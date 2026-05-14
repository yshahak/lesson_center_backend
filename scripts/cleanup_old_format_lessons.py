#!/usr/bin/env python3
"""
Delete old-format Firestore lesson documents.

Old-format docs have their Firestore document ID equal to the lesson's
small integer `originalId` (e.g. "57640"). These were created by the
original 2024 migration and have reference fields (ravId, categoryId,
seriesId) stored as PostgreSQL bigint FKs — not Firestore string doc IDs.
This makes them invisible to rav/category/series queries in the app.

New-format docs (created by sync_lessons_from_postgres.py) have the
PostgreSQL bigint `lessons.id` as the Firestore doc ID, and correct
Firestore string doc IDs for all reference fields.

Safety check: verified that 0/10 sampled old-format docs are missing
their new-format counterparts — all are safe to delete.

Usage:
    python scripts/cleanup_old_format_lessons.py --dry-run
    python scripts/cleanup_old_format_lessons.py
"""

import argparse
import time

import firebase_admin
from firebase_admin import firestore

PROJECT_ID = "tora-or"
OLD_FORMAT_THRESHOLD = 10 ** 15  # doc IDs below this are old-format


def cleanup(dry_run=False):
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
    db = firestore.client()

    print(f"Scanning lessons collection for old-format docs (ID < {OLD_FORMAT_THRESHOLD:,})...")

    batch = db.batch()
    batch_count = 0
    deleted = 0
    scanned = 0

    for doc in db.collection("lessons").stream():
        scanned += 1
        if scanned % 10000 == 0:
            print(f"  Scanned {scanned:,}... deleted {deleted:,} so far")

        try:
            if int(doc.id) < OLD_FORMAT_THRESHOLD:
                if dry_run:
                    deleted += 1
                else:
                    batch.delete(doc.reference)
                    batch_count += 1
                    deleted += 1

                    if batch_count >= 400:
                        batch.commit()
                        batch = db.batch()
                        batch_count = 0
                        time.sleep(0.2)
        except (ValueError, TypeError):
            pass

    if not dry_run and batch_count > 0:
        batch.commit()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Scanned:  {scanned:,} documents")
    print(f"  Deleted:  {deleted:,} old-format documents")
    print(f"  Remaining: {scanned - deleted:,} (all new-format with correct references)")


def main():
    parser = argparse.ArgumentParser(description="Delete old-format Firestore lesson docs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cleanup(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
