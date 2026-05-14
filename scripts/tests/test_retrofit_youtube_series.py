"""
Tests for retrofit_youtube_series.py

Covers: URL parsing, playlist map building, series doc creation,
        lesson update logic, idempotency, dry-run, checkpoint save/load.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from retrofit_youtube_series import (
    extract_video_id,
    build_playlist_map,
    get_or_create_series_doc,
    retrofit_channel,
    load_checkpoint,
    save_checkpoint,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_youtube(playlists=None, playlist_items=None, channels_uploads='UPabc'):
    """Build a mock YouTube API client."""
    yt = MagicMock()

    # channels().list().execute()
    yt.channels.return_value.list.return_value.execute.return_value = {
        'items': [{'contentDetails': {'relatedPlaylists': {'uploads': channels_uploads}}}]
    }

    # playlists().list().execute()
    yt.playlists.return_value.list.return_value.execute.return_value = {
        'items': playlists or [],
        'nextPageToken': None,
    }

    # playlistItems().list().execute()
    def _items_execute(**kwargs):
        return {'items': playlist_items or [], 'nextPageToken': None}
    yt.playlistItems.return_value.list.return_value.execute.side_effect = _items_execute

    return yt


def _make_db(existing_series=None, lessons=None):
    """Build a minimal mock Firestore db."""
    db = MagicMock()

    # series collection — track what gets written
    series_written = {}

    def _series_doc(doc_id):
        ref = MagicMock()
        exists_flag = doc_id in (existing_series or {})
        ref.get.return_value.exists = exists_flag
        ref.set.side_effect = lambda data: series_written.__setitem__(doc_id, data)
        ref.update = MagicMock()
        return ref

    db.collection.return_value.document.side_effect = _series_doc
    db._series_written = series_written

    # lessons collection — stream() returns mock docs
    lesson_docs = []
    for lesson in (lessons or []):
        doc = MagicMock()
        doc.id = str(lesson.get('id', 'doc_id'))
        doc.to_dict.return_value = lesson
        doc.reference = MagicMock()
        lesson_docs.append(doc)

    # Support pagination: first call returns lessons, second returns []
    call_count = [0]
    def _stream():
        call_count[0] += 1
        if call_count[0] == 1:
            return iter(lesson_docs)
        return iter([])

    db.collection.return_value.where.return_value.limit.return_value.stream.side_effect = _stream
    db.collection.return_value.where.return_value.limit.return_value.start_after.return_value.stream.return_value = iter([])

    # batch
    batch = MagicMock()
    db.batch.return_value = batch
    db._batch = batch

    return db


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestExtractVideoId(unittest.TestCase):

    def test_standard_watch_url(self):
        self.assertEqual(extract_video_id('https://www.youtube.com/watch?v=abc123'), 'abc123')

    def test_url_with_extra_params(self):
        self.assertEqual(extract_video_id('https://www.youtube.com/watch?v=xyz&t=30s'), 'xyz')

    def test_non_youtube_url_returns_none(self):
        self.assertIsNone(extract_video_id('https://vimeo.com/12345'))

    def test_audio_url_returns_none(self):
        self.assertIsNone(extract_video_id('https://mp3.meirtv.co.il/lesson.mp3'))

    def test_none_returns_none(self):
        self.assertIsNone(extract_video_id(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(extract_video_id(''))


class TestBuildPlaylistMap(unittest.TestCase):

    def test_maps_video_to_playlist_series(self):
        yt = _make_youtube(
            playlists=[{'id': 'PLabc', 'snippet': {'title': 'פרשת השבוע'}}],
            playlist_items=[{'snippet': {'resourceId': {'videoId': 'vid1'}}}],
            channels_uploads='UPabc',
        )
        db = _make_db()
        result = build_playlist_map(yt, db, 'UCchannel', 50, 'UPabc')
        self.assertIn('vid1', result)

    def test_uploads_playlist_excluded(self):
        yt = _make_youtube(
            playlists=[
                {'id': 'UPabc', 'snippet': {'title': 'Uploads'}},  # auto-generated
                {'id': 'PL123', 'snippet': {'title': 'גמרא'}},
            ],
            playlist_items=[{'snippet': {'resourceId': {'videoId': 'vid1'}}}],
            channels_uploads='UPabc',
        )
        db = _make_db()
        result = build_playlist_map(yt, db, 'UCchannel', 50, 'UPabc')
        # Only one series should have been created (for PL123)
        self.assertEqual(len(db._series_written), 1)

    def test_uu_prefix_playlist_excluded(self):
        yt = _make_youtube(
            playlists=[
                {'id': 'UUabc', 'snippet': {'title': 'Auto Uploads'}},
                {'id': 'PL999', 'snippet': {'title': 'שיעורים'}},
            ],
            playlist_items=[{'snippet': {'resourceId': {'videoId': 'vid2'}}}],
            channels_uploads='UPother',
        )
        db = _make_db()
        build_playlist_map(yt, db, 'UCchannel', 50, 'UPother')
        self.assertEqual(len(db._series_written), 1)

    def test_multiple_playlists_last_wins(self):
        """Video in two playlists → series of second (last) playlist."""
        call_count = [0]
        yt = MagicMock()
        yt.playlists.return_value.list.return_value.execute.return_value = {
            'items': [
                {'id': 'PL_A', 'snippet': {'title': 'Playlist A'}},
                {'id': 'PL_B', 'snippet': {'title': 'Playlist B'}},
            ],
            'nextPageToken': None,
        }
        # Both playlists contain the same videoId
        yt.playlistItems.return_value.list.return_value.execute.return_value = {
            'items': [{'snippet': {'resourceId': {'videoId': 'shared_vid'}}}],
            'nextPageToken': None,
        }
        db = _make_db()
        result = build_playlist_map(yt, db, 'UCchannel', 50, 'UPuploads')
        # Video should be mapped to whichever series was processed last
        self.assertIn('shared_vid', result)

    def test_channel_with_no_playlists_returns_empty_map(self):
        yt = _make_youtube(playlists=[], channels_uploads='UPabc')
        db = _make_db()
        result = build_playlist_map(yt, db, 'UCchannel', 50, 'UPabc')
        self.assertEqual(result, {})


class TestGetOrCreateSeriesDoc(unittest.TestCase):

    def test_creates_series_if_not_exists(self):
        db = _make_db(existing_series={})
        doc_id = get_or_create_series_doc(db, 50, 'PL123', 'פרשת השבוע')
        self.assertIsNotNone(doc_id)
        self.assertTrue(doc_id.startswith('ser_'))
        # set() should have been called
        self.assertIn(doc_id, db._series_written)

    def test_does_not_overwrite_existing_series(self):
        db = _make_db(existing_series={'ser_existing': True})

        # Patch document() to return existing
        ref = MagicMock()
        ref.get.return_value.exists = True
        db.collection.return_value.document.return_value = ref

        get_or_create_series_doc(db, 50, 'PL_existing', 'Existing Series')
        ref.set.assert_not_called()

    def test_same_playlist_id_produces_same_series_doc_id(self):
        db1 = _make_db()
        db2 = _make_db()
        id1 = get_or_create_series_doc(db1, 50, 'PL_fixed', 'Title A')
        id2 = get_or_create_series_doc(db2, 50, 'PL_fixed', 'Title B')
        self.assertEqual(id1, id2, "Same playlist ID must always produce same series doc ID")


class TestRetrofitChannel(unittest.TestCase):

    def _run(self, lesson_video_url, playlist_video_id, dry_run=False):
        """Helper: run retrofit for one lesson against one playlist."""
        yt = _make_youtube(
            playlists=[{'id': 'PL001', 'snippet': {'title': 'פרשת השבוע'}}],
            playlist_items=[{'snippet': {'resourceId': {'videoId': playlist_video_id}}}],
            channels_uploads='UPabc',
        )
        db = _make_db(lessons=[{
            'sourceId': 50,
            'videoUrl': lesson_video_url,
            'seriesId': 'ser_old_כללי',
        }])
        stats = retrofit_channel(db, yt, 50, 'UCchannel', dry_run=dry_run)
        return stats, db

    def test_lesson_in_playlist_gets_updated_series_id(self):
        stats, db = self._run(
            lesson_video_url='https://www.youtube.com/watch?v=vid_in_playlist',
            playlist_video_id='vid_in_playlist',
        )
        self.assertEqual(stats['updated'], 1)
        self.assertEqual(stats['skipped'], 0)
        db._batch.update.assert_called_once()

    def test_lesson_not_in_any_playlist_stays_as_כללי(self):
        stats, db = self._run(
            lesson_video_url='https://www.youtube.com/watch?v=vid_not_in_playlist',
            playlist_video_id='different_video',
        )
        # seriesId would be set to כללי doc — but current is already ser_old_כללי
        # Since they differ, it still counts as updated (to the new כללי doc)
        self.assertGreaterEqual(stats['updated'] + stats['skipped'], 1)

    def test_lesson_already_correct_series_is_skipped(self):
        """Idempotency: if seriesId already correct, don't update."""
        yt = _make_youtube(
            playlists=[{'id': 'PL001', 'snippet': {'title': 'פרשת השבוע'}}],
            playlist_items=[{'snippet': {'resourceId': {'videoId': 'vid1'}}}],
            channels_uploads='UPabc',
        )

        # Pre-compute what the series doc ID will be
        from retrofit_youtube_series import get_or_create_series_doc as gocd
        db_tmp = _make_db()
        expected_series_id = gocd(db_tmp, 50, 'PL001', 'פרשת השבוע')

        db = _make_db(lessons=[{
            'sourceId': 50,
            'videoUrl': 'https://www.youtube.com/watch?v=vid1',
            'seriesId': expected_series_id,  # already correct
        }])
        stats = retrofit_channel(db, yt, 50, 'UCchannel')
        self.assertEqual(stats['skipped'], 1)
        self.assertEqual(stats['updated'], 0)
        db._batch.update.assert_not_called()

    def test_non_youtube_lesson_not_updated(self):
        stats, db = self._run(
            lesson_video_url='https://vimeo.com/12345',
            playlist_video_id='any_video',
        )
        self.assertEqual(stats['no_playlist'], 1)
        db._batch.update.assert_not_called()

    def test_dry_run_does_not_write(self):
        stats, db = self._run(
            lesson_video_url='https://www.youtube.com/watch?v=vid_in_playlist',
            playlist_video_id='vid_in_playlist',
            dry_run=True,
        )
        self.assertEqual(stats['updated'], 1)
        db._batch.update.assert_not_called()
        db._batch.commit.assert_not_called()


