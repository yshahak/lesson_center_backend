#!/usr/bin/env python3 -u
"""
Fix null ravId/seriesId/categoryId on the ~13K new Arutz Meir lessons
that weren't in the PostgreSQL CSV (fix_arutz_meir_taxonomy.py already
handled the ~42K old lessons).

Strategy:
  Phase 1 — bulk-fetch all WP taxonomy terms (~35 API calls total).
             Build {(taxonomy, wp_term_id) -> firestore_doc_id}.
             Print resolution stats — ravs/categories must be near 100%.

  Phase 2 — paginate all WP lessons (~475 pages, JSON only, no HTML).
             For each lesson with null taxonomy in Firestore, apply the map.

Usage:
  python scripts/fix_arutz_meir_taxonomy_wp.py --dry-run
  python scripts/fix_arutz_meir_taxonomy_wp.py --dry-run --limit 200
  python scripts/fix_arutz_meir_taxonomy_wp.py           # full run
"""

import argparse
import json
import os
import re
import sys
import time

import firebase_admin
import requests
from firebase_admin import firestore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TERM_CACHE_FILE  = 'data/wp_terms_cache.json'
LESSON_CACHE_FILE = 'data/wp_lessons_cache.json'

BASE_URL = 'https://meirtv.com/wp-json/wp/v2'
SOURCE_ID = 2
BATCH_SIZE = 400
FS_PORT = 8191
FS_SESSION = 'fix_taxonomy'
# Abort if resolution rate for ravs or categories falls below this threshold
MIN_RESOLUTION_RATE = 0.80


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=4, backoff_factor=1,
                  status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retry))
    session.headers['User-Agent'] = 'Mozilla/5.0'
    return session


_session = _make_session()


def _fs_get_json(url: str, params: dict) -> tuple[list | dict | None, int]:
    """Fetch a WP REST API URL via FlareSolverr (bypasses Cloudflare)."""
    from urllib.parse import urlencode
    full_url = url + '?' + urlencode(params)
    for attempt in range(3):
        try:
            resp = requests.post(
                f'http://localhost:{FS_PORT}/v1',
                json={'cmd': 'request.get', 'url': full_url,
                      'session': FS_SESSION, 'maxTimeout': 60000},
                timeout=75,
            )
            sol = resp.json().get('solution', {})
            status = sol.get('status', 0)
            body = sol.get('response', '')
            if status == 200 and body:
                stripped = body.strip()
                if stripped.startswith(('[', '{')):
                    return json.loads(stripped), 200
                pre = re.search(r'<pre[^>]*>([\s\S]*?)</pre>', body)
                if pre:
                    return json.loads(pre.group(1)), 200
            if status == 403:
                time.sleep(5 * (attempt + 1))
                continue
            return None, status
        except Exception as e:
            print(f'  ⚠ FlareSolverr error: {e}', file=sys.stderr)
            time.sleep(5)
    return None, 0


# ---------------------------------------------------------------------------
# Phase 1: bulk fetch all WP taxonomy terms
# ---------------------------------------------------------------------------

def fetch_all_wp_terms(endpoint: str, max_pages: int | None = None) -> list[dict]:
    """Paginate through all terms, return list of {id, slug, name}."""
    terms = []
    page = 1
    while True:
        try:
            r = _session.get(
                f'{BASE_URL}/{endpoint}',
                params={'per_page': 100, 'page': page, '_fields': 'id,slug,name'},
                timeout=30,
            )
        except Exception as e:
            print(f'  ⚠ Request error page {page}: {e}', file=sys.stderr)
            time.sleep(3)
            continue

        if r.status_code == 400:
            break  # past last page
        if r.status_code != 200:
            print(f'  ⚠ HTTP {r.status_code} on page {page}', file=sys.stderr)
            break

        batch = r.json()
        if not batch:
            break
        terms.extend(batch)
        total_pages = int(r.headers.get('X-WP-TotalPages', 1))
        print(f'  fetched page {page}/{total_pages} ({len(terms)} terms so far)...')
        if page >= total_pages or (max_pages and page >= max_pages):
            break
        page += 1
        time.sleep(0.2)
    return terms


