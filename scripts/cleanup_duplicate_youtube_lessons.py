#!/usr/bin/env python3
"""
Remove duplicate YouTube lessons created by the ID-scheme mismatch bug (May 13 2026).

Background:
  The PostgreSQL migration seeded YouTube lessons (sources 50-74) with Firestore
  doc IDs derived from pg_lessons.id. When the Cloud Function scraper ran for the
  first time, source docs had empty 'lessonIds' arrays, so the scraper treated every
  video as new and created a second doc per video using hash-based IDs. Result:
  ~42K duplicate lessons across 18 channels.

How we identify old (migration-era) docs:
  - sourceId in [50, 51, 52, 60-74]
  - No 'createdAt' field (migration never set it; scraper always sets it)

Safety check (never delete unless a new doc exists for the same video):
  For every candidate old doc, verify a NEW doc exists with the same sourceId+videoUrl
  before deleting. If no new doc found, the old doc is kept (it's the only copy).

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
from datetime import datetime

import firebase_admin
from firebase_admin import firestore

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

YOUTUBE_SOURCE_IDS = [50, 51, 52, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74]
BATCH_SIZE = 400


def is_old_format(data: dict) -> bool:
    """Migration-era doc: no createdAt field."""
    return not data.get('createdAt')


def find_new_doc_for_url(db, source_id: int, video_url: str, old_doc_id: str) -> bool:
    """Return True if a NEW doc (with createdAt) exists for this sourceId+videoUrl,
    different from the old doc itself."""
    docs = list(
        db.collection('lessons')
        .where('sourceId', '==', source_id)
        .where('videoUrl', '==', video_url)
        .stream()
    )
    for doc in docs:
        if doc.id == old_doc_id:
            continue
        if doc.to_dict().get('createdAt'):
            return True
    return False


def cleanup_source(db, source_id: int, dry_run: bool = False):
    """
    Delete old-format duplicate docs for one source.
    Returns stats dict.
    """
    logger.info(f"🔍 Scanning source {source_id} for old-format duplicates")

    stats = {'deleted': 0, 'kept_no_new_doc': 0, 'skipped_new_format': 0, 'errors': 0}
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

                if not is_old_format(data):
                    stats['skipped_new_format'] += 1
                    continue

                video_url = data.get('videoUrl', '')
                if not video_url or 'youtube.com' not in video_url:
                    # Non-YouTube lesson without createdAt — don't touch
                    stats['skipped_new_format'] += 1
                    continue

                # Safety: only delete if a new-format doc exists for same video
                if not find_new_doc_for_url(db, source_id, video_url, doc.id):
                    logger.debug(f"  ⚠️ No new doc found for {doc.id} ({video_url[:60]}) — keeping")
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
        f"skipped_new_format={stats['skipped_new_format']} "
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

    total = {'deleted': 0, 'kept_no_new_doc': 0, 'errors': 0}
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
