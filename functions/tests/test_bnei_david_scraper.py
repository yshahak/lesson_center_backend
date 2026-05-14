#!/usr/bin/env python3
"""
Unit tests for the Bnei David WordPress scraper.
All tests use mocks — no network calls, no Firestore writes.
"""

import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

# Make the functions/ directory importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.bnei_david_scraper import (
    _extract_audio_file_id,
    _extract_vimeo_id,
    _build_audio_url,
    _upsert_lesson,
    SOURCE_ID,
)


# ---------------------------------------------------------------------------
# HTML extraction tests
# ---------------------------------------------------------------------------

class TestExtractAudioFileId(unittest.TestCase):

    def test_extract_audio_file_id_standard(self):
        """Standard &file_id= in source attribute."""
        html = '<source src="https://bneidavid.org/wp-admin/admin-ajax.php?action=stream_audio&file_id=ABC123" type="audio/mpeg">'
        result = _extract_audio_file_id(html)
        self.assertEqual(result, "ABC123")

    def test_extract_audio_file_id_amp_encoded(self):
        """HTML-entity encoded &amp;file_id= variant."""
        html = '<source src="https://bneidavid.org/wp-admin/admin-ajax.php?action=stream_audio&amp;file_id=1b2Ddm7vbIXu4kFQoSS0T-NRheiTmnWZ_" type="audio/mpeg">'
        result = _extract_audio_file_id(html)
        self.assertEqual(result, "1b2Ddm7vbIXu4kFQoSS0T-NRheiTmnWZ_")

    def test_extract_audio_file_id_none_when_missing(self):
        """Returns None when no stream_audio pattern exists."""
        html = "<html><body>No audio here</body></html>"
        result = _extract_audio_file_id(html)
        self.assertIsNone(result)


class TestExtractVimeoId(unittest.TestCase):

    def test_extract_vimeo_id_from_iframe(self):
        """Extracts Vimeo ID from player.vimeo.com iframe src."""
        html = (
            '<iframe class="elementor-video-iframe" allowfullscreen '
            'src="https://player.vimeo.com/video/1191960680?color&autopause=0&loop=0"></iframe>'
        )
        result = _extract_vimeo_id(html)
        self.assertEqual(result, "1191960680")

    def test_extract_vimeo_id_none_when_missing(self):
        """Returns None when no Vimeo iframe exists."""
        html = "<html><body>No video here</body></html>"
        result = _extract_vimeo_id(html)
        self.assertIsNone(result)


class TestStreamAudioFileIdStoredNotUrl(unittest.TestCase):

    def test_stream_audio_file_id_stored_not_url(self):
        """
        Scraper stores the raw file_id, NOT a full URL.
        _extract_audio_file_id returns just the file_id value.
        _build_audio_url (a separate helper) constructs the URL from the file_id.
        The stored field (streamAudioFileId) must equal the file_id, not the URL.
        """
        html = '<source src="https://bneidavid.org/wp-admin/admin-ajax.php?action=stream_audio&file_id=FILE_ID_123" type="audio/mpeg">'
        file_id = _extract_audio_file_id(html)
        self.assertEqual(file_id, "FILE_ID_123")

        # Confirm the URL can be constructed separately — it must NOT equal the stored file_id
        full_url = _build_audio_url(file_id)
        self.assertNotEqual(file_id, full_url)
        self.assertIn("FILE_ID_123", full_url)
        self.assertIn("stream_audio", full_url)


# ---------------------------------------------------------------------------
# Upsert logic tests
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
        # Build mock query result: one snapshot per existing doc
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
        # No existing docs → empty result
        query_chain = MagicMock()
        query_chain.get.return_value = []
        lessons_col.where.return_value.where.return_value.limit.return_value = query_chain

    return db, lessons_col


def _make_lesson_data(**overrides):
    base = {
        "originalId": 37553,
        "title": "סיום המאמר | עבודת אלוקים [22]",
        "streamAudioFileId": "XYZ",
        "vimeoId": "1191960680",
        "ravId": "23",
        "seriesId": "ser_1a2c7b492b394685afda",
        "categoryId": "cat_abc",
        "dateStr": "2026-05-13",
        "duration": 3242,
        "timestamp": 1747148127,
    }
    base.update(overrides)
    return base


class TestUpsertCallsUpdateWhenLessonExists(unittest.TestCase):

    def test_upsert_calls_update_when_lesson_exists(self):
        """When a matching lesson exists, update() is called and set() is not."""
        existing = {
            "originalId": 37553,
            "sourceId": SOURCE_ID,
            "ravId": "23",
            "seriesId": None,
            "categoryId": None,
            "vimeoId": None,
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        # update() must have been called
        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        snap.reference.update.assert_called_once()

        # set() must NOT have been called on the lessons collection document
        lessons_col.document.assert_not_called()
        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["created"], 0)


