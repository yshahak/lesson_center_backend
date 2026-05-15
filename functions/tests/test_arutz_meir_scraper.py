#!/usr/bin/env python3
"""
Unit tests for the Arutz Meir WordPress scraper.
All tests use mocks — no network calls, no Firestore writes.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Make the functions/ directory importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.arutz_meir_scraper import (
    _extract_original_id_from_slug,
    _extract_site_audio_url,
    _extract_vimeo_id,
    _find_existing_by_title,
    _upsert_lesson,
    SOURCE_ID,
)


# ---------------------------------------------------------------------------
# Slug / originalId extraction tests
# ---------------------------------------------------------------------------

class TestExtractOriginalIdFromSlug(unittest.TestCase):

    def test_extract_original_id_from_slug_standard(self):
        """Standard slug 'shiur-10915' returns 10915."""
        result = _extract_original_id_from_slug("shiur-10915")
        self.assertEqual(result, 10915)

    def test_extract_original_id_from_slug_fallback(self):
        """Non-matching slug (title-based) returns None."""
        result = _extract_original_id_from_slug("parashat-noach-2024")
        self.assertIsNone(result)

    def test_extract_original_id_from_slug_empty(self):
        """Empty string returns None."""
        result = _extract_original_id_from_slug("")
        self.assertIsNone(result)

    def test_extract_original_id_from_slug_no_number(self):
        """Slug with no number returns None."""
        result = _extract_original_id_from_slug("shiur-abc")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# HTML extraction tests
# ---------------------------------------------------------------------------

class TestExtractSiteAudioUrl(unittest.TestCase):

    def test_extract_site_audio_url_from_html(self):
        """Extracts audio URL from <audio src="..."> tag."""
        html = (
            '<audio class="jet-audio-player" '
            'src="https://mp3.meirtv.co.il//wp2/388996.mp3" '
            'preload="none"></audio>'
        )
        result = _extract_site_audio_url(html)
        self.assertEqual(result, "https://mp3.meirtv.co.il//wp2/388996.mp3")

    def test_extract_site_audio_url_single_quotes(self):
        """Works with single-quoted src attribute."""
        html = "<audio src='https://mp3.meirtv.co.il/wp2/215928.mp3'></audio>"
        result = _extract_site_audio_url(html)
        self.assertEqual(result, "https://mp3.meirtv.co.il/wp2/215928.mp3")

    def test_extract_site_audio_url_returns_none_when_missing(self):
        """Returns None when no <audio src> tag exists."""
        html = "<html><body>No audio here</body></html>"
        result = _extract_site_audio_url(html)
        self.assertIsNone(result)


class TestExtractVimeoId(unittest.TestCase):

    def test_extract_vimeo_id_from_shortcode(self):
        """Extracts Vimeo ID from [fwdevp video_path="https://vimeo.com/123456"] shortcode."""
        html = (
            '[fwdevp preset_id="meirtv" video_path="https://vimeo.com/1192170518" '
            'start_at_video="1" playback_rate_speed="1"]'
        )
        result = _extract_vimeo_id(html)
        self.assertEqual(result, "1192170518")

    def test_extract_vimeo_id_single_quotes(self):
        """Works with single-quoted video_path."""
        html = "[fwdevp video_path='https://vimeo.com/714904873']"
        result = _extract_vimeo_id(html)
        self.assertEqual(result, "714904873")

    def test_extract_vimeo_id_returns_none_when_missing(self):
        """Returns None when no fwdevp shortcode exists."""
        html = "<html><body>No video here</body></html>"
        result = _extract_vimeo_id(html)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _make_db(existing_docs=None):
    """
    Build a minimal Firestore mock.
    existing_docs: list of dicts representing existing lesson documents,
                   or None / empty list for no existing docs.
    """
    db = MagicMock()
    lessons_col = MagicMock()
    db.collection.return_value = lessons_col

    if existing_docs:
        mock_snapshots = []
        for doc_data in existing_docs:
            snap = MagicMock()
            snap.to_dict.return_value = doc_data
            snap.reference = MagicMock()
            mock_snapshots.append(snap)

        query_chain = MagicMock()
        query_chain.get.return_value = mock_snapshots
        lessons_col.where.return_value.where.return_value.limit.return_value = query_chain
    else:
        query_chain = MagicMock()
        query_chain.get.return_value = []
        lessons_col.where.return_value.where.return_value.limit.return_value = query_chain

    return db, lessons_col


def _make_lesson_data(**overrides):
    base = {
        "originalId": 388996,
        "title": "שיעור לדוגמה",
        "siteAudioUrl": "https://mp3.meirtv.co.il/wp2/388996.mp3",
        "vimeoId": "1192170518",
        "ravId": "rav_firestore_doc_id",
        "seriesId": "series_firestore_doc_id",
        "categoryId": "category_firestore_doc_id",
        "dateStr": "2026-05-14",
        "duration": 0,
        "timestamp": 1747180000,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Upsert logic tests
# ---------------------------------------------------------------------------

class TestUpsertNullsBrokenAudioUrl(unittest.TestCase):

    def test_upsert_nulls_broken_audio_url(self):
        """Existing doc with storage.googleapis.com audioUrl → update sets audioUrl=None."""
        existing = {
            "originalId": 388996,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "audioUrl": "https://storage.googleapis.com/meirtvmp3/archive/file.mp3",
            "videoUrl": "http://player.vimeo.com/external/123.sd.mp4?s=abc",
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertIn("audioUrl", update_kwargs)
        self.assertIsNone(update_kwargs["audioUrl"])
        self.assertEqual(stats["broken_audio_nulled"], 1)


class TestUpsertPreservesWorkingAudioUrl(unittest.TestCase):

    def test_upsert_preserves_working_audio_url(self):
        """Existing doc with mp3.meirtv.co.il audioUrl → audioUrl NOT in update payload."""
        existing = {
            "originalId": 388996,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "audioUrl": "http://mp3.meirtv.co.il/wp2/221041.mp3",
            "videoUrl": None,
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertNotIn("audioUrl", update_kwargs)
        self.assertEqual(stats["broken_audio_nulled"], 0)


class TestUpsertNeverTouchesVideoUrl(unittest.TestCase):

    def test_upsert_never_touches_video_url(self):
        """videoUrl is never included in the UPDATE payload."""
        existing = {
            "originalId": 388996,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "audioUrl": None,
            "videoUrl": "http://player.vimeo.com/external/999.sd.mp4?s=tok",
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertNotIn("videoUrl", update_kwargs)


class TestUpsertCallsSetForNewLesson(unittest.TestCase):

    def test_upsert_calls_set_for_new_lesson(self):
        """When no matching lesson exists, set() is called and update() is not."""
        db, lessons_col = _make_db([])  # empty → not exists
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        with patch("scrapers.arutz_meir_scraper.get_hash_for_id", return_value=12345):
            _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        lessons_col.document.assert_called_once_with("12345")
        lessons_col.document.return_value.set.assert_called_once()
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["updated"], 0)


class TestUpsertCallsUpdateForExisting(unittest.TestCase):

    def test_upsert_calls_update_for_existing(self):
        """When matching lesson exists, update() is called and set() is not."""
        existing = {
            "originalId": 388996,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "audioUrl": None,
            "videoUrl": None,
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        snap.reference.update.assert_called_once()
        lessons_col.document.assert_not_called()
        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["created"], 0)


class TestScrapeSourceArrayOnCreate(unittest.TestCase):

    def test_scrape_source_array_on_create(self):
        """New lesson gets scrapeSource as a list ['new_site']."""
        db, lessons_col = _make_db([])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        with patch("scrapers.arutz_meir_scraper.get_hash_for_id", return_value=9999):
            _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        set_kwargs = lessons_col.document.return_value.set.call_args[0][0]
        self.assertIsInstance(set_kwargs["scrapeSource"], list)
        self.assertEqual(set_kwargs["scrapeSource"], ["new_site"])


class TestScrapeSourceArrayUnionOnUpdate(unittest.TestCase):

    def test_scrape_source_array_union_on_update(self):
        """UPDATE uses ArrayUnion(['new_site']) so it appends to any existing array."""
        from google.cloud.firestore import ArrayUnion

        existing = {
            "originalId": 388996,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "audioUrl": None,
            "videoUrl": None,
            "scrapeSource": ["old_site"],
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertIn("scrapeSource", update_kwargs)
        self.assertIsInstance(update_kwargs["scrapeSource"], ArrayUnion)


class TestDryRunNoWrites(unittest.TestCase):

    def test_dry_run_no_writes_on_create(self):
        """dry_run=True must not call set() on new lesson."""
        db, lessons_col = _make_db([])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        with patch("scrapers.arutz_meir_scraper.get_hash_for_id", return_value=42):
            _upsert_lesson(_make_lesson_data(), db, "", dry_run=True, stats=stats)

        lessons_col.document.return_value.set.assert_not_called()

    def test_dry_run_no_writes_on_update(self):
        """dry_run=True must not call update() on existing lesson."""
        existing = {
            "originalId": 388996,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "audioUrl": "https://storage.googleapis.com/meirtvmp3/bad.mp3",
            "videoUrl": None,
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=True, stats=stats)

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        snap.reference.update.assert_not_called()


class TestUpsertOnlySetsTaxonomyIfNull(unittest.TestCase):

    def test_upsert_does_not_overwrite_existing_taxonomy(self):
        """
        update() does NOT include ravId when the existing doc already has one.
        """
        existing = {
            "originalId": 388996,
            "sourceId": SOURCE_ID,
            "ravId": "existing_rav_doc_id",  # already set
            "seriesId": None,
            "categoryId": None,
            "audioUrl": None,
            "videoUrl": None,
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(
            _make_lesson_data(ravId="new_rav_doc_id"),
            db, "", dry_run=False, stats=stats
        )

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertNotIn("ravId", update_kwargs)

    def test_upsert_sets_null_taxonomy(self):
        """update() includes ravId when existing doc has ravId=None."""
        existing = {
            "originalId": 388996,
            "sourceId": SOURCE_ID,
            "ravId": None,  # null — should be filled in
            "seriesId": None,
            "categoryId": None,
            "audioUrl": None,
            "videoUrl": None,
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(
            _make_lesson_data(ravId="new_rav_doc_id"),
            db, "", dry_run=False, stats=stats
        )

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertIn("ravId", update_kwargs)
        self.assertEqual(update_kwargs["ravId"], "new_rav_doc_id")


# ---------------------------------------------------------------------------
# Title-based dedup fallback tests
# ---------------------------------------------------------------------------

def _make_db_with_title_fallback(originalid_docs=None, title_docs=None):
    """
    Build a Firestore mock that handles both:
    - originalId-based query (.where().where().limit().get())  → originalid_docs
    - title-based query (.where().where().limit().stream())    → title_docs

    The first .where() call on lessons_col returns a query object.
    The second .where() is chained. We need separate chains for each query type.
    We differentiate by inspecting call args on the second .where().
    """
    db = MagicMock()
    lessons_col = MagicMock()
    db.collection.return_value = lessons_col

    def _make_snapshots(docs):
        snaps = []
        if docs:
            for d in docs:
                snap = MagicMock()
                snap.to_dict.return_value = d
                snap.reference = MagicMock()
                snaps.append(snap)
        return snaps

    orig_snaps = _make_snapshots(originalid_docs or [])
    title_snaps = _make_snapshots(title_docs or [])

    # First .where("sourceId", "==", SOURCE_ID) is shared; second .where distinguishes queries.
    first_where = MagicMock()
    lessons_col.where.return_value = first_where

    def second_where_side_effect(field, op, val):
        chain = MagicMock()
        limit_chain = MagicMock()
        chain.limit.return_value = limit_chain

        if field == "originalId":
            limit_chain.get.return_value = orig_snaps
        elif field == "title":
            limit_chain.stream.return_value = iter(title_snaps)

        return chain

    first_where.where.side_effect = second_where_side_effect

    return db, lessons_col


class TestSlugFallbackTriggersTitleSearch(unittest.TestCase):

    def test_slug_fallback_triggers_title_search(self):
        """When is_slug_fallback=True and no doc found by originalId, title query is attempted."""
        db, lessons_col = _make_db_with_title_fallback(originalid_docs=[], title_docs=[])
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        with patch("scrapers.arutz_meir_scraper.get_hash_for_id", return_value=99):
            _upsert_lesson(
                _make_lesson_data(originalId=169176),
                db, "", dry_run=False, stats=stats,
                is_slug_fallback=True,
            )

        # The lessons collection should have been queried twice:
        # once for originalId lookup (.get) and once for title lookup (.stream)
        first_where = lessons_col.where.return_value
        call_fields = [c.args[0] for c in first_where.where.call_args_list]
        self.assertIn("originalId", call_fields)
        self.assertIn("title", call_fields)


class TestTitleMatchUpdatesInsteadOfCreates(unittest.TestCase):

    def test_title_match_updates_instead_of_creates(self):
        """When slug fallback is used and title found in Firestore, update() is called not set()."""
        existing_by_title = {
            "originalId": 10915,   # old PostgreSQL ID in Firestore
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "audioUrl": None,
            "videoUrl": None,
            "title": "שיעור לדוגמה",
        }
        db, lessons_col = _make_db_with_title_fallback(
            originalid_docs=[],           # not found by WP post_id
            title_docs=[existing_by_title],  # found by title
        )
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        _upsert_lesson(
            _make_lesson_data(originalId=169176),  # WP post_id as originalId
            db, "", dry_run=False, stats=stats,
            is_slug_fallback=True,
        )

        # Should update the existing doc, not create a new one
        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats.get("title_fallback_hit", 0), 1)

        # set() must NOT have been called (no new doc created)
        lessons_col.document.assert_not_called()


class TestNoTitleMatchCreatesNew(unittest.TestCase):

    def test_no_title_match_creates_new(self):
        """When slug fallback is used and title NOT found in Firestore, set() is called."""
        db, lessons_col = _make_db_with_title_fallback(
            originalid_docs=[],   # not found by originalId
            title_docs=[],        # not found by title either
        )
        stats = {"created": 0, "updated": 0, "broken_audio_nulled": 0}

        with patch("scrapers.arutz_meir_scraper.get_hash_for_id", return_value=77777):
            _upsert_lesson(
                _make_lesson_data(originalId=169176),
                db, "", dry_run=False, stats=stats,
                is_slug_fallback=True,
            )

        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(stats.get("title_fallback_hit", 0), 0)
        lessons_col.document.assert_called_once_with("77777")
        lessons_col.document.return_value.set.assert_called_once()


if __name__ == "__main__":
    unittest.main()
