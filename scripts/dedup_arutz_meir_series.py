#!/usr/bin/env python3 -u
"""
Fix split series for Arutz Meir (sourceId=2).

Multiple Firestore docs exist for the same WP series (same wpTermId).
Lessons are split across them. This script:
  1. For each duplicate group, picks the doc with the most lessons as canonical.
  2. Re-points all lessons from non-canonical docs to the canonical doc.
  3. Updates the canonical doc's totalCount.
  4. Deletes non-canonical docs.

Only touches series with duplicate wpTermId. Integer-integer pairs without
wpTermId are not touched.

Usage:
  python scripts/dedup_arutz_meir_series.py --dry-run
  python scripts/dedup_arutz_meir_series.py
"""

import argparse
import time
from collections import defaultdict

import firebase_admin
from firebase_admin import firestore

SOURCE_ID = 2
PROJECT_ID = "tora-or"


def init_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
    return firestore.client()


def get_actual_lesson_count(db, series_id):
    result = db.collection("lessons").where("sourceId", "==", SOURCE_ID).where("seriesId", "==", series_id).count().get()
    return int(result[0][0].value)


def run(dry_run):
    db = init_firebase()

    print(f"{'[DRY RUN] ' if dry_run else ''}Loading series docs for sourceId=2...")
    all_series = [(d.id, d.to_dict()) for d in db.collection("series").where("sourceId", "==", SOURCE_ID).stream()]
    print(f"  Total series docs: {len(all_series)}")

    # Group by wpTermId — only process groups with a real wpTermId
    by_wp = defaultdict(list)
    for doc_id, data in all_series:
        wp = data.get("wpTermId")
        if wp:
            by_wp[wp].append((doc_id, data))

    dup_groups = {k: v for k, v in by_wp.items() if len(v) > 1}
    print(f"  Duplicate groups by wpTermId: {len(dup_groups)}")

    total_repointed = 0
    total_deleted = 0

    for wp_id, docs in sorted(dup_groups.items()):
        name = docs[0][1].get("serie", "?")

        # Get actual lesson counts for each doc
        counts = []
        for doc_id, data in docs:
            actual = get_actual_lesson_count(db, doc_id)
            counts.append((doc_id, data, actual))

        counts.sort(key=lambda x: x[2], reverse=True)  # most lessons = canonical
        canonical_id, canonical_data, canonical_count = counts[0]
        non_canonical = [(doc_id, data, cnt) for doc_id, data, cnt in counts[1:]]

        lessons_to_repoint = sum(cnt for _, _, cnt in non_canonical)
        docs_to_delete = [doc_id for doc_id, _, _ in non_canonical]

        print(f"\n  wpTermId={wp_id} \"{name}\":")
        print(f"    Keep:   {canonical_id} ({canonical_count} lessons)")
        for doc_id, _, cnt in non_canonical:
            print(f"    Delete: {doc_id} ({cnt} lessons to re-point)")

        if dry_run:
            total_repointed += lessons_to_repoint
            total_deleted += len(docs_to_delete)
            continue

        # Re-point lessons from each non-canonical doc to canonical
        for doc_id, _, cnt in non_canonical:
            if cnt == 0:
                continue
            print(f"    Re-pointing {cnt} lessons from {doc_id} → {canonical_id}...")
            # Fetch in pages of 400
            offset_doc = None
            repointed = 0
            while True:
                q = (db.collection("lessons")
                     .where("sourceId", "==", SOURCE_ID)
                     .where("seriesId", "==", doc_id)
                     .limit(400))
                if offset_doc:
                    q = q.start_after(offset_doc)
                batch_docs = list(q.stream())
                if not batch_docs:
                    break
                batch = db.batch()
                for lesson in batch_docs:
                    batch.update(lesson.reference, {"seriesId": canonical_id})
                batch.commit()
                repointed += len(batch_docs)
                offset_doc = batch_docs[-1]
                time.sleep(0.2)
            print(f"      Re-pointed {repointed} lessons.")
            total_repointed += repointed

        # Update canonical doc totalCount
        new_total = get_actual_lesson_count(db, canonical_id)
        db.collection("series").document(canonical_id).update({"totalCount": new_total})
        print(f"    Updated totalCount on {canonical_id}: {new_total}")

        # Delete non-canonical docs
        for doc_id in docs_to_delete:
            db.collection("series").document(doc_id).delete()
            print(f"    Deleted {doc_id}")
            total_deleted += 1

        time.sleep(0.1)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Lessons re-pointed: {total_repointed}")
    print(f"  Series docs deleted: {total_deleted}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.dry_run)


if __name__ == "__main__":
    main()