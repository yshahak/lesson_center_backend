"""
Data integrity test: no two lessons in the same source should have the same videoUrl.

This is the test that would have caught the May 13 2026 duplicate bug, where the
Cloud Function scraper created new docs for every YouTube video because the source
docs had empty 'lessonIds' after migration (ID-scheme mismatch between PostgreSQL
bigint IDs and scraper hash IDs).

Run against real Firestore:
    cd lesson_center_backend
    python -m pytest scripts/tests/test_no_duplicate_lessons.py -v
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'functions'))

try:
    import firebase_admin
    from firebase_admin import firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False

YOUTUBE_SOURCE_IDS = [50, 51, 52, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74]
# Acceptable duplicate threshold — 0 means zero tolerance
DUPLICATE_TOLERANCE = 0


def get_db():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={'projectId': 'tora-or'})
    return firestore.client()


@unittest.skipUnless(FIREBASE_AVAILABLE, "firebase_admin not installed")
class TestNoDuplicateLessons(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = get_db()

    def _check_source_for_duplicates(self, source_id):
        """
        Returns list of videoUrls that appear more than once for this source.
        Fetches in pages of 500 to handle large sources.
        """
        url_counts = {}
        last_doc = None

        while True:
            query = self.db.collection('lessons') \
                .where('sourceId', '==', source_id) \
                .limit(500)
            if last_doc:
                query = query.start_after(last_doc)

            docs = list(query.stream())
            if not docs:
                break

            for doc in docs:
                url = doc.to_dict().get('videoUrl', '')
                if url and 'youtube.com' in url:
                    url_counts[url] = url_counts.get(url, 0) + 1

            last_doc = docs[-1]
            if len(docs) < 500:
                break

        return [url for url, count in url_counts.items() if count > DUPLICATE_TOLERANCE + 1]

    def test_no_duplicate_youtube_urls_source_50(self):
        dupes = self._check_source_for_duplicates(50)
        self.assertEqual(dupes, [],
            f"Source 50 has {len(dupes)} duplicate videoUrls. "
            f"First few: {dupes[:3]}. "
            f"Run cleanup_duplicate_youtube_lessons.py to fix.")

    def test_no_duplicate_youtube_urls_source_52(self):
        dupes = self._check_source_for_duplicates(52)
        self.assertEqual(dupes, [], f"Source 52 has {len(dupes)} duplicate videoUrls")

    def test_no_duplicate_youtube_urls_source_63(self):
        """Source 63 (הר עציון) is the largest channel — most likely to show duplicates."""
        dupes = self._check_source_for_duplicates(63)
        self.assertEqual(dupes, [],
            f"Source 63 has {len(dupes)} duplicate videoUrls — "
            f"likely ID-scheme mismatch between migration and scraper. "
            f"First few: {dupes[:3]}")

    def test_no_duplicate_youtube_urls_all_sources(self):
        """
        Full sweep across all 18 YouTube sources.
        Slower but catches any source missed by individual tests.
        """
        all_dupes = {}
        for source_id in YOUTUBE_SOURCE_IDS:
            dupes = self._check_source_for_duplicates(source_id)
            if dupes:
                all_dupes[source_id] = dupes

        self.assertEqual(all_dupes, {},
            f"Duplicate videoUrls found in sources: "
            f"{', '.join(f'{sid}: {len(d)} dupes' for sid, d in all_dupes.items())}. "
            f"Run cleanup_duplicate_youtube_lessons.py to fix.")


if __name__ == '__main__':
    unittest.main()
