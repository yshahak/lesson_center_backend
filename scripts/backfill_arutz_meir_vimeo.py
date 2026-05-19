#!/usr/bin/env python3
"""
Backfill vimeoId (and siteAudioUrl where missing) for Arutz Meir lessons.

Only processes lessons where:
  - sourceId = 2
  - vimeoId is null
  - siteAudioUrl is set (page was reachable during original scrape)

Resumable: tracks last processed Firestore doc cursor in /tmp/backfill_vimeo_cursor.json
Safe to stop and restart — will skip already-updated lessons.

Usage:
    cd lesson_center_backend/functions
    python ../scripts/backfill_arutz_meir_vimeo.py
    python ../scripts/backfill_arutz_meir_vimeo.py --dry-run
    python ../scripts/backfill_arutz_meir_vimeo.py --workers 1 --delay 1.0
    python ../scripts/backfill_arutz_meir_vimeo.py --reset   # clear cursor, start over
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../functions')
import firebase_admin
from firebase_admin import firestore

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

CURSOR_FILE = '/tmp/backfill_vimeo_cursor.json'
BATCH_SIZE = 200
VIMEO_RE = re.compile(r'player\.vimeo\.com/video/(\d+)')
AUDIO_RE = re.compile(r'src=["\']([^"\']*mp3\.meirtv\.co\.il[^"\']+)["\']')

# Site-down detection: warn if this many consecutive fetches all fail
SITE_DOWN_THRESHOLD = 10


def make_session():
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    return s


def fetch_vimeo_and_audio(session, original_id):
    """
    Fetch lesson page, return (vimeo_id, site_audio_url, status) where
    status is 'ok', '404', or 'error'.
    """
    for url in [f'https://meirtv.com/shiurim/shiur-{original_id}/',
                f'https://meirtv.com/shiurim/{original_id}/']:
        try:
            r = session.get(url, timeout=10)
            if r.status_code == 200:
                vimeo = VIMEO_RE.search(r.text)
                audio = AUDIO_RE.search(r.text)
                return (vimeo.group(1) if vimeo else None,
                        audio.group(1) if audio else None,
                        'ok')
            elif r.status_code == 404:
                return None, None, '404'
        except Exception as e:
            return None, None, f'error:{str(e)[:60]}'
    return None, None, '404'


def load_cursor():
    if os.path.exists(CURSOR_FILE):
        with open(CURSOR_FILE) as f:
            return json.load(f)
    return {'last_doc_id': None, 'processed': 0, 'updated': 0, 'skipped': 0, 'errors': 0}


def save_cursor(cursor):
    with open(CURSOR_FILE, 'w') as f:
        json.dump(cursor, f, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--delay', type=float, default=1.0,
                        help='Seconds between HTML fetches (default 1.0 — polite to meirtv.com)')
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    if args.reset and os.path.exists(CURSOR_FILE):
        os.remove(CURSOR_FILE)
        logger.info('Cursor reset.')

    try: firebase_admin.get_app()
    except ValueError: firebase_admin.initialize_app(options={'projectId': 'tora-or'})
    db = firestore.client()

    cursor = load_cursor()
    session = make_session()

    logger.info(f'Starting backfill. workers={args.workers} delay={args.delay}s')
    logger.info(f'Cursor: processed={cursor["processed"]} updated={cursor["updated"]} last_doc={cursor["last_doc_id"]}')

    total_updated = cursor['updated']
    total_skipped = cursor['skipped']
    total_errors = cursor.get('errors', 0)
    total_processed = cursor['processed']
    consecutive_failures = 0
    start_time = time.time()
    batch_num = 0

    while True:
        query = (db.collection('lessons')
                 .where('sourceId', '==', 2)
                 .where('vimeoId', '==', None)
                 .where('siteAudioUrl', '>', '')
                 .limit(BATCH_SIZE))

        if cursor['last_doc_id']:
            last_doc = db.collection('lessons').document(cursor['last_doc_id']).get()
            if last_doc.exists:
                query = query.start_after(last_doc)

        docs = list(query.stream())
        if not docs:
            logger.info('✅ No more lessons to process. Done!')
            break

        batch_num += 1
        batch_updated = 0
        batch_skipped = 0
        batch_errors = 0
        pending_writes = []

        def process(doc):
            data = doc.to_dict()
            orig_id = data['originalId']
            vimeo_id, site_audio_url, status = fetch_vimeo_and_audio(session, orig_id)
            if args.delay > 0:
                time.sleep(args.delay)
            return doc, orig_id, vimeo_id, site_audio_url, status

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(process, doc): doc for doc in docs}
            for future in as_completed(futures):
                doc, orig_id, vimeo_id, site_audio_url, status = future.result()
                total_processed += 1

                if status.startswith('error'):
                    consecutive_failures += 1
                    batch_errors += 1
                    total_errors += 1
                    logger.warning(f'  FETCH FAIL orig={orig_id} [{status}] consecutive_failures={consecutive_failures}')
                    if consecutive_failures >= SITE_DOWN_THRESHOLD:
                        logger.error(f'⚠️  SITE MAY BE DOWN — {consecutive_failures} consecutive fetch failures. Consider stopping.')
                    continue
                else:
                    consecutive_failures = 0

                if status == '404':
                    batch_skipped += 1
                    total_skipped += 1
                    logger.debug(f'  404 orig={orig_id}')
                    continue

                # status == 'ok'
                if not vimeo_id and not site_audio_url:
                    batch_skipped += 1
                    total_skipped += 1
                    logger.info(f'  NO MEDIA orig={orig_id} (page ok, no vimeo/audio found)')
                    continue

                update = {'updatedAt': datetime.now().isoformat()}
                if vimeo_id:
                    update['vimeoId'] = vimeo_id
                if site_audio_url and not doc.to_dict().get('siteAudioUrl'):
                    update['siteAudioUrl'] = site_audio_url

                pending_writes.append((doc.reference, update))
                batch_updated += 1
                total_updated += 1
                logger.info(f'  ✓ orig={orig_id} vimeoId={vimeo_id} audio={"yes" if site_audio_url else "no"}')

        if not args.dry_run and pending_writes:
            fb_batch = db.batch()
            for ref, upd in pending_writes:
                fb_batch.update(ref, upd)
            for attempt in range(3):
                try:
                    fb_batch.commit()
                    break
                except Exception as e:
                    if attempt == 2:
                        logger.error(f'Batch commit failed after 3 attempts: {e}')
                    else:
                        time.sleep(2 ** attempt)

        cursor['last_doc_id'] = docs[-1].id
        cursor['processed'] = total_processed
        cursor['updated'] = total_updated
        cursor['skipped'] = total_skipped
        cursor['errors'] = total_errors
        save_cursor(cursor)

        elapsed = time.time() - start_time
        rate = total_processed / elapsed * 60 if elapsed > 0 else 0
        prefix = '[DRY RUN] ' if args.dry_run else ''
        logger.info(
            f'{prefix}Batch {batch_num} done | '
            f'batch: +{batch_updated} updated, {batch_skipped} skipped, {batch_errors} errors | '
            f'total: processed={total_processed} updated={total_updated} skipped={total_skipped} errors={total_errors} | '
            f'rate={rate:.0f}/min'
        )


if __name__ == '__main__':
    main()
