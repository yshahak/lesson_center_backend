#!/usr/bin/env python3
"""
Backfill vimeoId/siteAudioUrl for a specific list of originalIds.
Useful for retrying lessons that errored during the main backfill.

Usage:
    cd lesson_center_backend/functions
    python ../scripts/backfill_specific_lessons.py 37763 37764 37765 37766 37767 37768 37769 37770 37771 37772
    python ../scripts/backfill_specific_lessons.py --dry-run 37763 37764
"""
import argparse
import re
import sys
import os
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../functions')
import firebase_admin
from firebase_admin import firestore

VIMEO_RE = re.compile(r'player\.vimeo\.com/video/(\d+)')
AUDIO_RE = re.compile(r'src=["\']([^"\']*mp3\.meirtv\.co\.il[^"\']+)["\']')
FLARESOLVERR_PORT = 8191
FLARESOLVERR_SESSION = 'meirtv_backfill'


def fs_get(url: str) -> tuple[str | None, int]:
    try:
        resp = requests.post(
            f'http://localhost:{FLARESOLVERR_PORT}/v1',
            json={'cmd': 'request.get', 'url': url, 'session': FLARESOLVERR_SESSION, 'maxTimeout': 60000},
            timeout=70,
        )
        solution = resp.json().get('solution', {})
        return solution.get('response'), solution.get('status', 0)
    except Exception as e:
        return None, 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('orig_ids', nargs='+', type=int)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    try: firebase_admin.get_app()
    except ValueError: firebase_admin.initialize_app(options={'projectId': 'tora-or'})
    db = firestore.client()

    print(f'Processing {len(args.orig_ids)} lessons: {args.orig_ids}')

    updated = skipped = errors = 0
    for orig_id in args.orig_ids:
        # Find the Firestore doc by originalId
        docs = list(db.collection('lessons').where('originalId', '==', orig_id).where('sourceId', '==', 2).limit(1).stream())
        if not docs:
            print(f'  orig={orig_id}: NOT FOUND in Firestore')
            skipped += 1
            continue

        doc = docs[0]
        data = doc.to_dict()

        if data.get('vimeoId'):
            print(f'  orig={orig_id}: already has vimeoId={data["vimeoId"]} — skipping')
            skipped += 1
            continue

        # Fetch page — retry each URL up to 3 times if we get a partial render
        vimeo_id = site_audio_url = None
        status = 0
        for url in [f'https://meirtv.com/shiurim/shiur-{orig_id}/', f'https://meirtv.com/shiurim/{orig_id}/']:
            for attempt in range(3):
                html, status = fs_get(url)
                if status == 200 and html:
                    is_wp404 = bool(re.search(r'<body[^>]+class="[^"]*error404', html))
                    is_partial = len(html) < 250_000
                    if is_wp404:
                        break  # Real WP 404 — try next slug
                    if is_partial:
                        print(f'  orig={orig_id}: partial render {len(html)}B attempt {attempt+1}, retrying...')
                        continue  # Retry same URL
                    m = VIMEO_RE.search(html)
                    a = AUDIO_RE.search(html)
                    vimeo_id = m.group(1) if m else None
                    site_audio_url = a.group(1) if a else None
                    break
                elif status == 404:
                    break
            if vimeo_id or site_audio_url:
                break
            if status == 404:
                break

        if not vimeo_id and not site_audio_url:
            print(f'  orig={orig_id}: http={status} no media found')
            errors += 1
            continue

        update = {'updatedAt': datetime.now().isoformat()}
        if vimeo_id: update['vimeoId'] = vimeo_id
        if site_audio_url and not data.get('siteAudioUrl'): update['siteAudioUrl'] = site_audio_url

        if not args.dry_run:
            doc.reference.update(update)

        print(f'  {"[DRY] " if args.dry_run else ""}✓ orig={orig_id} vimeoId={vimeo_id} audio={"yes" if site_audio_url else "no"}')
        updated += 1

    print(f'\nDone — updated={updated} skipped={skipped} errors={errors}')


if __name__ == '__main__':
    main()
