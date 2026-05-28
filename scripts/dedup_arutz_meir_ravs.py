#!/usr/bin/env python3 -u
"""
Fix duplicate rav docs for Arutz Meir (sourceId=2).

Only fixes the `rav_N` vs integer-ID duplicates created by
create_missing_arutz_meir_taxonomy.py. These are ravs where a `rav_NNNN` doc
was created for a WP term that already had an integer-ID doc (e.g. id=18521).

Action:
  1. Re-points the small number of lessons from `rav_N` docs to the integer-ID doc.
  2. Copies wpTermId from `rav_N` onto the integer-ID doc (so scraper finds it).
  3. Deletes the `rav_N` docs.

Does NOT touch integer-integer rav pairs (e.g. 3968/3969) — those may be
genuinely different WP users with the same name.

Usage:
  python scripts/dedup_arutz_meir_ravs.py --dry-run
  python scripts/dedup_arutz_meir_ravs.py
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


def run(dry_run):
    db = init_firebase()

    print(f"{'[DRY RUN] ' if dry_run else ''}Loading rav docs for sourceId=2...")
    all_ravs = [(d.id, d.to_dict()) for d in db.collection("ravs").where("sourceId", "==", SOURCE_ID).stream()]
    print(f"  Total rav docs: {len(all_ravs)}")

    by_name = defaultdict(list)
    for doc_id, data in all_ravs:
        by_name[data.get("rav", "")].append((doc_id, data))

    dup_groups = {k: v for k, v in by_name.items() if len(v) > 1}
    print(f"  Duplicate groups by name: {len(dup_groups)}")

    total_repointed = 0
    total_deleted = 0

    for name, docs in sorted(dup_groups.items()):
        # Separate rav_ prefixed docs from integer-ID docs
        rav_prefix = [(doc_id, data) for doc_id, data in docs if doc_id.startswith("rav_")]
        int_id = [(doc_id, data) for doc_id, data in docs if not doc_id.startswith("rav_")]

        if not rav_prefix or not int_id:
            # Both are integer-IDs or both are rav_ — skip (may be genuine different WP terms)
            print(f"\n  SKIP \"{name}\": no rav_ vs int-ID pair — {[d for d,_ in docs]}")
            continue

        if len(int_id) > 1:
            # Multiple integer-ID docs for same name — skip, too ambiguous
            print(f"\n  SKIP \"{name}\": multiple integer-ID docs — {[d for d,_ in int_id]}")
            continue

        canonical_id, canonical_data = int_id[0]

        print(f"\n  \"{name}\":")
        print(f"    Keep (integer-ID):  {canonical_id}  originalId={canonical_data.get('originalId')}  wpTermId={canonical_data.get('wpTermId')}")

        for rav_doc_id, rav_data in rav_prefix:
            wp_term_id = rav_data.get("wpTermId")

            # Count actual lessons on the rav_ doc
            result = db.collection("lessons").where("sourceId", "==", SOURCE_ID).where("ravId", "==", rav_doc_id).count().get()
            actual = int(result[0][0].value)
            print(f"    Delete (rav_ doc):  {rav_doc_id}  wpTermId={wp_term_id}  actual_lessons={actual}")

            if dry_run:
                total_repointed += actual
                total_deleted += 1
                continue

            # Re-point lessons from rav_ doc to canonical
            if actual > 0:
                print(f"      Re-pointing {actual} lessons...")
                fetched = list(
                    db.collection("lessons")
                    .where("sourceId", "==", SOURCE_ID)
                    .where("ravId", "==", rav_doc_id)
                    .stream()
                )
                batch = db.batch()
                for lesson in fetched:
                    batch.update(lesson.reference, {"ravId": canonical_id})
                batch.commit()
                print(f"      Re-pointed {len(fetched)} lessons.")
                total_repointed += len(fetched)

            # Copy wpTermId to canonical doc if it doesn't have one
            if wp_term_id and not canonical_data.get("wpTermId"):
                db.collection("ravs").document(canonical_id).update({"wpTermId": wp_term_id})
                print(f"      Set wpTermId={wp_term_id} on {canonical_id}")

            # Delete the rav_ doc
            db.collection("ravs").document(rav_doc_id).delete()
            print(f"      Deleted {rav_doc_id}")
            total_deleted += 1
            time.sleep(0.1)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Lessons re-pointed: {total_repointed}")
    print(f"  Rav docs deleted: {total_deleted}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.dry_run)


if __name__ == "__main__":
    main()