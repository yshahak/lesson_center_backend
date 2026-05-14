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
    canonical_doc_id,
    get_authoritative_lesson_ids,
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


class TestCanonicalDocId(unittest.TestCase):

    def test_returns_string(self):
        result = canonical_doc_id(50, 'https://www.youtube.com/watch?v=abc123')
        self.assertIsInstance(result, str)

    def test_deterministic(self):
        id1 = canonical_doc_id(50, 'https://www.youtube.com/watch?v=abc123')
        id2 = canonical_doc_id(50, 'https://www.youtube.com/watch?v=abc123')
        self.assertEqual(id1, id2)

    def test_different_video_different_id(self):
        self.assertNotEqual(
            canonical_doc_id(50, 'https://www.youtube.com/watch?v=aaa'),
            canonical_doc_id(50, 'https://www.youtube.com/watch?v=bbb'),
        )

    def test_different_source_different_id(self):
        self.assertNotEqual(
            canonical_doc_id(50, VIDEO_URL),
            canonical_doc_id(63, VIDEO_URL),
        )

    def test_non_youtube_url_returns_none(self):
        self.assertIsNone(canonical_doc_id(50, 'https://vimeo.com/12345'))

    def test_url_without_v_param_returns_none(self):
        self.assertIsNone(canonical_doc_id(50, 'https://www.youtube.com/'))


class TestFindNewDocForUrl(unittest.TestCase):

    def test_returns_true_when_canonical_doc_exists(self):
        """find_new_doc_for_url checks if the canonical doc exists in Firestore."""
        canon_id = canonical_doc_id(SOURCE_ID, VIDEO_URL)
        old_id = 'some_old_non_canonical_id'
        canon_doc = MagicMock()
        canon_doc.exists = True
        db = MagicMock()
        db.collection.return_value.document.return_value.get.return_value = canon_doc
        self.assertTrue(find_new_doc_for_url(db, SOURCE_ID, VIDEO_URL, old_id))

    def test_returns_false_when_canonical_doc_missing(self):
        canon_doc = MagicMock()
        canon_doc.exists = False
        db = MagicMock()
        db.collection.return_value.document.return_value.get.return_value = canon_doc
        self.assertFalse(find_new_doc_for_url(db, SOURCE_ID, VIDEO_URL, 'old_id'))

    def test_returns_false_when_old_id_is_canonical(self):
        """If the old doc IS the canonical doc, no counterpart to delete."""
        canon_id = canonical_doc_id(SOURCE_ID, VIDEO_URL)
        db = MagicMock()
        self.assertFalse(find_new_doc_for_url(db, SOURCE_ID, VIDEO_URL, canon_id))

    def test_returns_false_for_non_youtube_url(self):
        db = MagicMock()
        self.assertFalse(find_new_doc_for_url(db, SOURCE_ID, 'https://vimeo.com/1', 'x'))


class TestCleanupSource(unittest.TestCase):
    """
    cleanup_source patches canonical_doc_id to control which doc is "canonical"
    and find_new_doc_for_url to control whether the canonical doc exists.
    """

    def _run(self, lessons, canonical_id='canonical_doc', find_new_result=True, dry_run=False):
        db = _make_db(lessons)
        with patch('cleanup_duplicate_youtube_lessons.canonical_doc_id', return_value=canonical_id), \
             patch('cleanup_duplicate_youtube_lessons.find_new_doc_for_url', return_value=find_new_result):
            stats = cleanup_source(db, SOURCE_ID, dry_run=dry_run)
        return stats, db

    def test_deletes_stale_doc_when_canonical_exists(self):
        """Non-canonical doc with canonical counterpart → deleted."""
        stats, db = self._run(
            lessons=[
                {'doc_id': 'stale_old', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL},
                {'doc_id': 'canonical_doc', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL, 'createdAt': '2026-05-13'},
            ],
            canonical_id='canonical_doc',
            find_new_result=True,
        )
        self.assertEqual(stats['deleted'], 1)
        self.assertEqual(stats['kept_no_new_doc'], 0)
        db._batch.delete.assert_called_once()

    def test_keeps_stale_doc_when_canonical_missing(self):
        """Non-canonical doc with no canonical counterpart → kept (only copy)."""
        stats, db = self._run(
            lessons=[{'doc_id': 'stale_only', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL}],
            canonical_id='canonical_doc',  # different from stale_only
            find_new_result=False,  # canonical doesn't exist
        )
        self.assertEqual(stats['deleted'], 0)
        self.assertEqual(stats['kept_no_new_doc'], 1)
        db._batch.delete.assert_not_called()

    def test_skips_canonical_doc(self):
        """The canonical doc itself must never be deleted."""
        stats, db = self._run(
            lessons=[{'doc_id': 'canonical_doc', 'sourceId': SOURCE_ID,
                      'videoUrl': VIDEO_URL, 'createdAt': '2026-05-13'}],
            canonical_id='canonical_doc',
        )
        self.assertEqual(stats['deleted'], 0)
        self.assertEqual(stats['skipped_authoritative'], 1)
        db._batch.delete.assert_not_called()

    def test_skips_non_youtube_docs(self):
        stats, db = self._run(
            lessons=[{'doc_id': 'vimeo_doc', 'sourceId': SOURCE_ID,
                      'videoUrl': 'https://vimeo.com/12345'}],
        )
        self.assertEqual(stats['deleted'], 0)

    def test_dry_run_does_not_delete(self):
        stats, db = self._run(
            lessons=[
                {'doc_id': 'stale_doc', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL},
                {'doc_id': 'canonical_doc', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL, 'createdAt': '2026-05-13'},
            ],
            find_new_result=True,
            dry_run=True,
        )
        self.assertEqual(stats['deleted'], 1)
        db._batch.delete.assert_not_called()
        db._batch.commit.assert_not_called()

    def test_multiple_stale_docs_all_deleted(self):
        """Migration doc AND old scraper doc both deleted when canonical exists."""
        stats, db = self._run(
            lessons=[
                {'doc_id': 'migration_doc', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL},
                {'doc_id': 'aug2024_doc', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL, 'createdAt': '2024-08-09'},
                {'doc_id': 'canonical_doc', 'sourceId': SOURCE_ID, 'videoUrl': VIDEO_URL, 'createdAt': '2026-05-13'},
            ],
            canonical_id='canonical_doc',
            find_new_result=True,
        )
        self.assertEqual(stats['deleted'], 2)
        self.assertEqual(stats['skipped_authoritative'], 1)
        self.assertEqual(db._batch.delete.call_count, 2)

    def test_only_youtube_source_ids_accepted(self):
        from cleanup_duplicate_youtube_lessons import YOUTUBE_SOURCE_IDS
        non_youtube = 1
        self.assertNotIn(non_youtube, YOUTUBE_SOURCE_IDS,
            "Source 1 (Bnei David) must not be in YOUTUBE_SOURCE_IDS")


if __name__ == '__main__':
    unittest.main()
