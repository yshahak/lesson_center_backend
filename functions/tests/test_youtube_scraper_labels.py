"""
Tests for youtube_scraper label writing.

Critical invariant: labels must be written with `lessonIds` (plural, list of strings)
matching the Flutter app schema. A singular `lessonId` field is the wrong schema and
will cause the ראשי tab to show 0 entries in the app.
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class FakeDoc:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


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
    def __init__(self):
        self.set_calls = []
        self.delete_calls = []

    def set(self, data):
        self.set_calls.append(data)

    def delete(self):
        self.delete_calls.append(True)


class FakeCollection:
    def __init__(self, docs=None):
        self._docs = docs or []
        self.doc_refs = {}

    def where(self, *args, **kwargs):
        return FakeQuery(self._docs)

    def document(self, doc_id=None):
        if doc_id not in self.doc_refs:
            self.doc_refs[doc_id] = FakeDocRef()
        return self.doc_refs[doc_id]


class FakeDB:
    def __init__(self, lesson_docs=None):
        self._lessons = FakeCollection(lesson_docs or [])
        self._labels = FakeCollection()
        self.batch_obj = MagicMock()

    def collection(self, name):
        if 'lessons' in name:
            return self._lessons
        if 'labels' in name:
            return self._labels
        return FakeCollection()

    def batch(self):
        return self.batch_obj


class FakeFirestoreDB:
    def __init__(self, lesson_docs=None):
        self.db = FakeDB(lesson_docs)
        self.collection_prefix = ""


import scrapers.youtube_scraper as scraper_module


class TestAddLabelsForRecentLessons(unittest.TestCase):

    def _setup_scraper(self, lesson_ids):
        """Seed fake Firestore with lessons and point the scraper at it."""
        lesson_docs = [FakeDoc({'id': lid, 'sourceId': 1}) for lid in lesson_ids]
        fake_db = FakeFirestoreDB(lesson_docs)
        scraper_module.firestore_db = fake_db
        return fake_db

    def test_writes_lessonIds_plural_array_not_singular(self):
        """label doc must have 'lessonIds' (list), NOT 'lessonId' (single int)."""
        fake_db = self._setup_scraper([101, 102, 103])
        scraper_module.add_labels_for_recent_lessons(50, 'cat_abc', 'הסדר חיפה - אחרונים')

        doc_ref = fake_db.db._labels.doc_refs.get('label_50')
        self.assertIsNotNone(doc_ref, "Expected label doc 'label_50' to be written")
        self.assertEqual(len(doc_ref.set_calls), 1)

        written = doc_ref.set_calls[0]
        self.assertIn('lessonIds', written, "Must write 'lessonIds' (plural array)")
        self.assertNotIn('lessonId', written, "Must NOT write 'lessonId' (singular) — Flutter app won't read it")

    def test_lessonIds_is_list_of_strings(self):
        """Flutter app reads lessonIds as List<String> — must be strings, not ints."""
        fake_db = self._setup_scraper([101, 102])
        scraper_module.add_labels_for_recent_lessons(50, 'cat_abc', 'test label')

        written = fake_db.db._labels.doc_refs['label_50'].set_calls[0]
        lesson_ids = written['lessonIds']

        self.assertIsInstance(lesson_ids, list)
        for lid in lesson_ids:
            self.assertIsInstance(lid, str,
                msg=f"lessonId {lid!r} must be str, got {type(lid).__name__} — Flutter casts to String")

    def test_writes_correct_label_name_and_source_id(self):
        fake_db = self._setup_scraper([101])
        scraper_module.add_labels_for_recent_lessons(63, 'cat_xyz', 'ישיבת הר עציון - אחרונים')

        written = fake_db.db._labels.doc_refs['label_63'].set_calls[0]
        self.assertEqual(written['label'], 'ישיבת הר עציון - אחרונים')
        self.assertEqual(written['sourceId'], 63)

    def test_writes_up_to_10_lesson_ids(self):
        fake_db = self._setup_scraper(list(range(1, 15)))  # 14 lessons
        scraper_module.add_labels_for_recent_lessons(50, 'cat_abc', 'test')

        written = fake_db.db._labels.doc_refs['label_50'].set_calls[0]
        # The query uses limit(10) so at most 10 IDs
        self.assertLessEqual(len(written['lessonIds']), 10)

    def test_no_write_when_no_lessons_found(self):
        fake_db = self._setup_scraper([])  # no lessons
        scraper_module.add_labels_for_recent_lessons(50, 'cat_abc', 'test')

        self.assertNotIn('label_50', fake_db.db._labels.doc_refs,
            "Should not write label doc when no lessons found")

    def test_clear_labels_deletes_deterministic_doc(self):
        """clear_labels_for_source must delete label_{source_id}, not query by sourceId."""
        fake_db = FakeFirestoreDB()
        scraper_module.firestore_db = fake_db

        scraper_module.clear_labels_for_source(63)

        doc_ref = fake_db.db._labels.doc_refs.get('label_63')
        self.assertIsNotNone(doc_ref)
        self.assertEqual(len(doc_ref.delete_calls), 1,
            "clear_labels_for_source must call delete() on label_63")


if __name__ == '__main__':
    unittest.main()
