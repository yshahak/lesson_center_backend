#!/usr/bin/env python3
"""
Fix ravId, categoryId, and seriesId reference fields in Firestore lessons.

Most lessons were migrated with these fields set to null because the original
batch migration didn't resolve the PostgreSQL integer IDs to Firestore doc IDs.
This script reads a CSV exported from PostgreSQL and fixes all three fields.

STEP 1 — Export from PostgreSQL (run on the AWS server):
    ssh -i ~/.ssh/id_rsa_mac_m1 bitnami@3.70.156.78

    # NOTE: Use a JOIN for ravId — lessons.ravid is a FK to ravs.id, but
    # Firestore rav_map is keyed by ravs.originalId (which may differ from ravs.id).
    psql -d lessons -U yaakov -h localhost -c "
      \\COPY (
        SELECT l.id            AS original_id,
               r.originalid   AS rav_original_id,
               l.categoryid   AS category_original_id,
               l.seriesid     AS series_original_id
        FROM   lessons l
        LEFT JOIN ravs r ON l.ravid = r.id
        WHERE  l.ravid IS NOT NULL
           OR  l.categoryid IS NOT NULL
           OR  l.seriesid IS NOT NULL
      ) TO '/tmp/lesson_refs.csv' WITH CSV HEADER;"
    exit

STEP 2 — Download the CSV:
    scp -i ~/.ssh/id_rsa_mac_m1 bitnami@3.70.156.78:/tmp/lesson_refs.csv ./data/lesson_refs.csv

STEP 3 — Run this script:
    python scripts/fix_lesson_references.py --input data/lesson_refs.csv

    Optional flags:
      --dry-run       Print what would change without writing to Firestore
      --field rav     Only fix ravId (choices: rav, category, series, all)
      --start 50000   Skip the first N rows (resume after interruption)
"""

import argparse
import csv
import sys
import time

import firebase_admin
from firebase_admin import firestore

PROJECT_ID = "tora-or"
BATCH_SIZE = 200   # Stay under Firestore's 500-op limit
BATCH_DELAY = 1.0  # Seconds between batches — avoids quota exhaustion


def init_firebase():
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def load_reference_maps(db):
    """Build originalId → Firestore docId maps for ravs, categories, and series."""
    print("Loading reference collections from Firestore...")

    rav_map = {}
    for doc in db.collection("ravs").stream():
        orig = doc.to_dict().get("originalId")
        if orig is not None:
            rav_map[int(orig)] = doc.id
    print(f"  Ravs: {len(rav_map)} documents")

    cat_map = {}
    for doc in db.collection("categories").stream():
        orig = doc.to_dict().get("originalId")
        if orig is not None:
            cat_map[int(orig)] = doc.id
    print(f"  Categories: {len(cat_map)} documents")

    series_map = {}
    for doc in db.collection("series").stream():
        orig = doc.to_dict().get("originalId")
        if orig is not None:
            series_map[int(orig)] = doc.id
    print(f"  Series: {len(series_map)} documents")

    return rav_map, cat_map, series_map


def _commit_batch_with_fallback(batch, doc_refs_and_updates):
    """
    Commit a batch. If it fails (e.g. one document doesn't exist),
    fall back to individual updates so the other documents still get updated.
    Returns (success_count, not_found_count, error_count).
    """
    try:
        batch.commit()
        return len(doc_refs_and_updates), 0, 0
    except Exception:
        # Batch failed — fall back to individual updates
        success = not_found = errors = 0
        for ref, updates in doc_refs_and_updates:
            try:
                ref.update(updates)
                success += 1
            except Exception as e:
                if "NOT_FOUND" in str(e) or "no document to update" in str(e).lower():
                    not_found += 1
                else:
                    errors += 1
        return success, not_found, errors


def fix_references(input_csv, dry_run=False, fields="all", start_row=0):
    init_firebase()
    db = firestore.client()

    rav_map, cat_map, series_map = load_reference_maps(db)

    fix_rav = fields in ("rav", "all")
    fix_cat = fields in ("category", "all")
    fix_series = fields in ("series", "all")

    print(f"\nReading {input_csv} (skipping first {start_row} data rows)...")
    with open(input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    rows = rows[start_row:]
    print(f"Total rows in CSV: {total}. Processing {len(rows)} rows.")

    batch = db.batch()
    pending = []  # (doc_ref, updates) pairs for current batch
    updated = 0
    not_in_firestore = 0
    skipped_no_ref = 0
    errors = 0
    processed = 0

    for i, row in enumerate(rows):
        processed += 1
        lesson_id = row["original_id"].strip()  # exact string — never use float() on 18-digit IDs

        updates = {}

        if fix_rav:
            raw = row.get("rav_original_id", "").strip()
            if raw and raw.lower() not in ("", "none", "null"):
                rav_orig = int(float(raw))
                if rav_orig in rav_map:
                    updates["ravId"] = rav_map[rav_orig]
                else:
                    skipped_no_ref += 1

        if fix_cat:
            raw = row.get("category_original_id", "").strip()
            if raw and raw.lower() not in ("", "none", "null"):
                cat_orig = int(float(raw))
                if cat_orig in cat_map:
                    updates["categoryId"] = cat_map[cat_orig]

        if fix_series:
            raw = row.get("series_original_id", "").strip()
            if raw and raw.lower() not in ("", "none", "null"):
                series_orig = int(float(raw))
                if series_orig in series_map:
                    updates["seriesId"] = series_map[series_orig]

        if not updates:
            continue

        if dry_run:
            if updated < 5:
                print(f"  [DRY RUN] lesson {lesson_id}: {updates}")
            updated += 1
            continue

        doc_ref = db.collection("lessons").document(lesson_id)
        batch.update(doc_ref, updates)
        pending.append((doc_ref, updates))

        if len(pending) >= BATCH_SIZE:
            ok, missing, err = _commit_batch_with_fallback(batch, pending)
            updated += ok
            not_in_firestore += missing
            errors += err
            print(
                f"  Batch done — ok={ok} missing={missing} err={err} | "
                f"total updated={updated}, {processed + start_row}/{total} rows"
            )
            batch = db.batch()
            pending = []
            time.sleep(BATCH_DELAY)

    # Commit remaining
    if pending and not dry_run:
        ok, missing, err = _commit_batch_with_fallback(batch, pending)
        updated += ok
        not_in_firestore += missing
        errors += err

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Updated:              {updated}")
    print(f"  Not in Firestore:     {not_in_firestore}  (lessons in PostgreSQL not yet migrated)")
    print(f"  Skipped (no mapping): {skipped_no_ref}")
    print(f"  Errors:               {errors}")
    print(f"  Total rows processed: {processed + start_row}/{total}")


def main():
    parser = argparse.ArgumentParser(description="Fix Firestore lesson reference fields")
    parser.add_argument("--input", required=True, help="Path to lesson_refs.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--field",
        choices=["rav", "category", "series", "all"],
        default="all",
        help="Which field to fix (default: all)",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Skip first N data rows (for resuming interrupted runs)",
    )
    args = parser.parse_args()

    fix_references(args.input, dry_run=args.dry_run, fields=args.field, start_row=args.start)


if __name__ == "__main__":
    main()