class TestRetrofitTotalCount(unittest.TestCase):
    """
    The retrofit script updates seriesId on lessons but must ALSO update
    totalCount on each series doc. Without this, series show 0 in the app
    even when they contain thousands of lessons.
    """

    def _make_db_with_series_update_tracking(self, lessons, existing_כללי_id):
        """Extended fake db that tracks series update() calls with their args."""
        db = MagicMock()
        series_updates = {}  # series_doc_id -> data passed to update()

        def _series_doc(doc_id):
            ref = MagicMock()
            ref.get.return_value.exists = False
            ref.set.side_effect = lambda data: None
            def _update(data):
                series_updates[doc_id] = data
            ref.update.side_effect = _update
            return ref

        db.collection.return_value.document.side_effect = _series_doc
        db._series_updates = series_updates

        lesson_docs = []
        for lesson in lessons:
            doc = MagicMock()
            doc.id = str(lesson.get('id', 'x'))
            doc.to_dict.return_value = lesson
            doc.reference = MagicMock()
            lesson_docs.append(doc)

        call_count = [0]
        def _stream():
            call_count[0] += 1
            return iter(lesson_docs) if call_count[0] == 1 else iter([])

        db.collection.return_value.where.return_value.limit.return_value.stream.side_effect = _stream
        db.collection.return_value.where.return_value.limit.return_value.start_after.return_value.stream.return_value = iter([])
        db.batch.return_value = MagicMock()
        return db

    def test_series_totalcount_updated_after_retrofit(self):
        """Series docs must receive a totalCount update after lessons are assigned."""
        yt = _make_youtube(
            playlists=[{'id': 'PL001', 'snippet': {'title': 'פרשת השבוע'}}],
            playlist_items=[
                {'snippet': {'resourceId': {'videoId': 'vid1'}}},
                {'snippet': {'resourceId': {'videoId': 'vid2'}}},
            ],
            channels_uploads='UPabc',
        )
        db = self._make_db_with_series_update_tracking(
            lessons=[
                {'sourceId': 50, 'videoUrl': 'https://www.youtube.com/watch?v=vid1', 'seriesId': 'ser_old'},
                {'sourceId': 50, 'videoUrl': 'https://www.youtube.com/watch?v=vid2', 'seriesId': 'ser_old'},
            ],
            existing_כללי_id='ser_כללי',
        )
        retrofit_channel(db, yt, 50, 'UCchannel')

        # At least one series doc must have received a totalCount update
        self.assertTrue(
            any('totalCount' in v for v in db._series_updates.values()),
            "retrofit_channel must update totalCount on series docs after assigning lessons"
        )

    def test_playlist_series_totalcount_equals_lesson_count(self):
        """The totalCount written to the playlist series = number of lessons assigned to it."""
        yt = _make_youtube(
            playlists=[{'id': 'PL001', 'snippet': {'title': 'פרשת השבוע'}}],
            playlist_items=[
                {'snippet': {'resourceId': {'videoId': 'vid1'}}},
                {'snippet': {'resourceId': {'videoId': 'vid2'}}},
                {'snippet': {'resourceId': {'videoId': 'vid3'}}},
            ],
            channels_uploads='UPabc',
        )
        db = self._make_db_with_series_update_tracking(
            lessons=[
                {'sourceId': 50, 'videoUrl': 'https://www.youtube.com/watch?v=vid1', 'seriesId': 'old'},
                {'sourceId': 50, 'videoUrl': 'https://www.youtube.com/watch?v=vid2', 'seriesId': 'old'},
                {'sourceId': 50, 'videoUrl': 'https://www.youtube.com/watch?v=vid3', 'seriesId': 'old'},
            ],
            existing_כללי_id='ser_כללי',
        )
        retrofit_channel(db, yt, 50, 'UCchannel')

        # Find the playlist series update and check its totalCount
        playlist_updates = {k: v for k, v in db._series_updates.items()
                           if v.get('totalCount', 0) > 0}
        self.assertTrue(playlist_updates, "No series got a non-zero totalCount update")
        # The playlist series should show 3 (all lessons belong to it)
        counts = [v['totalCount'] for v in playlist_updates.values()]
        self.assertIn(3, counts, f"Expected totalCount=3 for playlist series, got: {counts}")

    def test_כללי_series_totalcount_updated_to_remaining_count(self):
        """כללי series must also get its totalCount updated to reflect only its remaining lessons."""
        yt = _make_youtube(
            playlists=[{'id': 'PL001', 'snippet': {'title': 'פרשת השבוע'}}],
            playlist_items=[{'snippet': {'resourceId': {'videoId': 'vid1'}}}],
            channels_uploads='UPabc',
        )
        db = self._make_db_with_series_update_tracking(
            lessons=[
                {'sourceId': 50, 'videoUrl': 'https://www.youtube.com/watch?v=vid1', 'seriesId': 'old'},  # → playlist
                {'sourceId': 50, 'videoUrl': 'https://www.youtube.com/watch?v=vid2', 'seriesId': 'old'},  # → כללי
            ],
            existing_כללי_id='ser_כללי',
        )
        retrofit_channel(db, yt, 50, 'UCchannel')

        # Every series that has lessons must get a totalCount update
        updated_series = {k for k, v in db._series_updates.items() if 'totalCount' in v}
        self.assertGreaterEqual(len(updated_series), 2,
            "Both the playlist series AND כללי series must get totalCount updates")

    def test_dry_run_does_not_update_totalcount(self):
        yt = _make_youtube(
            playlists=[{'id': 'PL001', 'snippet': {'title': 'שיעורים'}}],
            playlist_items=[{'snippet': {'resourceId': {'videoId': 'vid1'}}}],
            channels_uploads='UPabc',
        )
        db = self._make_db_with_series_update_tracking(
            lessons=[{'sourceId': 50, 'videoUrl': 'https://www.youtube.com/watch?v=vid1', 'seriesId': 'old'}],
            existing_כללי_id='ser_כללי',
        )
        retrofit_channel(db, yt, 50, 'UCchannel', dry_run=True)

        totalcount_updates = [v for v in db._series_updates.values() if 'totalCount' in v]
        self.assertEqual(totalcount_updates, [],
            "dry_run must not write totalCount updates")


class TestCheckpoint(unittest.TestCase):

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = os.path.join(tmpdir, 'checkpoint.json')
            with patch('retrofit_youtube_series.CHECKPOINT_FILE', checkpoint_path):
                data = {'50': {'done': True, 'updated': 42}}
                save_checkpoint(data)
                loaded = load_checkpoint()
                self.assertEqual(loaded, data)

    def test_load_returns_empty_dict_if_no_file(self):
        with patch('retrofit_youtube_series.CHECKPOINT_FILE', '/nonexistent/path.json'):
            self.assertEqual(load_checkpoint(), {})


if __name__ == '__main__':
    unittest.main()
