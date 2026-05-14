"""
Tests for cleanup_duplicate_youtube_lessons.py
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from cleanup_duplicate_youtube_lessons import (
    is_old_format,
    find_new_doc_for_url,
    cleanup_source,
)

VIDEO_URL = 'https://www.youtube.com/watch?v=abc123'
SOURCE_ID = 63


def _make_doc(doc_id, data):
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = data
    doc.reference = MagicMock()
    return doc


def _make_db(lessons):
    """
    lessons: list of dicts with keys: doc_id, sourceId, videoUrl, createdAt (optional)
    """
    db = MagicMock()
    docs = [_make_doc(l['doc_id'], {k: v for k, v in l.items() if k != 'doc_id'})
            for l in lessons]

    # Support pagination: first call returns docs, second returns []
    call_count = [0]
    def _stream():
        call_count[0] += 1
        return iter(docs) if call_count[0] == 1 else iter([])

    db.collection.return_value.where.return_value.where.return_value.stream.return_value = iter(docs)
    db.collection.return_value.where.return_value.limit.return_value.stream.side_effect = _stream
    db.collection.return_value.where.return_value.limit.return_value.start_after.return_value.stream.return_value = iter([])

    batch = MagicMock()
    db.batch.return_value = batch
    db._batch = batch
    db._lessons = docs
    return db


class TestIsOldFormat(unittest.TestCase):

    def test_no_created_at_is_old(self):
        self.assertTrue(is_old_format({'sourceId': 63, 'videoUrl': VIDEO_URL}))

    def test_none_created_at_is_old(self):
        self.assertTrue(is_old_format({'createdAt': None}))

    def test_empty_created_at_is_old(self):
        self.assertTrue(is_old_format({'createdAt': ''}))

    def test_has_created_at_is_new(self):
        self.assertFalse(is_old_format({'createdAt': '2026-05-13T13:34:20'}))


class TestFindNewDocForUrl(unittest.TestCase):

    def test_finds_new_doc_with_same_url(self):
        old_id = 'old_doc_id'
        new_doc = _make_doc('new_doc_id', {
            'sourceId': SOURCE_ID,
            'videoUrl': VIDEO_URL,
            'createdAt': '2026-05-13T13:34:20',
        })
        db = MagicMock()
        db.collection.return_value.where.return_value.where.return_value.stream.return_value = iter([new_doc])
        self.assertTrue(find_new_doc_for_url(db, SOURCE_ID, VIDEO_URL, old_id))

    def test_returns_false_when_only_old_doc_exists(self):
        old_id = 'old_doc_id'
        old_doc = _make_doc(old_id, {'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL})
        db = MagicMock()
        db.collection.return_value.where.return_value.where.return_value.stream.return_value = iter([old_doc])
        self.assertFalse(find_new_doc_for_url(db, SOURCE_ID, VIDEO_URL, old_id))

    def test_ignores_the_old_doc_itself(self):
        """The old doc matches the videoUrl query — must be excluded from the check."""
        old_id = 'old_doc_id'
        old_doc = _make_doc(old_id, {
            'sourceId': SOURCE_ID,
            'videoUrl': VIDEO_URL,
            'createdAt': '2026-05-13',  # even with createdAt, same id should be skipped
        })
        db = MagicMock()
        db.collection.return_value.where.return_value.where.return_value.stream.return_value = iter([old_doc])
        self.assertFalse(find_new_doc_for_url(db, SOURCE_ID, VIDEO_URL, old_id))

    def test_returns_false_when_no_docs(self):
        db = MagicMock()
        db.collection.return_value.where.return_value.where.return_value.stream.return_value = iter([])
        self.assertFalse(find_new_doc_for_url(db, SOURCE_ID, VIDEO_URL, 'old_id'))


class TestCleanupSource(unittest.TestCase):

    def _make_paired_db(self, old_id, new_id, url=VIDEO_URL):
        """DB with one old doc and one new doc for the same video."""
        lessons = [
            {'doc_id': old_id, 'sourceId': SOURCE_ID, 'videoUrl': url},  # old, no createdAt
            {'doc_id': new_id, 'sourceId': SOURCE_ID, 'videoUrl': url, 'createdAt': '2026-05-13'},
        ]
        return _make_db(lessons)

    def test_deletes_old_doc_when_new_exists(self):
        db = self._make_paired_db('old_148609', 'new_100584')
        stats = cleanup_source(db, SOURCE_ID, dry_run=False)
        self.assertEqual(stats['deleted'], 1)
        self.assertEqual(stats['kept_no_new_doc'], 0)
        db._batch.delete.assert_called_once()

    def test_keeps_old_doc_when_no_new_exists(self):
        """If a video exists ONLY in old format, keep it — it's the only copy."""
        lessons = [
            {'doc_id': 'old_only', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL},
        ]
        db = _make_db(lessons)
        # find_new_doc_for_url returns empty
        db.collection.return_value.where.return_value.where.return_value.stream.return_value = iter([
            _make_doc('old_only', {'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL})
        ])
        stats = cleanup_source(db, SOURCE_ID, dry_run=False)
        self.assertEqual(stats['deleted'], 0)
        self.assertEqual(stats['kept_no_new_doc'], 1)
        db._batch.delete.assert_not_called()

    def test_skips_new_format_docs(self):
        """New docs (with createdAt) must never be deleted."""
        lessons = [
            {'doc_id': 'new_doc', 'sourceId': SOURCE_ID,
             'videoUrl': VIDEO_URL, 'createdAt': '2026-05-13'},
        ]
        db = _make_db(lessons)
        stats = cleanup_source(db, SOURCE_ID, dry_run=False)
        self.assertEqual(stats['deleted'], 0)
        self.assertEqual(stats['skipped_new_format'], 1)
        db._batch.delete.assert_not_called()

    def test_skips_non_youtube_old_docs(self):
        """Old docs with non-YouTube URLs must not be deleted."""
        lessons = [
            {'doc_id': 'old_vimeo', 'sourceId': SOURCE_ID,
             'videoUrl': 'https://vimeo.com/12345'},
        ]
        db = _make_db(lessons)
        stats = cleanup_source(db, SOURCE_ID, dry_run=False)
        self.assertEqual(stats['deleted'], 0)

    def test_dry_run_does_not_delete(self):
        db = self._make_paired_db('old_doc', 'new_doc')
        stats = cleanup_source(db, SOURCE_ID, dry_run=True)
        self.assertEqual(stats['deleted'], 1)  # counted but not written
        db._batch.delete.assert_not_called()
        db._batch.commit.assert_not_called()

    def test_multiple_old_docs_all_deleted(self):
        """Two old docs for two different videos, both with new counterparts."""
        url_a = 'https://www.youtube.com/watch?v=aaa'
        url_b = 'https://www.youtube.com/watch?v=bbb'
        lessons = [
            {'doc_id': 'old_a', 'sourceId': SOURCE_ID, 'videoUrl': url_a},
            {'doc_id': 'new_a', 'sourceId': SOURCE_ID, 'videoUrl': url_a, 'createdAt': '2026-05-13'},
            {'doc_id': 'old_b', 'sourceId': SOURCE_ID, 'videoUrl': url_b},
            {'doc_id': 'new_b', 'sourceId': SOURCE_ID, 'videoUrl': url_b, 'createdAt': '2026-05-13'},
        ]
        db = _make_db(lessons)
        # Patch find_new_doc_for_url to always confirm new doc exists
        with patch('cleanup_duplicate_youtube_lessons.find_new_doc_for_url', return_value=True):
            stats = cleanup_source(db, SOURCE_ID, dry_run=False)
        self.assertEqual(stats['deleted'], 2)
        self.assertEqual(db._batch.delete.call_count, 2)

    def test_only_youtube_source_ids_accepted(self):
        """Source IDs outside the YouTube range should not be processed."""
        from cleanup_duplicate_youtube_lessons import YOUTUBE_SOURCE_IDS
        non_youtube = 1  # Bnei David — not a YouTube-only source
        self.assertNotIn(non_youtube, YOUTUBE_SOURCE_IDS,
            "Source 1 (Bnei David) must not be in YOUTUBE_SOURCE_IDS — "
            "it has legitimate old-format docs from the site scraper")


if __name__ == '__main__':
    unittest.main()
