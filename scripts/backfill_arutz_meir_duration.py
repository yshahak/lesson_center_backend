#!/usr/bin/env python3 -u
"""
Backfill duration for Arutz Meir (sourceId=2) lessons where duration=0.

Strategy: range-request the first 128KB of each lesson's siteAudioUrl and
use mutagen to read duration from the MPEG header (Xing/LAME frame).
No Cloudflare bypass needed — mp3.meirtv.co.il is a direct CDN.

Skips lessons with no siteAudioUrl (vimeo-only — can't backfill from audio).
Saves progress to a cursor file so the script is resumable.

Usage:
  pip install mutagen
  python scripts/backfill_arutz_meir_duration.py --dry-run --limit 20
  python scripts/backfill_arutz_meir_duration.py
  python scripts/backfill_arutz_meir_duration.py --reset   # restart from scratch
"""

import argparse
import io
import json
import os
import sys
import time
import requests
from collections import defaultdict

import firebase_admin
from firebase_admin import firestore

try:
    from mutagen.mp3 import MP3
    from mutagen import MutagenError
except ImportError:
    print("mutagen not installed. Run: pip install mutagen", file=sys.stderr)
    sys.exit(1)

PROJECT_ID = "tora-or"
SOURCE_ID = 2
CURSOR_FILE = "data/backfill_duration_cursor.json"
RANGE_BYTES = 131072  # 128KB — enough for MPEG Xing/LAME header

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"


def init_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
    return firestore.client()


import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "functions"))
from utils.duration import get_duration_from_audio_url, get_duration_from_vimeo, get_duration


def load_cursor() -> str | None:
    if os.path.exists(CURSOR_FILE):
        with open(CURSOR_FILE) as f:
            return json.load(f).get("last_doc_id")
    return None


def save_cursor(doc_id: str):
    os.makedirs("data", exist_ok=True)
    with open(CURSOR_FILE, "w") as f:
        json.dump({"last_doc_id": doc_id}, f)


def get_last_n_missing(db, n: int) -> list:
    """
    Return the N most recently added sourceId=2 lessons that are missing duration.
    'Most recently added' = highest originalId (WP post ID).
    Loads all sourceId=2 lessons in memory, filters, sorts by originalId DESC, takes N.
    """
    print(f"Loading all sourceId=2 lessons to find last {n} missing duration...")
    all_docs = list(db.collection("lessons").where("sourceId", "==", SOURCE_ID).stream())
    print(f"  Loaded {len(all_docs):,} docs")

    candidates = []
    for doc in all_docs:
        d = doc.to_dict()
        if (d.get("duration") or 0) > 0:
            continue
        # Include lessons with siteAudioUrl OR vimeoId — both can provide duration
        if not d.get("siteAudioUrl") and not d.get("vimeoId"):
            continue
        orig = d.get("originalId")
        if orig is None:
            continue
        candidates.append((int(str(orig)), doc))

    candidates.sort(key=lambda x: x[0], reverse=True)  # highest originalId first
    result = [doc for _, doc in candidates[:n]]
    print(f"  Found {len(candidates):,} missing-duration lessons, taking last {len(result)}")
    return result