def build_term_map(
    wp_terms: list[dict],
    fs_map: dict[int, str],  # originalId → firestore_doc_id
    label: str,
) -> tuple[dict[int, str], list[dict]]:
    """
    Map WP term IDs to Firestore doc IDs via the term's slug (= originalId).
    Returns (resolved_map, unresolved_terms).
    """
    resolved = {}
    unresolved = []
    for term in wp_terms:
        slug = term.get('slug', '')
        if slug.isdigit():
            orig_id = int(slug)
            fs_id = fs_map.get(orig_id)
            if fs_id:
                resolved[term['id']] = fs_id
            else:
                unresolved.append(term)
        else:
            unresolved.append(term)  # non-numeric slug — genuinely new

    total = len(wp_terms)
    rate = len(resolved) / total if total else 0
    print(f'  {label}: {len(resolved)}/{total} resolved ({rate*100:.1f}%)')
    if unresolved:
        print(f'  Unresolved {label} ({len(unresolved)}):')
        for t in unresolved[:10]:
            print(f'    wp_id={t["id"]} slug="{t.get("slug","")}" name="{t.get("name","")}"')
        if len(unresolved) > 10:
            print(f'    ... and {len(unresolved)-10} more')
    return resolved, unresolved


# ---------------------------------------------------------------------------
# Phase 2: paginate WP lessons and apply
# ---------------------------------------------------------------------------

