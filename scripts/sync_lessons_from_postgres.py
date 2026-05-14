#!/usr/bin/env python3
"""
Sync lessons from PostgreSQL to Firestore.

This is the PRIMARY migration script. Run this first before any reference
field fixes or integrity tests. It ensures every PostgreSQL lesson exists
in Firestore as a document.

Uses set(merge=True) — safe to re-run, existing docs are NOT overwritten.
New docs are created. Changed docs are NOT updated (use fix_lesson_references.py
for reference field updates after this runs).

Usage:
    # Sync all lessons (full sync — safe to re-run):
    python scripts/sync_lessons_from_postgres.py

    # Sync only lessons added/updated after a date (faster, for incremental sync):
    python scripts/sync_lessons_from_postgres.py --since 2025-12-30

    # Dry run — show counts without writing:
    python scripts/sync_lessons_from_postgres.py --dry-run

    # Resume after interruption:
    python scripts/sync_lessons_from_postgres.py --start 50000

Prerequisites:
    - Firebase ADC: gcloud auth application-default login
    - SSH key at ~/.ssh/id_rsa_mac_m1 with access to bitnami@3.70.156.78
    - pip install firebase-admin

What this script does:
    1. Loads Firestore reference maps (ravs, categories, series)
       so ravId/categoryId/seriesId can be resolved to Firestore doc IDs
    2. Exports lessons from PostgreSQL via SSH
    3. For each lesson, resolves FK bigint IDs → Firestore doc IDs
    4. Uploads to Firestore in batches using set(merge=True)

After running this script:
    - Run: python scripts/audit_data_gaps.py --output data/gaps_report.csv
    - Run: python -m pytest scripts/tests/ -v --tb=short
"""

import argparse
import csv
import io
import os
import shlex
import subprocess
import time

import firebase_admin
from firebase_admin import firestore

PROJECT_ID = "tora-or"
SSH_KEY = os.path.expanduser("~/.ssh/id_rsa_mac_m1")
SSH_HOST = "bitnami@3.70.156.78"
DB_NAME = "lessons"
BATCH_SIZE = 100
BATCH_DELAY = 1.0


def init_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
    return firestore.client()


def run_postgres_query(sql, timeout=120):
    """Run a small SQL query via SSH (for metadata/reference queries)."""
    copy_sql = f"COPY ({sql}) TO STDOUT WITH CSV HEADER"
    cmd = f"sudo -u postgres psql -d {DB_NAME} -c {shlex.quote(copy_sql)}"
    result = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=accept-new",
         SSH_HOST, cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PostgreSQL query failed:\n{result.stderr}")
    return list(csv.DictReader(io.StringIO(result.stdout)))


def export_lessons_via_file(sql, local_path, timeout=600):
    """
    Export a large PostgreSQL query to a local CSV file.
    Writes to /tmp on the server first, then SCP's it down.
    Use for large exports (>10K rows) where streaming over SSH times out.
    """
    remote_path = "/tmp/lessons_export.csv"

    # Write to file on server
    copy_sql = f"COPY ({sql}) TO '{remote_path}' WITH CSV HEADER"
    cmd = f"sudo -u postgres psql -d {DB_NAME} -c {shlex.quote(copy_sql)}"
    print(f"  Exporting to {remote_path} on server...")
    result = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=accept-new",
         SSH_HOST, cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PostgreSQL export failed:\n{result.stderr}")

    # Download via SCP
    print(f"  Downloading to {local_path}...")
    result = subprocess.run(
        ["scp", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=accept-new",
         f"{SSH_HOST}:{remote_path}", local_path],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"SCP download failed:\n{result.stderr}")

    with open(local_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"  Downloaded {len(rows):,} rows")
    return rows


def load_reference_maps(db):
    """
    Build PostgreSQL bigint id → Firestore doc ID maps for ravs, categories, series.
    The Firestore doc ID for each rav/category/series might be the originalId
    (small integer) or a UUID — we load all docs and map by originalId.
    """
    print("Loading Firestore reference maps...")

    def load_map(collection):
        result = {}
        for doc in db.collection(collection).stream():
            data = doc.to_dict()
            orig = data.get("originalId")
            if orig is not None:
                result[int(orig)] = doc.id
        print(f"  {collection}: {len(result)} entries")
        return result

    ravs_by_orig = load_map("ravs")
    cats_by_orig = load_map("categories")
    series_by_orig = load_map("series")

    # Also need PostgreSQL originalId for ravs/categories/series to map the FK
    # Firestore originalId = PostgreSQL "originalId" column (small int)
    # PostgreSQL FK (lessons."ravId") references ravs.id (bigint hash)
    # So we need: ravs.id (bigint) → ravs."originalId" (small int) → Firestore doc ID
    print("\nLoading PostgreSQL id→originalId mappings for ravs/categories/series...")

    def load_pg_id_map(table):
        rows = run_postgres_query(
            f'SELECT id, "originalId" FROM {table}'
        )
        return {int(r["id"]): int(r["originalId"]) for r in rows}

    rav_pg_id_to_orig = load_pg_id_map("ravs")
    cat_pg_id_to_orig = load_pg_id_map("categories")
    series_pg_id_to_orig = load_pg_id_map("series")

    print(f"  ravs: {len(rav_pg_id_to_orig)}, categories: {len(cat_pg_id_to_orig)}, series: {len(series_pg_id_to_orig)}")

    def resolve_rav(pg_bigint_id):
        if not pg_bigint_id or pg_bigint_id.strip().lower() in ("", "null", "none"):
            return None
        pg_id = int(pg_bigint_id.strip())
        orig = rav_pg_id_to_orig.get(pg_id)
        return ravs_by_orig.get(orig) if orig else None

    def resolve_cat(pg_bigint_id):
        if not pg_bigint_id or pg_bigint_id.strip().lower() in ("", "null", "none"):
            return None
        pg_id = int(pg_bigint_id.strip())
        orig = cat_pg_id_to_orig.get(pg_id)
        return cats_by_orig.get(orig) if orig else None

    def resolve_series(pg_bigint_id):
        if not pg_bigint_id or pg_bigint_id.strip().lower() in ("", "null", "none"):
            return None
        pg_id = int(pg_bigint_id.strip())
        orig = series_pg_id_to_orig.get(pg_id)
        return series_by_orig.get(orig) if orig else None

    return resolve_rav, resolve_cat, resolve_series