def run(dry_run: bool, limit: int | None, reset: bool, last: int | None):
    db = init_firebase()

    # --last N mode: process only the N most recently added missing-duration lessons
    if last:
        docs_to_process = get_last_n_missing(db, last)
        processed = 0
        updated = 0
        errors = 0
        write_batch = db.batch()
        batch_count = 0

        for doc in docs_to_process:
            d = doc.to_dict()
            url = d.get("siteAudioUrl", "")
            vimeo_id = d.get("vimeoId", "")
            orig_id = d.get("originalId")

            duration = get_duration(url, vimeo_id, session) or None
            processed += 1

            if duration and duration > 0:
                if dry_run:
                    print(f"  [{processed}] {orig_id}: {duration}s ({duration//60}min) — {url[-40:]}")
                else:
                    write_batch.update(doc.reference, {"duration": duration})
                    batch_count += 1
                    updated += 1
                    if batch_count >= 400:
                        write_batch.commit()
                        write_batch = db.batch()
                        batch_count = 0
                        print(f"  Committed. processed={processed} updated={updated}")
            else:
                errors += 1
                print(f"  [{processed}] {orig_id}: no duration — {url[-40:]}")
            time.sleep(0.1)

        if not dry_run and batch_count > 0:
            write_batch.commit()

        print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
        print(f"  Processed: {processed}  Updated: {updated}  Errors: {errors}")
        return

    # Full / resumable mode
    if reset and os.path.exists(CURSOR_FILE):
        os.remove(CURSOR_FILE)
        print("Cursor reset.")

    cursor_doc_id = None if reset else load_cursor()
    if cursor_doc_id:
        print(f"Resuming from cursor: {cursor_doc_id}")
    else:
        print("Starting from beginning.")

    # Simple query: sourceId=2, paginated by __name__. Filter duration=0 and
    # siteAudioUrl in memory to avoid needing composite indexes.
    query = (db.collection("lessons")
               .where("sourceId", "==", SOURCE_ID)
               .order_by("__name__"))

    PAGE_SIZE = 200
    processed = 0
    updated = 0
    skipped_no_url = 0
    errors = 0
    last_doc = None

    # Fast-forward to cursor
    if cursor_doc_id:
        cursor_ref = db.collection("lessons").document(cursor_doc_id).get()
        if cursor_ref.exists:
            query = query.start_after(cursor_ref)

    write_batch = db.batch()
    batch_count = 0

    print(f"{'[DRY RUN] ' if dry_run else ''}Fetching lessons with duration=0 and siteAudioUrl...")

    while True:
        page = list(query.limit(PAGE_SIZE).stream())
        if not page:
            break

        for doc in page:
            if limit and processed >= limit:
                break

            data = doc.to_dict()
            url = data.get("siteAudioUrl", "")
            orig_id = data.get("originalId")
            current_duration = data.get("duration", 0) or 0

            if not url:
                skipped_no_url += 1
                continue

            if current_duration > 0:
                continue  # already has duration, skip

            vimeo_id = data.get("vimeoId", "")
            duration = get_duration(url, vimeo_id, session) or None
            processed += 1

            if duration and duration > 0:
                if dry_run:
                    print(f"  [{processed}] {orig_id}: {duration}s ({duration//60}min) — {url[-40:]}")
                else:
                    write_batch.update(doc.reference, {"duration": duration})
                    batch_count += 1
                    updated += 1

                    if batch_count >= 400:
                        write_batch.commit()
                        write_batch = db.batch()
                        batch_count = 0
                        save_cursor(doc.id)
                        print(f"  Committed batch. Processed={processed} updated={updated} errors={errors}")
            else:
                errors += 1
                if dry_run:
                    print(f"  [{processed}] {orig_id}: ERROR/no duration — {url[-40:]}")

            last_doc = doc
            time.sleep(0.1)  # gentle pace

        if (limit and processed >= limit) or len(page) < PAGE_SIZE:
            break

        query = query.start_after(page[-1])

    if not dry_run and batch_count > 0:
        write_batch.commit()
        if last_doc:
            save_cursor(last_doc.id)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Processed: {processed}")
    print(f"  Updated:   {updated}")
    print(f"  Errors:    {errors}")
    print(f"  Skipped (no URL): {skipped_no_url}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Stop after N lessons in full mode")
    parser.add_argument("--last", type=int, help="Process only the N most recently added missing-duration lessons")
    parser.add_argument("--reset", action="store_true", help="Restart full mode from beginning")
    args = parser.parse_args()
    run(args.dry_run, args.limit, args.reset, args.last)


if __name__ == "__main__":
    main()
