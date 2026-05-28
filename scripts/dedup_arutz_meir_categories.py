#!/usr/bin/env python3 -u
"""
Fix duplicate category docs for Arutz Meir (sourceId=2).

Multiple docs exist for the same WP category (same wpTermId). Some groups have
lessons split across multiple docs (same problem as series). This script:
  1. For each duplicate group, picks the doc with the most lessons as canonical.
  2. Re-points lessons from non-canonical docs to the canonical doc.
  3. Updates the canonical doc's totalCount.
  4. Deletes non-canonical docs.

Only touches categories with duplicate wpTermId. Skips categories without wpTermId.

Usage:
  python scripts/dedup_arutz_meir_categories.py --dry-run
  python scripts/dedup_arutz_meir_categories.py
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


def get_actual_lesson_count(db, category_id):
    result = db.collection("lessons").where("sourceId", "==", SOURCE_ID).where("categoryId", "==", category_id).count().get()
    return int(result[0][0].value)


def run(dry_run):
    db = init_firebase()

    print(f"{'[DRY RUN] ' if dry_run else ''}Loading category docs for sourceId=2...")
    all_cats = [(d.id, d.to_dict()) for d in db.collection("categories").where("sourceId", "==", SOURCE_ID).stream()]
    print(f"  Total category docs: {len(all_cats)}")

    by_wp = defaultdict(list)
    for doc_id, data in all_cats:
        wp = data.get("wpTermId")
        if wp:
            by_wp[wp].append((doc_id, data))

    dup_groups = {k: v for k, v in by_wp.items() if len(v) > 1}
    print(f"  Duplicate groups by wpTermId: {len(dup_groups)}")

    total_repointed = 0
    total_deleted = 0

    for wp_id, docs in sorted(dup_groups.items()):
        name = docs[0][1].get("category", "?")

        counts = []
        for doc_id, data in docs:
            actual = get_actual_lesson_count(db, doc_id)
            counts.append((doc_id, data, actual))

        counts.sort(key=lambda x: x[2], reverse=True)  # most lessons = canonical
        canonical_id, canonical_data, canonical_count = counts[0]
        non_canonical = [(doc_id, data, cnt) for doc_id, data, cnt in counts[1:]]

        lessons_to_repoint = sum(cnt for _, _, cnt in non_canonical)
        has_splits = lessons_to_repoint > 0

        print(f"\n  wpTermId={wp_id} \"{name}\":")
        print(f"    Keep:   {canonical_id} ({canonical_count} lessons)")
        for doc_id, _, cnt in non_canonical:
            action = f"{cnt} lessons to re-point" if cnt > 0 else "0 lessons — safe delete"
            print(f"    Delete: {doc_id} ({action})")

        if dry_run:
            total_repointed += lessons_to_repoint
            total_deleted += len(non_canonical)
            continue

        # Re-point lessons from non-canonical docs to canonical
        for doc_id, _, cnt in non_canonical:
            if cnt == 0:
                continue
            print(f"    Re-pointing {cnt} lessons from {doc_id} → {canonical_id}...")
            offset_doc = None
            repointed = 0
            while True:
                q = (db.collection("lessons")
                     .where("sourceId", "==", SOURCE_ID)
                     .where("categoryId", "==", doc_id)
                     .limit(400))
                if offset_doc:
                    q = q.start_after(offset_doc)
                batch_docs = list(q.stream())
                if not batch_docs:
                    break
                batch = db.batch()
                for lesson in batch_docs:
                    batch.update(lesson.reference, {"categoryId": canonical_id})
                batch.commit()
                repointed += len(batch_docs)
                offset_doc = batch_docs[-1]
                time.sleep(0.2)
            print(f"      Re-pointed {repointed} lessons.")
            total_repointed += repointed

        # Update canonical doc totalCount
        new_total = get_actual_lesson_count(db, canonical_id)
        db.collection("categories").document(canonical_id).update({"totalCount": new_total})
        print(f"    Updated totalCount on {canonical_id}: {new_total}")

        # Delete non-canonical docs
        for doc_id, _, _ in non_canonical:
            db.collection("categories").document(doc_id).delete()
            print(f"    Deleted {doc_id}")
            total_deleted += 1

        time.sleep(0.1)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Lessons re-pointed: {total_repointed}")
    print(f"  Category docs deleted: {total_deleted}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.dry_run)


if __name__ == "__main__":
    main()