def build_lesson_doc(row, resolve_rav, resolve_cat, resolve_series):
    """Convert a PostgreSQL row dict to a Firestore lesson document."""
    def safe_int(val):
        if val and val.strip().lower() not in ("", "null", "none"):
            return int(val.strip())
        return None

    def safe_str(val):
        if val and val.strip().lower() not in ("null", "none"):
            return val.strip()
        return None

    return {
        "originalId":  safe_int(row.get("originalId")),
        "id":          safe_int(row.get("originalId")),  # same field, kept for compatibility
        "sourceId":    safe_int(row.get("sourceId")),
        "title":       safe_str(row.get("title")),
        "dateStr":     safe_str(row.get("dateStr")),
        "duration":    safe_int(row.get("duration")),
        "videoUrl":    safe_str(row.get("videoUrl")),
        "audioUrl":    safe_str(row.get("audioUrl")),
        "timestamp":   safe_int(row.get("timestamp")),
        "ravId":       resolve_rav(row.get("ravId")),
        "categoryId":  resolve_cat(row.get("categoryId")),
        "seriesId":    resolve_series(row.get("seriesId")),
    }


def sync_lessons(since_date=None, dry_run=False, start_row=0):
    db = init_firebase()
    resolve_rav, resolve_cat, resolve_series = load_reference_maps(db)

    # Build SQL
    where = f"WHERE l.insertedat > '{since_date}'" if since_date else ""
    sql = f"""
        SELECT l.id,
               l."originalId",
               l."sourceId",
               l."ravId",
               l."categoryId",
               l."seriesId",
               l.title,
               l."dateStr",
               l.duration,
               l."videoUrl",
               l."audioUrl",
               l.timestamp
        FROM lessons l
        {where}
        ORDER BY l.insertedat
    """

    local_csv = "data/lessons_sync.csv"
    os.makedirs("data", exist_ok=True)
    print(f"\nExporting lessons from PostgreSQL{' since ' + since_date if since_date else ' (all)'}...")
    rows = export_lessons_via_file(sql.strip(), local_csv)
    total = len(rows)
    print(f"Exported {total:,} lessons → {local_csv}")

    if start_row > 0:
        rows = rows[start_row:]
        print(f"Resuming from row {start_row} ({len(rows):,} remaining)")

    if dry_run:
        sample = build_lesson_doc(rows[0], resolve_rav, resolve_cat, resolve_series) if rows else {}
        print(f"\n[DRY RUN] Would upload {len(rows):,} lessons. Sample doc:\n{sample}")
        return

    batch = db.batch()
    batch_count = 0
    uploaded = 0
    skipped = 0

    for i, row in enumerate(rows):
        lesson_fs_id = row["id"].strip()  # bigint string — Firestore doc ID
        doc_data = build_lesson_doc(row, resolve_rav, resolve_cat, resolve_series)

        # Skip rows with no useful data
        if not doc_data.get("sourceId"):
            skipped += 1
            continue

        doc_ref = db.collection("lessons").document(lesson_fs_id)
        batch.set(doc_ref, doc_data, merge=True)
        batch_count += 1

        if batch_count >= BATCH_SIZE:
            try:
                batch.commit()
                uploaded += batch_count
            except Exception as e:
                print(f"  ⚠️  Batch error at row {start_row + i}: {e}")
            batch = db.batch()
            batch_count = 0

            if uploaded % 5000 == 0:
                print(f"  {uploaded:,}/{total:,} uploaded...")
            time.sleep(BATCH_DELAY)

    # Final batch
    if batch_count > 0:
        try:
            batch.commit()
            uploaded += batch_count
        except Exception as e:
            print(f"  ⚠️  Final batch error: {e}")

    print(f"\nDone.")
    print(f"  Uploaded: {uploaded:,}")
    print(f"  Skipped:  {skipped:,}")
    print(f"  Total:    {total:,}")
    print(f"\nNext steps:")
    print(f"  1. python scripts/fix_lesson_references.py --input data/lesson_refs_rav.csv --field rav")
    print(f"  2. python scripts/audit_data_gaps.py --output data/gaps_report.csv")
    print(f"  3. python -m pytest scripts/tests/ -v --tb=short")


def main():
    parser = argparse.ArgumentParser(description="Sync lessons from PostgreSQL to Firestore")
    parser.add_argument("--since", default=None,
                        help="Only sync lessons inserted after this date (e.g. 2025-12-30)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--start", type=int, default=0,
                        help="Skip first N rows (resume after interruption)")
    args = parser.parse_args()

    sync_lessons(since_date=args.since, dry_run=args.dry_run, start_row=args.start)


if __name__ == "__main__":
    main()
