#!/usr/bin/env python3
"""
Remove duplicate YouTube lessons created by ID-scheme mismatches.

Background:
  Multiple historical scraper/migration runs created multiple Firestore docs for the
  same YouTube video under different doc ID schemes:
  - PostgreSQL migration: doc_id = pg_lessons.id (bigint)
  - Aug 2024 scraper: doc_id = get_hash_for_id(source_id, get_hash_for_string(video_id))
  - May 2026 scraper: same hash function, same IDs as Aug 2024 (overwrites correctly)

  BUT the migration and Aug 2024 scraper used DIFFERENT source_id values for some
  channels, producing different hash outputs → multiple docs per video.

The only authoritative doc for each video is the one whose doc ID equals
get_hash_for_id(source_id, get_hash_for_string(video_id)) — the deterministic
hash the current scraper uses. Any doc with a different ID for the same videoUrl
is a stale duplicate and can be safely deleted.

Safety: never delete a doc unless a correctly-hashed doc exists for the same video.

Usage:
    cd lesson_center_backend
    python scripts/cleanup_duplicate_youtube_lessons.py --dry-run   # preview first
    python scripts/cleanup_duplicate_youtube_lessons.py             # then real run
    python scripts/cleanup_duplicate_youtube_lessons.py --source 63 # single channel
"""

import argparse
import logging
import os
import sys
from urllib.parse import urlparse, parse_qs
from datetime import datetime

import firebase_admin
from firebase_admin import firestore

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))
from utils.firestore_helper import get_hash_for_id, get_hash_for_string

YOUTUBE_SOURCE_IDS = [50, 51, 52, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74]
BATCH_SIZE = 400


def canonical_doc_id(source_id: int, video_url: str) -> str:
    """
    Compute the canonical Firestore doc ID for a YouTube lesson.
    This is the deterministic hash the current scraper uses.
    Any doc with a different ID for the same videoUrl is a stale duplicate.
    """
    params = parse_qs(urlparse(video_url).query)
    ids = params.get('v', [])
    if not ids:
        return None
    video_id = ids[0]
    original_video_id = get_hash_for_string(video_id)
    lesson_id = get_hash_for_id(source_id, original_video_id)
    return str(lesson_id)


def is_old_format(data: dict) -> bool:
    """Migration-era doc: no createdAt field."""
    return not data.get('createdAt')


def find_new_doc_for_url(db, source_id: int, video_url: str, old_doc_id: str) -> bool:
    """Return True if the canonical doc exists for this videoUrl (different from old_doc_id)."""
    canon_id = canonical_doc_id(source_id, video_url)
    if not canon_id or canon_id == old_doc_id:
        return False
    # Check if canonical doc actually exists in Firestore
    doc = db.collection('lessons').document(canon_id).get()
    return doc.exists


def get_authoritative_lesson_ids(db, source_id: int) -> set:
    """Kept for backwards compatibility with tests."""
    source_query = db.collection('sources').where('originalId', '==', source_id).limit(1).get()
    if not source_query:
        return set()
    return set(str(lid) for lid in source_query[0].to_dict().get('lessonIds', []))


def cleanup_source(db, source_id: int, dry_run: bool = False):
    """
    Delete stale duplicate docs for one YouTube source.

    For each lesson, compute the canonical doc ID from the videoUrl hash.
    - If this doc's ID == canonical ID → it's the correct doc, keep it.
    - If this doc's ID != canonical ID → it's a stale duplicate.
      Only delete if the canonical doc actually exists (safety check).
    """
    logger.info(f"🔍 Scanning source {source_id} for stale duplicates")

    stats = {'deleted': 0, 'kept_no_new_doc': 0, 'skipped_authoritative': 0, 'errors': 0}
    batch = db.batch()
    batch_count = 0
    last_doc = None

    while True:
        query = db.collection('lessons').where('sourceId', '==', source_id).limit(500)
        if last_doc:
            query = query.start_after(last_doc)
        docs = list(query.stream())
        if not docs:
            break
        last_doc = docs[-1]

        for doc in docs:
            try:
                data = doc.to_dict()
                video_url = data.get('videoUrl', '')

                if not video_url or 'youtube.com' not in video_url:
                    stats['skipped_authoritative'] += 1
                    continue

                canon_id = canonical_doc_id(source_id, video_url)
                if not canon_id:
                    stats['skipped_authoritative'] += 1
                    continue

                # This doc IS the canonical one → keep
                if str(doc.id) == canon_id:
                    stats['skipped_authoritative'] += 1
                    continue

                # This doc is NOT canonical → stale duplicate.
                # Safety: only delete if the canonical doc actually exists.
                if not find_new_doc_for_url(db, source_id, video_url, doc.id):
                    logger.debug(f"  ⚠️ No canonical doc for {doc.id} ({video_url[:60]}) — keeping")
                    stats['kept_no_new_doc'] += 1
                    continue

                if not dry_run:
                    batch.delete(doc.reference)
                    batch_count += 1
                    if batch_count >= BATCH_SIZE:
                        batch.commit()
                        batch = db.batch()
                        batch_count = 0

                stats['deleted'] += 1

            except Exception as e:
                logger.error(f"  ❌ Error on doc {doc.id}: {e}")
                stats['errors'] += 1

        if len(docs) < 500:
            break

    if not dry_run and batch_count > 0:
        batch.commit()

    prefix = "[DRY RUN] " if dry_run else ""
    logger.info(
        f"  {prefix}✅ source {source_id}: "
        f"deleted={stats['deleted']} "
        f"kept_no_new_doc={stats['kept_no_new_doc']} "
        f"skipped_authoritative={stats['skipped_authoritative']} "
        f"errors={stats['errors']}"
    )
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Remove duplicate YouTube lessons from ID-scheme mismatch'
    )
    parser.add_argument('--dry-run', action='store_true', help='Preview — no deletes')
    parser.add_argument('--source', type=int, help='Only clean this source ID')
    args = parser.parse_args()

    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={'projectId': 'tora-or'})
    db = firestore.client()

    sources = YOUTUBE_SOURCE_IDS
    if args.source:
        if args.source not in YOUTUBE_SOURCE_IDS:
            logger.error(f"Source {args.source} is not a YouTube source")
            sys.exit(1)
        sources = [args.source]

    total = {'deleted': 0, 'kept_no_new_doc': 0, 'skipped_authoritative': 0, 'errors': 0}
    for source_id in sources:
        stats = cleanup_source(db, source_id, dry_run=args.dry_run)
        for k in total:
            total[k] += stats.get(k, 0)

    logger.info(f"\n🎯 Cleanup complete: {total}")
    if args.dry_run:
        logger.info("(dry run — no changes written)")
    if total['kept_no_new_doc'] > 0:
        logger.warning(
            f"⚠️ {total['kept_no_new_doc']} old docs had no matching new doc and were kept. "
            f"These may be legitimate unique lessons — investigate before deleting."
        )


if __name__ == '__main__':
    main()