class TestUpsertCallsSetWhenLessonNotExists(unittest.TestCase):

    def test_upsert_calls_set_when_lesson_not_exists(self):
        """When no matching lesson exists, set() is called and update() is not."""
        db, lessons_col = _make_db([])  # empty → not exists
        stats = {"created": 0, "updated": 0}

        with patch("scrapers.bnei_david_scraper.get_hash_for_id", return_value=999):
            _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        lessons_col.document.assert_called_once_with("999")
        lessons_col.document.return_value.set.assert_called_once()
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["updated"], 0)


class TestUpsertUpdatePreservesExistingAudioUrl(unittest.TestCase):

    def test_upsert_update_preserves_existing_audio_url(self):
        """update() payload does NOT include audioUrl — existing value is preserved."""
        existing = {
            "originalId": 37553,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "audioUrl": "https://old-audio-url/existing.mp3",
            "vimeoId": None,
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertNotIn("audioUrl", update_kwargs)
        self.assertNotIn("videoUrl", update_kwargs)


class TestUpsertAlwaysSetsVimeoId(unittest.TestCase):

    def test_upsert_always_sets_vimeo_id(self):
        """update() always includes vimeoId — even when the new value is None."""
        existing = {
            "originalId": 37553,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "vimeoId": None,
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0}

        # Pass lesson_data with vimeoId=None
        _upsert_lesson(
            _make_lesson_data(vimeoId=None),
            db, "", dry_run=False, stats=stats
        )

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertIn("vimeoId", update_kwargs)


class TestUpsertOnlySetsNullTaxonomy(unittest.TestCase):

    def test_upsert_only_sets_taxonomy_if_null(self):
        """
        update() includes ravId in payload only when the existing doc has ravId=None.
        When existing doc already has a ravId, it is NOT overwritten.
        """
        existing_with_rav = {
            "originalId": 37553,
            "sourceId": SOURCE_ID,
            "ravId": "23",  # already set
            "seriesId": None,
            "categoryId": None,
            "vimeoId": None,
        }
        db, lessons_col = _make_db([existing_with_rav])
        stats = {"created": 0, "updated": 0}

        _upsert_lesson(
            _make_lesson_data(ravId="99"),  # scraper found a different rav
            db, "", dry_run=False, stats=stats
        )

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        # ravId must NOT appear — existing value wins
        self.assertNotIn("ravId", update_kwargs)


class TestScrapeSourceIsArray(unittest.TestCase):

    def test_scrape_source_is_array(self):
        """New lessons have scrapeSource as a list ['new_site'], not a string."""
        db_create, lessons_col = _make_db([])
        stats = {"created": 0, "updated": 0}

        with patch("scrapers.bnei_david_scraper.get_hash_for_id", return_value=1234):
            _upsert_lesson(_make_lesson_data(), db_create, "", dry_run=False, stats=stats)

        set_kwargs = lessons_col.document.return_value.set.call_args[0][0]
        self.assertIsInstance(set_kwargs["scrapeSource"], list)
        self.assertEqual(set_kwargs["scrapeSource"], ["new_site"])


class TestUpsertAppendsToExistingScrapeSource(unittest.TestCase):

    def test_upsert_appends_to_existing_scrape_source(self):
        """UPDATE uses ArrayUnion(['new_site']) so it appends to any existing array."""
        from google.cloud.firestore import ArrayUnion

        existing = {
            "originalId": 37553,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "vimeoId": None,
            "scrapeSource": ["old_site"],
        }
        db, lessons_col = _make_db([existing])
        stats = {"created": 0, "updated": 0}

        _upsert_lesson(_make_lesson_data(), db, "", dry_run=False, stats=stats)

        snap = lessons_col.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        update_kwargs = snap.reference.update.call_args[0][0]
        self.assertIn("scrapeSource", update_kwargs)
        # Must be an ArrayUnion sentinel, not a plain list or string
        self.assertIsInstance(update_kwargs["scrapeSource"], ArrayUnion)


class TestDryRunDoesNotWrite(unittest.TestCase):

    def test_dry_run_does_not_write(self):
        """dry_run=True must not call set() or update() on any Firestore ref."""
        # Test CREATE path
        db_create, lessons_col = _make_db([])
        stats = {"created": 0, "updated": 0}

        with patch("scrapers.bnei_david_scraper.get_hash_for_id", return_value=42):
            _upsert_lesson(_make_lesson_data(), db_create, "", dry_run=True, stats=stats)

        lessons_col.document.return_value.set.assert_not_called()

        # Test UPDATE path
        existing = {
            "originalId": 37553,
            "sourceId": SOURCE_ID,
            "ravId": None,
            "seriesId": None,
            "categoryId": None,
            "vimeoId": None,
        }
        db_update, lessons_col_u = _make_db([existing])
        stats2 = {"created": 0, "updated": 0}

        _upsert_lesson(_make_lesson_data(), db_update, "", dry_run=True, stats=stats2)

        snap = lessons_col_u.where.return_value.where.return_value.limit.return_value.get.return_value[0]
        snap.reference.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
