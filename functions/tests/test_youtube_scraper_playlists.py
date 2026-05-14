"""
Tests for playlist-based series classification in youtube_scraper.

TDD: all tests written before implementation.

Feature: Instead of assigning all videos to "כללי", assign each video to the
YouTube playlist it belongs to. Playlists become series docs in Firestore.

Playlist map caching stored in source doc:
  - playlistMap: {videoId: seriesDocId}
  - lastPlaylistScanAt: ISO timestamp of last full scan

Refresh conditions:
  - New videos were found in this scrape run
  - A new playlist was detected (playlist IDs changed since last scan)
  - More than 7 days elapsed since lastPlaylistScanAt
  - playlistMap is missing entirely (first run)

Fallback: video not in any named playlist → assigned to "כללי" series.
Uploads playlist (auto-generated, named "Uploads from..." or ID starting "UU")
must be excluded.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ---------------------------------------------------------------------------
# Fake Firestore infrastructure (extended from test_youtube_scraper_labels.py)
# ---------------------------------------------------------------------------

class FakeDoc:
    def __init__(self, data, doc_id=None, ref=None):
        self._data = data
        self.id = doc_id
        self._ref = ref

    def to_dict(self):
        return self._data

    @property
    def exists(self):
        return self._data is not None

    @property
    def reference(self):
        if self._ref is not None:
            return self._ref
        return FakeDocRef(self.id)


class FakeQuery:
    def __init__(self, docs):
        self._docs = docs
        self._limit = None

    def where(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def get(self):
        if self._limit is not None:
            return self._docs[:self._limit]
        return self._docs


class FakeDocRef:
    def __init__(self, doc_id=None, initial_data=None):
        self.id = doc_id
        self._data = initial_data
        self.set_calls = []
        self.update_calls = []
        self.delete_calls = []

    @property
    def exists(self):
        return self._data is not None

    def get(self):
        return FakeDoc(self._data, self.id, ref=self)

    def set(self, data):
        self._data = data
        self.set_calls.append(data)

    def update(self, data):
        if self._data is None:
            self._data = {}
        self._data.update(data)
        self.update_calls.append(data)

    def delete(self):
        self._data = None
        self.delete_calls.append(True)


class FakeCollection:
    def __init__(self, docs=None):
        # docs: list of (doc_id, dict) tuples OR list of FakeDoc
        self._doc_refs = {}  # doc_id -> FakeDocRef
        if docs:
            for item in docs:
                if isinstance(item, tuple):
                    doc_id, data = item
                    self._doc_refs[doc_id] = FakeDocRef(doc_id, data)
                elif isinstance(item, FakeDoc):
                    self._doc_refs[item.id] = FakeDocRef(item.id, item._data)

    def where(self, field=None, op=None, value=None, *args, **kwargs):
        # Return docs where field == value (simple equality only)
        if field and op == '==' and value is not None:
            matched = [
                FakeDoc(ref._data, ref.id, ref=ref)
                for ref in self._doc_refs.values()
                if ref._data and ref._data.get(field) == value
            ]
            return FakeQuery(matched)
        return FakeQuery([
            FakeDoc(ref._data, ref.id, ref=ref)
            for ref in self._doc_refs.values()
            if ref._data is not None
        ])

    def document(self, doc_id=None):
        if doc_id not in self._doc_refs:
            self._doc_refs[doc_id] = FakeDocRef(doc_id, None)
        return self._doc_refs[doc_id]

    def get(self):
        return [
            FakeDoc(ref._data, ref.id, ref=ref)
            for ref in self._doc_refs.values()
            if ref._data is not None
        ]

    @property
    def doc_refs(self):
        return self._doc_refs


class FakeBatch:
    def __init__(self):
        self.updates = []
        self.sets = []

    def update(self, ref, data):
        self.updates.append((ref, data))

    def set(self, ref, data):
        self.sets.append((ref, data))

    def commit(self):
        # Apply updates to fake doc refs
        for ref, data in self.updates:
            if hasattr(ref, 'update'):
                ref.update(data)
        for ref, data in self.sets:
            if hasattr(ref, 'set'):
                ref.set(data)


class FakeDB:
    def __init__(self, collections=None):
        # collections: dict of collection_name -> FakeCollection
        self._collections = collections or {}
        self._batch = FakeBatch()

    def collection(self, name):
        # Strip prefix (e.g. "test_sources" → use "sources" key or full name)
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]

    def batch(self):
        return self._batch


class FakeFirestoreDB:
    def __init__(self, collections=None, collection_prefix=""):
        self.db = FakeDB(collections)
        self.collection_prefix = collection_prefix


# ---------------------------------------------------------------------------
# YouTube API fake helpers
# ---------------------------------------------------------------------------

def make_youtube_fake(playlists=None, playlist_items=None,
                      channel_uploads_id="UUfake_uploads",
                      channel_id="UCfakechannel"):
    """
    Build a mock youtube client.

    playlists: list of dicts with {id, title}
    playlist_items: dict of {playlist_id: [videoId, ...]}
    """
    playlists = playlists or []
    playlist_items = playlist_items or {}

    # channels().list().execute()
    channel_response = {
        'items': [{
            'contentDetails': {
                'relatedPlaylists': {
                    'uploads': channel_uploads_id
                }
            }
        }]
    }

    def channels_list(**kwargs):
        m = MagicMock()
        m.execute.return_value = channel_response
        return m

    def playlists_list(**kwargs):
        items = [
            {'id': p['id'], 'snippet': {'title': p['title']}}
            for p in playlists
        ]
        m = MagicMock()
        m.execute.return_value = {'items': items, 'nextPageToken': None}
        return m

    def playlist_items_list(**kwargs):
        pl_id = kwargs.get('playlistId', '')
        video_ids = playlist_items.get(pl_id, [])
        items = [
            {'snippet': {'resourceId': {'videoId': vid}}}
            for vid in video_ids
        ]
        m = MagicMock()
        m.execute.return_value = {'items': items, 'nextPageToken': None}
        return m

    # videos().list().execute() — returns minimal snippet+contentDetails
    def videos_list(**kwargs):
        ids_str = kwargs.get('id', '')
        ids = ids_str.split(',') if ids_str else []
        items = []
        for vid in ids:
            items.append({
                'id': vid,
                'snippet': {
                    'title': f'Video {vid}',
                    'publishedAt': '2024-01-01T00:00:00Z',
                },
                'contentDetails': {
                    'duration': 'PT10M'
                }
            })
        m = MagicMock()
        m.execute.return_value = {'items': items}
        return m

    # uploads playlistItems (always returns nothing by default so tests control new videos)
    def uploads_playlist_items_list(**kwargs):
        pl_id = kwargs.get('playlistId', '')
        video_ids = playlist_items.get(pl_id, [])
        items = [
            {'snippet': {'resourceId': {'videoId': vid}}}
            for vid in video_ids
        ]
        m = MagicMock()
        m.execute.return_value = {'items': items, 'nextPageToken': None}
        return m

    youtube_mock = MagicMock()
    youtube_mock.channels.return_value.list.side_effect = channels_list
    youtube_mock.playlists.return_value.list.side_effect = playlists_list
    youtube_mock.playlistItems.return_value.list.side_effect = playlist_items_list
    youtube_mock.videos.return_value.list.side_effect = videos_list

    return youtube_mock


# ---------------------------------------------------------------------------
# Import scraper module
# ---------------------------------------------------------------------------

from collections import defaultdict

import scrapers.youtube_scraper as scraper_module


# ---------------------------------------------------------------------------
# Base test class with shared setup helpers
# ---------------------------------------------------------------------------

SOURCE_ID = 50
CHANNEL_ID = "UCfakechannel"
UPLOADS_PLAYLIST_ID = "UUfake_uploads"
CATEGORY = "test_category"
LABEL = "test_label"
CATEGORY_DOC_ID = "cat_test_abc"


def _iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _make_fake_db(source_data=None, existing_series=None):
    """Build a FakeFirestoreDB with the given source doc and optional series docs."""
    sources_col = FakeCollection()
    if source_data is not None:
        # Store source with a fixed doc ID "src_50"
        sources_col._doc_refs["src_50"] = FakeDocRef("src_50", source_data)

    series_col = FakeCollection()
    if existing_series:
        for ser_id, ser_data in existing_series.items():
            series_col._doc_refs[ser_id] = FakeDocRef(ser_id, ser_data)

    collections = {
        'sources': sources_col,
        'series': series_col,
        'categories': FakeCollection(),
        'lessons': FakeCollection(),
        'labels': FakeCollection(),
    }
    return FakeFirestoreDB(collections=collections)


def _run_process_channel_videos(youtube_mock, source_doc_ref, exists_lesson_ids=None,
                                 fake_db=None):
    """Helper to call process_channel_videos with standard args."""
    new_lesson_ids = []
    categories_affected = defaultdict(int)
    series_affected = defaultdict(int)

    scraper_module.youtube = youtube_mock
    if fake_db:
        scraper_module.firestore_db = fake_db

    scraper_module.process_channel_videos(
        channel_id=CHANNEL_ID,
        source_id=SOURCE_ID,
        category=CATEGORY,
        label=LABEL,
        exists_lesson_ids=exists_lesson_ids or set(),
        new_lesson_ids=new_lesson_ids,
        categories_affected=categories_affected,
        series_affected=series_affected,
        category_doc_id=CATEGORY_DOC_ID,
        source_doc_ref=source_doc_ref,
    )
    return new_lesson_ids, series_affected


# ===========================================================================
# Test cases
# ===========================================================================

class TestPlaylistSeries(unittest.TestCase):

    # -----------------------------------------------------------------------
    # 1. New video gets playlist series, NOT כללי
    # -----------------------------------------------------------------------

    def test_new_video_gets_playlist_series_not_כללי(self):
        """A new video that belongs to a named playlist must get that playlist's seriesId."""
        video_id = "abc123"
        playlist_id = "PLfakeparasha"
        playlist_title = "פרשת השבוע"

        youtube_mock = make_youtube_fake(
            playlists=[{'id': playlist_id, 'title': playlist_title}],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [video_id],   # uploads: this video exists
                playlist_id: [video_id],           # named playlist: same video
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        fake_db = _make_fake_db(source_data={
            'originalId': SOURCE_ID,
            'lessonIds': [],
            'channelId': CHANNEL_ID,
        })

        source_doc_ref = fake_db.db.collection('sources').document("src_50")
        new_lesson_ids, series_affected = _run_process_channel_videos(
            youtube_mock, source_doc_ref, exists_lesson_ids=set(), fake_db=fake_db
        )

        # Identify the series docs in Firestore
        series_col = fake_db.db.collection('series')
        all_series = {
            doc_id: ref._data
            for doc_id, ref in series_col.doc_refs.items()
            if ref._data is not None
        }

        # Must have a series doc for "פרשת השבוע"
        parasha_series = [s for s in all_series.values() if s.get('serie') == playlist_title]
        self.assertTrue(len(parasha_series) >= 1, f"Expected series doc for '{playlist_title}', got: {all_series}")

        # The lesson written for abc123 must use the parasha series doc ID, not כללי
        lessons_col = fake_db.db.collection('lessons')
        written_lessons = {
            doc_id: ref._data
            for doc_id, ref in lessons_col.doc_refs.items()
            if ref._data is not None
        }
        self.assertEqual(len(written_lessons), 1, "Expected exactly one new lesson written")

        lesson = list(written_lessons.values())[0]
        lesson_series_id = lesson.get('seriesId')

        # Find כללי series doc ID (if any)
        כללי_series_ids = {doc_id for doc_id, s in all_series.items() if s.get('serie') == 'כללי'}
        self.assertNotIn(lesson_series_id, כללי_series_ids,
                         f"Lesson should NOT be in כללי series; seriesId={lesson_series_id}")

        # Lesson's seriesId must be the parasha series doc
        parasha_series_ids = {doc_id for doc_id, s in all_series.items() if s.get('serie') == playlist_title}
        self.assertIn(lesson_series_id, parasha_series_ids,
                      f"Lesson seriesId {lesson_series_id!r} not in parasha series {parasha_series_ids}")

    # -----------------------------------------------------------------------
    # 2. Video not in any playlist → כללי
    # -----------------------------------------------------------------------

    def test_video_not_in_any_playlist_gets_כללי(self):
        """A new video not in any named playlist falls back to the כללי series."""
        video_id_in_playlist = "abc123"
        video_id_not_in_playlist = "xyz999"
        playlist_id = "PLfakeparasha"

        youtube_mock = make_youtube_fake(
            playlists=[{'id': playlist_id, 'title': "פרשת השבוע"}],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [video_id_in_playlist, video_id_not_in_playlist],
                playlist_id: [video_id_in_playlist],  # only the first video
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        fake_db = _make_fake_db(source_data={
            'originalId': SOURCE_ID,
            'lessonIds': [],
            'channelId': CHANNEL_ID,
        })

        source_doc_ref = fake_db.db.collection('sources').document("src_50")
        _run_process_channel_videos(
            youtube_mock, source_doc_ref, exists_lesson_ids=set(), fake_db=fake_db
        )

        lessons_col = fake_db.db.collection('lessons')
        series_col = fake_db.db.collection('series')

        all_series = {
            doc_id: ref._data
            for doc_id, ref in series_col.doc_refs.items()
            if ref._data is not None
        }
        כללי_series_ids = {doc_id for doc_id, s in all_series.items() if s.get('serie') == 'כללי'}

        written_lessons = [ref._data for ref in lessons_col.doc_refs.values() if ref._data]
        # Find the lesson for xyz999 — it won't have the exact same lesson_id calculation,
        # so we check that at least one lesson has a כללי seriesId
        self.assertTrue(len(written_lessons) >= 1, "Expected lessons to be written")

        # All lessons not in the named playlist must have כללי seriesId
        # (We can't easily identify which lesson is xyz999 without replicating hash logic,
        # so we check: at least one lesson uses כללי)
        כללי_lessons = [l for l in written_lessons if l.get('seriesId') in כללי_series_ids]
        self.assertTrue(len(כללי_lessons) >= 1,
                        f"Expected at least one lesson in כללי series. Lessons: {written_lessons}")

    # -----------------------------------------------------------------------
    # 3. Playlist map NOT refreshed within 7 days + no new videos
    # -----------------------------------------------------------------------

    def test_playlist_map_not_refreshed_within_7_days_no_new_videos(self):
        """
        When lastPlaylistScanAt < 7 days ago and no new videos are found,
        youtube.playlists().list() must NOT be called.
        """
        # All videos already exist → no new videos
        from utils.firestore_helper import get_hash_for_string, get_hash_for_id
        existing_video_id = "existingvid"
        existing_lesson_id = get_hash_for_id(SOURCE_ID, get_hash_for_string(existing_video_id))

        youtube_mock = make_youtube_fake(
            playlists=[{'id': "PLfake", 'title': "test"}],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [existing_video_id],
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        source_data = {
            'originalId': SOURCE_ID,
            'lessonIds': [existing_lesson_id],
            'channelId': CHANNEL_ID,
            'lastPlaylistScanAt': _iso_days_ago(3),  # 3 days ago (< 7)
            'playlistMap': {'some_video': 'some_series_doc'},
        }
        fake_db = _make_fake_db(source_data=source_data)
        source_doc_ref = fake_db.db.collection('sources').document("src_50")

        _run_process_channel_videos(
            youtube_mock, source_doc_ref,
            exists_lesson_ids={existing_lesson_id},
            fake_db=fake_db
        )

        # playlists().list() must NOT have been called
        youtube_mock.playlists.return_value.list.assert_not_called()

    # -----------------------------------------------------------------------
    # 4. Playlist map refreshed when new videos found (even if < 7 days)
    # -----------------------------------------------------------------------

    def test_playlist_map_refreshed_when_new_videos_found(self):
        """
        When new videos ARE found, playlist map must be refreshed
        even if lastPlaylistScanAt is recent (< 7 days).
        """
        new_video_id = "brandnewvideo"

        youtube_mock = make_youtube_fake(
            playlists=[{'id': "PLfake", 'title': "שיעורים"}],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [new_video_id],
                "PLfake": [new_video_id],
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        source_data = {
            'originalId': SOURCE_ID,
            'lessonIds': [],  # no existing lessons → new_video_id is new
            'channelId': CHANNEL_ID,
            'lastPlaylistScanAt': _iso_days_ago(3),  # < 7 days
            'playlistMap': {},
        }
        fake_db = _make_fake_db(source_data=source_data)
        source_doc_ref = fake_db.db.collection('sources').document("src_50")

        _run_process_channel_videos(
            youtube_mock, source_doc_ref,
            exists_lesson_ids=set(),
            fake_db=fake_db
        )

        # playlists().list() MUST have been called
        youtube_mock.playlists.return_value.list.assert_called()

    # -----------------------------------------------------------------------
    # 5. Playlist map refreshed after 7 days (no new videos)
    # -----------------------------------------------------------------------

    def test_playlist_map_refreshed_after_7_days(self):
        """
        When lastPlaylistScanAt > 7 days ago, playlist map must be refreshed
        even if no new videos were found.
        """
        from utils.firestore_helper import get_hash_for_string, get_hash_for_id
        existing_video_id = "oldvid"
        existing_lesson_id = get_hash_for_id(SOURCE_ID, get_hash_for_string(existing_video_id))

        youtube_mock = make_youtube_fake(
            playlists=[{'id': "PLfake", 'title': "test"}],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [existing_video_id],
                "PLfake": [],
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        source_data = {
            'originalId': SOURCE_ID,
            'lessonIds': [existing_lesson_id],
            'channelId': CHANNEL_ID,
            'lastPlaylistScanAt': _iso_days_ago(8),  # 8 days ago → stale
            'playlistMap': {'some_video': 'some_series_doc'},
        }
        fake_db = _make_fake_db(source_data=source_data)
        source_doc_ref = fake_db.db.collection('sources').document("src_50")

        _run_process_channel_videos(
            youtube_mock, source_doc_ref,
            exists_lesson_ids={existing_lesson_id},
            fake_db=fake_db
        )

        # playlists().list() MUST have been called
        youtube_mock.playlists.return_value.list.assert_called()

    # -----------------------------------------------------------------------
    # 6. Playlist map refreshed on first run (no playlistMap)
    # -----------------------------------------------------------------------

    def test_playlist_map_refreshed_on_first_run(self):
        """
        When source doc has no playlistMap and no lastPlaylistScanAt,
        playlist map must be fetched (first run scenario).
        """
        new_video_id = "newvid"

        youtube_mock = make_youtube_fake(
            playlists=[{'id': "PLfake", 'title': "שיעורים"}],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [new_video_id],
                "PLfake": [new_video_id],
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        source_data = {
            'originalId': SOURCE_ID,
            'lessonIds': [],
            'channelId': CHANNEL_ID,
            # No playlistMap, no lastPlaylistScanAt
        }
        fake_db = _make_fake_db(source_data=source_data)
        source_doc_ref = fake_db.db.collection('sources').document("src_50")

        _run_process_channel_videos(
            youtube_mock, source_doc_ref,
            exists_lesson_ids=set(),
            fake_db=fake_db
        )

        # playlists().list() MUST have been called
        youtube_mock.playlists.return_value.list.assert_called()

    # -----------------------------------------------------------------------
    # 7. Uploads playlist excluded from series
    # -----------------------------------------------------------------------

    def test_uploads_playlist_excluded_from_series(self):
        """
        The auto-generated uploads playlist (ID starts with 'UU') must not
        become a series doc. Only user-created playlists become series.
        """
        user_playlist_id = "PLuser_shiurim"
        user_playlist_title = "שיעורים"
        video_id = "vid1"

        youtube_mock = make_youtube_fake(
            playlists=[
                {'id': UPLOADS_PLAYLIST_ID, 'title': 'Uploads from test channel'},
                {'id': user_playlist_id, 'title': user_playlist_title},
            ],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [video_id],
                user_playlist_id: [video_id],
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        source_data = {
            'originalId': SOURCE_ID,
            'lessonIds': [],
            'channelId': CHANNEL_ID,
        }
        fake_db = _make_fake_db(source_data=source_data)
        source_doc_ref = fake_db.db.collection('sources').document("src_50")

        _run_process_channel_videos(
            youtube_mock, source_doc_ref,
            exists_lesson_ids=set(),
            fake_db=fake_db
        )

        series_col = fake_db.db.collection('series')
        all_series = {
            doc_id: ref._data
            for doc_id, ref in series_col.doc_refs.items()
            if ref._data is not None
        }

        # The uploads playlist title must NOT appear as a series
        uploads_series = [s for s in all_series.values()
                          if s.get('serie') == 'Uploads from test channel']
        self.assertEqual(len(uploads_series), 0,
                         "Uploads playlist must not become a series doc")

        # The user playlist MUST appear as a series
        user_series = [s for s in all_series.values()
                       if s.get('serie') == user_playlist_title]
        self.assertTrue(len(user_series) >= 1,
                        f"Expected series doc for '{user_playlist_title}', got: {all_series}")

    # -----------------------------------------------------------------------
    # 8. Multiple playlists per video: last one wins
    # -----------------------------------------------------------------------

    def test_multiple_playlists_per_video_last_wins(self):
        """
        If a video is in multiple playlists, the last one processed wins.
        Playlists are processed in the order returned by the API.
        """
        video_id = "vid_multi"
        playlist_a_id = "PLfakeA"
        playlist_b_id = "PLfakeB"
        playlist_a_title = "Playlist A"
        playlist_b_title = "Playlist B"

        # The API returns A first, then B — so B is processed last → B wins
        youtube_mock = make_youtube_fake(
            playlists=[
                {'id': playlist_a_id, 'title': playlist_a_title},
                {'id': playlist_b_id, 'title': playlist_b_title},
            ],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [video_id],
                playlist_a_id: [video_id],
                playlist_b_id: [video_id],
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        source_data = {
            'originalId': SOURCE_ID,
            'lessonIds': [],
            'channelId': CHANNEL_ID,
        }
        fake_db = _make_fake_db(source_data=source_data)
        source_doc_ref = fake_db.db.collection('sources').document("src_50")

        _run_process_channel_videos(
            youtube_mock, source_doc_ref,
            exists_lesson_ids=set(),
            fake_db=fake_db
        )

        series_col = fake_db.db.collection('series')
        all_series = {
            doc_id: ref._data
            for doc_id, ref in series_col.doc_refs.items()
            if ref._data is not None
        }

        # Find series B doc ID
        series_b_ids = {doc_id for doc_id, s in all_series.items()
                        if s.get('serie') == playlist_b_title}
        self.assertTrue(len(series_b_ids) >= 1,
                        f"Expected series doc for '{playlist_b_title}'")

        # The lesson must have seriesId matching playlist B
        lessons_col = fake_db.db.collection('lessons')
        written_lessons = [ref._data for ref in lessons_col.doc_refs.values() if ref._data]
        self.assertEqual(len(written_lessons), 1, "Expected exactly one lesson")

        lesson_series_id = written_lessons[0].get('seriesId')
        self.assertIn(lesson_series_id, series_b_ids,
                      f"Expected lesson seriesId to be from playlist B, got {lesson_series_id!r}")

    # -----------------------------------------------------------------------
    # 9. Series docs created for playlists
    # -----------------------------------------------------------------------

    def test_series_docs_created_for_playlists(self):
        """
        A named playlist must produce a series doc in Firestore
        with serie=<playlist title> and sourceId=<source_id>.
        """
        playlist_id = "PLfake_parasha"
        playlist_title = "פרשת השבוע"
        video_ids = ["v1", "v2", "v3"]

        youtube_mock = make_youtube_fake(
            playlists=[{'id': playlist_id, 'title': playlist_title}],
            playlist_items={
                UPLOADS_PLAYLIST_ID: video_ids,
                playlist_id: video_ids,
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        source_data = {
            'originalId': SOURCE_ID,
            'lessonIds': [],
            'channelId': CHANNEL_ID,
        }
        fake_db = _make_fake_db(source_data=source_data)
        source_doc_ref = fake_db.db.collection('sources').document("src_50")

        _run_process_channel_videos(
            youtube_mock, source_doc_ref,
            exists_lesson_ids=set(),
            fake_db=fake_db
        )

        series_col = fake_db.db.collection('series')
        all_series = {
            doc_id: ref._data
            for doc_id, ref in series_col.doc_refs.items()
            if ref._data is not None
        }

        parasha_series = [s for s in all_series.values()
                          if s.get('serie') == playlist_title]
        self.assertTrue(len(parasha_series) >= 1,
                        f"Expected series doc for '{playlist_title}', got: {all_series}")
        self.assertEqual(parasha_series[0].get('sourceId'), SOURCE_ID,
                         "Series doc must have correct sourceId")

    # -----------------------------------------------------------------------
    # 10. Playlist map stored in source doc after refresh
    # -----------------------------------------------------------------------

    def test_playlist_map_stored_in_source_doc_after_refresh(self):
        """
        After a playlist scan, source doc must be updated with:
          - playlistMap: {videoId: seriesDocId, ...}
          - lastPlaylistScanAt: ISO timestamp string
        """
        video_id = "tracked_video"
        playlist_id = "PLfake_tracked"
        playlist_title = "שיעורים"

        youtube_mock = make_youtube_fake(
            playlists=[{'id': playlist_id, 'title': playlist_title}],
            playlist_items={
                UPLOADS_PLAYLIST_ID: [video_id],
                playlist_id: [video_id],
            },
            channel_uploads_id=UPLOADS_PLAYLIST_ID,
        )

        source_data = {
            'originalId': SOURCE_ID,
            'lessonIds': [],
            'channelId': CHANNEL_ID,
            # No playlistMap → first run → will refresh
        }
        fake_db = _make_fake_db(source_data=source_data)
        source_doc_ref = fake_db.db.collection('sources').document("src_50")

        _run_process_channel_videos(
            youtube_mock, source_doc_ref,
            exists_lesson_ids=set(),
            fake_db=fake_db
        )

        # Check source doc was updated
        source_after = source_doc_ref._data
        self.assertIn('playlistMap', source_after,
                      "Source doc must have 'playlistMap' after playlist scan")
        self.assertIn('lastPlaylistScanAt', source_after,
                      "Source doc must have 'lastPlaylistScanAt' after playlist scan")

        playlist_map = source_after['playlistMap']
        self.assertIsInstance(playlist_map, dict,
                              "playlistMap must be a dict")

        # video_id must be mapped to some series doc ID
        self.assertIn(video_id, playlist_map,
                      f"playlistMap must contain videoId '{video_id}'. Got: {playlist_map}")

        # lastPlaylistScanAt must be a valid recent ISO timestamp
        scan_at = source_after['lastPlaylistScanAt']
        self.assertIsInstance(scan_at, str, "lastPlaylistScanAt must be a string")
        # Should parse without error
        try:
            dt = datetime.fromisoformat(scan_at.replace('Z', '+00:00'))
        except ValueError:
            self.fail(f"lastPlaylistScanAt is not a valid ISO timestamp: {scan_at!r}")


if __name__ == '__main__':
    unittest.main()