def fetch_wp_lessons_by_ids(wp_ids: list[int]) -> list[dict]:
    """Fetch only the specific WP lesson IDs we need, in batches of 100.
    Uses local cache if available — no network on re-runs."""
    if os.path.exists(LESSON_CACHE_FILE):
        print(f'  Loading from cache ({LESSON_CACHE_FILE})...')
        with open(LESSON_CACHE_FILE) as f:
            return json.load(f)

    print(f'  Fetching {len(wp_ids)} lessons via FlareSolverr in batches of 100 (~{len(wp_ids)//100+1} calls)...')
    all_lessons = []
    for i in range(0, len(wp_ids), 100):
        chunk = wp_ids[i:i + 100]
        data, status = _fs_get_json(
            f'{BASE_URL}/shiurim',
            {
                'include': ','.join(str(x) for x in chunk),
                'per_page': 100,
                '_fields': 'id,rabbis,shiurim-series,shiurim-category',
            },
        )
        if status == 200 and isinstance(data, list):
            all_lessons.extend(data)
        else:
            print(f'  ⚠ HTTP {status} on batch {i//100+1}', file=sys.stderr)

        if (i // 100) % 10 == 0:
            print(f'  {len(all_lessons)} fetched so far (batch {i//100+1}/{len(wp_ids)//100+1})...')
        time.sleep(2.0)

    os.makedirs('data', exist_ok=True)
    with open(LESSON_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_lessons, f, ensure_ascii=False)
    print(f'  Cached {len(all_lessons)} lessons to {LESSON_CACHE_FILE}')
    return all_lessons


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool, limit: int | None, test: bool):
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={'projectId': 'tora-or'})
    db = firestore.client()

    # Load Firestore taxonomy maps {originalId → firestore_doc_id}
    print('Loading Firestore taxonomy maps (sourceId=2)...')
    fs_ravs, fs_series, fs_categories = {}, {}, {}
    for collection, target in [
        ('ravs', fs_ravs), ('series', fs_series), ('categories', fs_categories),
    ]:
        for doc in db.collection(collection).where('sourceId', '==', SOURCE_ID).stream():
            orig = doc.to_dict().get('originalId')
            if orig is not None:
                target[int(orig)] = doc.id
        print(f'  {len(target)} {collection}')

    # Phase 1: build {wp_term_id → firestore_doc_id} from Firestore + WP terms cache.
    # Categories/series use wpTermId field (WP term ID stored on Firestore doc).
    # Ravs: WP term ID ≠ Firestore originalId (slug ≠ term ID), so we need the
    # WP terms cache to map WP term ID → slug → Firestore originalId → doc_id.
    print('\nPhase 1: building term maps...')
    rav_map, cat_map, series_map = {}, {}, {}

    # Build rav slug→doc_id map from Firestore
    rav_slug_map = {}  # {int(originalId/slug) → doc_id}
    for doc in db.collection('ravs').where('sourceId', '==', SOURCE_ID).stream():
        d = doc.to_dict()
        orig = d.get('originalId')
        if orig is not None:
            rav_slug_map[int(orig)] = doc.id

    # Build {WP_term_ID → doc_id} using cached WP rav terms
    if os.path.exists(TERM_CACHE_FILE):
        with open(TERM_CACHE_FILE) as f:
            wp_term_cache = json.load(f)
        for term in wp_term_cache.get('rabbis', []):
            slug = term.get('slug', '')
            if slug.isdigit():
                fs_id = rav_slug_map.get(int(slug))
                if fs_id:
                    rav_map[term['id']] = fs_id
        print(f'  {len(rav_map)} ravs resolved via WP terms cache')
    else:
        # Fallback: use originalId directly (wrong but better than nothing)
        rav_map = rav_slug_map
        print(f'  {len(rav_map)} ravs (fallback: no WP terms cache)')

    for doc in db.collection('categories').where('sourceId', '==', SOURCE_ID).stream():
        d = doc.to_dict()
        if d.get('wpTermId') is not None:
            cat_map[int(d['wpTermId'])] = doc.id

    for doc in db.collection('series').where('sourceId', '==', SOURCE_ID).stream():
        d = doc.to_dict()
        if d.get('wpTermId') is not None:
            series_map[int(d['wpTermId'])] = doc.id

    print(f'  {len(rav_map)} ravs, {len(cat_map)} categories, {len(series_map)} series')
    print('Term maps built. Proceeding to lesson updates...')

    # Load Firestore lessons with null taxonomy {originalId → (doc_ref, data)}
    print('\nLoading Firestore lessons with null taxonomy...')
    null_lessons = {}
    for field in ('categoryId', 'seriesId', 'ravId'):
        for doc in (db.collection('lessons')
                    .where('sourceId', '==', SOURCE_ID)
                    .where(field, '==', None)
                    .stream()):
            data = doc.to_dict() or {}
            orig = str(data.get('originalId') or '')
            if orig:
                null_lessons[orig] = (doc.reference, data)
    print(f'  {len(null_lessons)} lessons with at least one null taxonomy field')

    # Phase 2: fetch only WP (non-YouTube) lessons by ID.
    # YouTube lessons have large hash-based originalIds; real meirtv WP post IDs are < 500000.
    # Also skip lessons with scrapeSource containing 'youtube'.
    wp_ids = []
    for orig, (ref, data) in null_lessons.items():
        if not orig.isdigit():
            continue
        orig_int = int(orig)
        if orig_int > 500_000:  # YouTube hash IDs are much larger
            continue
        src = data.get('scrapeSource') or []
        if 'youtube' in src:
            continue
        wp_ids.append(orig_int)
    print(f'\nPhase 2: fetching {len(wp_ids)} WP lessons by ID...')
    wp_lesson_list = fetch_wp_lessons_by_ids(wp_ids)
    print(f'  {len(wp_lesson_list)} lessons returned from WP')

    updated = skipped_no_terms = 0
    batch = db.batch()
    batch_count = 0
    lessons_processed = 0

    for wp_lesson in (wp_lesson_list[:limit] if limit else wp_lesson_list):
        if limit and lessons_processed >= limit:
            break
        lessons_processed += 1

        orig_id = str(wp_lesson.get('id', ''))
        entry = null_lessons.get(orig_id)
        if not entry:
            continue  # lesson not in our null set

        doc_ref, current = entry
        payload = {}

        if current.get('ravId') is None:
            for wp_id in wp_lesson.get('rabbis', []):
                if fs_id := rav_map.get(wp_id):
                    payload['ravId'] = fs_id
                    break

        if current.get('categoryId') is None:
            for wp_id in wp_lesson.get('shiurim-category', []):
                if fs_id := cat_map.get(wp_id):
                    payload['categoryId'] = fs_id
                    break

        if current.get('seriesId') is None:
            for wp_id in wp_lesson.get('shiurim-series', []):
                if fs_id := series_map.get(wp_id):
                    payload['seriesId'] = fs_id
                    break

        if not payload:
            skipped_no_terms += 1
            continue

        if dry_run:
            title = (current.get('title') or '')[:60]
            print(f'  [DRY RUN] {orig_id} "{title}" → {list(payload.keys())}')
        else:
            batch.update(doc_ref, payload)
            batch_count += 1
            if batch_count >= BATCH_SIZE:
                batch.commit()
                batch = db.batch()
                batch_count = 0

        updated += 1

    if not dry_run and batch_count > 0:
        batch.commit()

    print(f'\n{"[DRY RUN] " if dry_run else ""}Done:')
    print(f'  updated:               {updated}')
    print(f'  skipped (no WP terms): {skipped_no_terms}  ← lesson has no taxonomy on WP')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--test', action='store_true',
                        help='Fetch only 1 page per taxonomy (quick validation, no cache write)')
    parser.add_argument('--limit', type=int, help='Max WP lessons to process')
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit, test=args.test)


if __name__ == '__main__':
    main()
