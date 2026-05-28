#!/usr/bin/env python3 -u
"""
Build a local cache mapping WP term ID → lesson IDs for sourceId=2 series and categories.

Uses the WP REST API taxonomy filter (no Cloudflare bypass needed):
  GET meirtv.com/wp-json/wp/v2/shiurim?shiurim-series={id}&per_page=100&_fields=id

Ravs are intentionally skipped — top ravs have 8K+ lessons (85 pages each),
making the call count prohibitive. Series + categories are enough to fix the
null-taxonomy lessons.

Cache file: data/wp_term_lessons_cache.json  (persisted after EVERY term fetch)
Structure:
  {
    "series":     { "14911": [306227, 346923, ...], ... },
    "categories": { "16277": [123, 456, ...], ... }
  }

Resumable: already-cached terms are skipped on re-run. Safe to kill and restart.
Estimated calls: ~2,060 at 3s apart = ~2 hours total, ~15 calls/min.

Usage:
  python scripts/build_wp_term_lessons_cache.py              # full run
  python scripts/build_wp_term_lessons_cache.py --dry-run    # show what would be fetched
  python scripts/build_wp_term_lessons_cache.py --limit 50   # stop after 50 terms
"""

import argparse
import json
import os
import sys
import time

import firebase_admin
import requests
from firebase_admin import firestore

BASE_URL = "https://meirtv.com/wp-json/wp/v2"
SOURCE_ID = 2
CACHE_FILE = "data/wp_term_lessons_cache.json"
PROJECT_ID = "tora-or"

# Taxonomy name in WP API query param → cache key (ravs skipped — too many pages)
TAXONOMY_MAP = {
    "shiurim-series":   "series",
    "shiurim-category": "categories",
}

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"series": {}, "categories": {}}


def save_cache(cache: dict):
    os.makedirs("data", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def fetch_lessons_for_term(wp_param: str, term_id: int) -> list[int]:
    """Fetch all lesson IDs for a given taxonomy term via paginated WP REST API."""
    ids = []
    page = 1
    while True:
        try:
            r = session.get(
                f"{BASE_URL}/shiurim",
                params={wp_param: term_id, "per_page": 100, "_fields": "id", "page": page},
                timeout=20,
            )
        except Exception as e:
            print(f"    ⚠ request error page {page}: {e}", file=sys.stderr)
            time.sleep(5)
            break

        if r.status_code == 400:
            # WP returns 400 when page > total pages — normal end of pagination
            break
        if r.status_code != 200:
            print(f"    ⚠ HTTP {r.status_code} page {page}", file=sys.stderr)
            time.sleep(3)
            break

        data = r.json()
        if not data:
            break

        ids.extend(item["id"] for item in data)

        # Check X-WP-TotalPages header
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break

        page += 1
        time.sleep(2.0)  # polite delay between pages of the same term

    return ids


def get_all_wp_term_ids(db) -> dict[str, list[tuple[int, str]]]:
    """
    Returns {cache_key: [(wp_term_id, name), ...]} for series and categories only.
    """
    result = {}
    for coll, cache_key in [("series", "series"), ("categories", "categories")]:
        terms = []
        for doc in db.collection(coll).where("sourceId", "==", SOURCE_ID).stream():
            d = doc.to_dict()
            wp_id = d.get("wpTermId")
            name = d.get("serie") or d.get("category") or ""
            if wp_id is not None:
                terms.append((int(wp_id), name))
        result[cache_key] = terms
        print(f"  {coll}: {len(terms)} terms with wpTermId")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fetched, don't fetch")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N API fetch operations")
    args = parser.parse_args()

    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
    db = firestore.client()

    cache = load_cache()
    cached_counts = {k: len(v) for k, v in cache.items()}
    print(f"Cache loaded: series={cached_counts['series']}, categories={cached_counts['categories']}")

    print("\nLoading terms from Firestore...")
    all_terms = get_all_wp_term_ids(db)

    # WP query param per taxonomy
    wp_param_for = {"series": "shiurim-series", "categories": "shiurim-category"}

    total_to_fetch = sum(
        sum(1 for (wp_id, _) in terms if str(wp_id) not in cache[cache_key])
        for cache_key, terms in all_terms.items()
    )
    print(f"\nTerms already cached: {sum(cached_counts.values())}")
    print(f"Terms to fetch:       {total_to_fetch}")
    print(f"Est. API calls:       ~{int(total_to_fetch * 1.1):,}  (~{int(total_to_fetch * 1.1 * 3 / 60)} min at 3s/term)")

    if args.dry_run:
        for cache_key, terms in all_terms.items():
            missing = [(wp_id, name) for wp_id, name in terms if str(wp_id) not in cache[cache_key]]
            print(f"\n  {cache_key}: {len(missing)} to fetch")
            for wp_id, name in missing[:5]:
                print(f"    wpTermId={wp_id}  \"{name}\"")
            if len(missing) > 5:
                print(f"    ... and {len(missing) - 5} more")
        print("\n[DRY RUN] No requests made.")
        return

    fetch_count = 0
    for cache_key, terms in all_terms.items():
        wp_param = wp_param_for[cache_key]
        missing = [(wp_id, name) for wp_id, name in terms if str(wp_id) not in cache[cache_key]]

        if not missing:
            print(f"\n{cache_key}: all {len(terms)} terms cached — skipping")
            continue

        print(f"\n{cache_key}: fetching {len(missing)}/{len(terms)} terms...")

        for i, (wp_id, name) in enumerate(missing):
            if args.limit and fetch_count >= args.limit:
                print(f"\nReached --limit {args.limit}, stopping.")
                save_cache(cache)
                return

            ids = fetch_lessons_for_term(wp_param, wp_id)
            cache[cache_key][str(wp_id)] = ids
            save_cache(cache)  # save after every term
            fetch_count += 1

            print(f"  [{i+1}/{len(missing)}] wpTermId={wp_id} \"{name[:40]}\": {len(ids)} lessons  (fetch #{fetch_count})")
            time.sleep(3.0)  # 3s between terms → ~15 calls/min

    total_lesson_ids = sum(len(ids) for terms in cache.values() for ids in terms.values())
    print(f"\nDone. Cache saved to {CACHE_FILE}")
    print(f"  Total terms cached: series={len(cache['series'])}, categories={len(cache['categories'])}")
    print(f"  Total lesson-term mappings: {total_lesson_ids:,}")


if __name__ == "__main__":
    main()
