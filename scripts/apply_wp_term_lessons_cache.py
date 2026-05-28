#!/usr/bin/env python3 -u
"""
Fix null seriesId / categoryId on sourceId=2 Firestore lessons using the
local WP term lessons cache (data/wp_term_lessons_cache.json).

The cache maps {wpTermId → [lesson originalIds]} for every series and category.
This script:
  1. Builds {wpTermId → Firestore doc ID} from Firestore series/categories.
  2. Loads all sourceId=2 lessons with null seriesId or null categoryId,
     keyed by originalId.
  3. For each term in the cache, finds matching null-taxonomy lessons and
     writes the correct Firestore doc ID.
  4. Never overwrites a field that already has a value.

Usage:
  python scripts/apply_wp_term_lessons_cache.py --dry-run
  python scripts/apply_wp_term_lessons_cache.py
"""

import argparse
import time
from collections import defaultdict

import firebase_admin
from firebase_admin import firestore

import json
import sys
import os

CACHE_FILE = "data/wp_term_lessons_cache.json"
SOURCE_ID = 2
PROJECT_ID = "tora-or"


def init_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
    return firestore.client()


def load_cache() -> dict:
    with open(CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_wpterm_to_fs_doc(db, collection: str, name_field: str) -> dict[int, str]:
    """Returns {wpTermId (int) → Firestore doc ID (str)}."""
    result = {}
    for doc in db.collection(collection).where("sourceId", "==", SOURCE_ID).stream():
        d = doc.to_dict()
        wp_id = d.get("wpTermId")
        if wp_id is not None:
            result[int(wp_id)] = doc.id
    print(f"  {collection}: {len(result)} docs with wpTermId")
    return result


def load_null_taxonomy_lessons(db) -> dict[int, tuple]:
    """
    Returns {originalId (int) → (doc_ref, {seriesId, categoryId})} for all
    sourceId=2 lessons with null seriesId OR null categoryId.
    """
    lessons = {}
    for field in ("seriesId", "categoryId"):
        for doc in (db.collection("lessons")
                    .where("sourceId", "==", SOURCE_ID)
                    .where(field, "==", None)
                    .stream()):
            d = doc.to_dict()
            orig = d.get("originalId")
            if orig is None:
                continue
            orig_int = int(str(orig)) if str(orig).isdigit() else None
            if orig_int is None or orig_int > 500_000:
                # Skip YouTube hash-based IDs — not in WP
                continue
            if orig_int not in lessons:
                lessons[orig_int] = (doc.reference, {
                    "seriesId": d.get("seriesId"),
                    "categoryId": d.get("categoryId"),
                })
    print(f"  Lessons with null seriesId or categoryId (WP range): {len(lessons):,}")
    return lessons


def run(dry_run: bool):
    db = init_firebase()

    print("Loading cache...")
    cache = load_cache()
    total_cached = sum(len(v) for v in cache.values())
    print(f"  series: {len(cache['series'])} terms, categories: {len(cache['categories'])} terms")
    print(f"  total lesson-term mappings: {total_cached:,}")

    print("\nBuilding wpTermId → Firestore doc ID maps...")
    series_map = build_wpterm_to_fs_doc(db, "series", "serie")
    cat_map = build_wpterm_to_fs_doc(db, "categories", "category")

    print("\nLoading null-taxonomy lessons from Firestore...")
    null_lessons = load_null_taxonomy_lessons(db)
    if not null_lessons:
        print("Nothing to fix — all lessons have seriesId and categoryId set.")
        return

    # Build update plan: {lesson_ref → {field: value}}
    updates: dict = {}  # ref.path → (ref, {field: value})

    for cache_key, wp_param, fs_map, fs_field in [
        ("series",     "series",     series_map, "seriesId"),
        ("categories", "categories", cat_map,    "categoryId"),
    ]:
        hits = 0
        for wp_id_str, orig_ids in cache[cache_key].items():
            wp_id = int(wp_id_str)
            fs_doc_id = fs_map.get(wp_id)
            if not fs_doc_id:
                continue  # WP term has no Firestore doc (deleted or unknown)

            for orig_id in orig_ids:
                lesson = null_lessons.get(orig_id)
                if not lesson:
                    continue  # lesson not in our null-taxonomy set
                ref, current = lesson
                if current.get(fs_field) is not None:
                    continue  # field already set — don't overwrite

                if ref.path not in updates:
                    updates[ref.path] = (ref, {})
                updates[ref.path][1][fs_field] = fs_doc_id
                hits += 1

        print(f"  {cache_key}: {hits} lessons will get {fs_field} set")

    total_updates = len(updates)
    total_field_sets = sum(len(fields) for _, fields in updates.values())
    print(f"\nTotal lessons to update: {total_updates:,}")
    print(f"Total field writes:      {total_field_sets:,}")

    if total_updates == 0:
        print("Nothing to update.")
        return

    if dry_run:
        # Show a sample
        print("\n[DRY RUN] Sample of planned updates:")
        for i, (path, (ref, fields)) in enumerate(list(updates.items())[:10]):
            print(f"  {path.split('/')[-1]}: {fields}")
        if total_updates > 10:
            print(f"  ... and {total_updates - 10} more")
        print("\n[DRY RUN] No changes made.")
        return

    # Batch-write
    print("\nWriting to Firestore...")
    batch = db.batch()
    batch_count = 0
    written = 0

    for path, (ref, fields) in updates.items():
        batch.update(ref, fields)
        batch_count += 1
        written += 1
        if batch_count >= 400:
            batch.commit()
            print(f"  Written {written:,} so far...")
            batch = db.batch()
            batch_count = 0
            time.sleep(0.2)

    if batch_count > 0:
        batch.commit()

    print(f"\nDone. Updated {written:,} lessons ({total_field_sets:,} field writes).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    run(args.dry_run)


if __name__ == "__main__":
    main()
