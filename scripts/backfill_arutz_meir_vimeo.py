#!/usr/bin/env python3
"""
Backfill vimeoId (and siteAudioUrl where missing) for Arutz Meir lessons.
Uses FlareSolverr to bypass Cloudflare managed challenge on meirtv.com.

Prerequisites:
    docker run -d --name flaresolverr -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest

Only processes lessons where:
  - sourceId = 2
  - vimeoId is null
  - siteAudioUrl is set (page was reachable during original scrape)

Resumable via /tmp/backfill_vimeo_cursor.json — safe to stop and restart.

Usage:
    cd lesson_center_backend/functions
    python ../scripts/backfill_arutz_meir_vimeo.py                    # resume
    python ../scripts/backfill_arutz_meir_vimeo.py --reset             # start over
    python ../scripts/backfill_arutz_meir_vimeo.py --dry-run           # no writes
    python ../scripts/backfill_arutz_meir_vimeo.py --flaresolverr-port 8192

Detached run (recommended):
    nohup python ../scripts/backfill_arutz_meir_vimeo.py --reset > /tmp/backfill_vimeo.log 2>&1 &
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../functions')
import firebase_admin
from firebase_admin import firestore

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', force=True)
logger = logging.getLogger(__name__)

CURSOR_FILE = '/tmp/backfill_vimeo_cursor.json'
BATCH_SIZE = 100
VIMEO_RE = re.compile(r'player\.vimeo\.com/video/(\d+)')
AUDIO_RE = re.compile(r'src=["\']([^"\']*mp3\.meirtv\.co\.il[^"\']+)["\']')
SITE_DOWN_THRESHOLD = 5
FLARESOLVERR_SESSION = 'meirtv_backfill'


# ---------------------------------------------------------------------------
# FlareSolverr client
# ---------------------------------------------------------------------------

def fs_get(url: str, port: int, timeout_ms: int = 60000) -> tuple[str | None, int]:
    """
    Fetch a URL via FlareSolverr. Returns (html_content, status_code).
    Returns (None, 0) on FlareSolverr connection failure.
    """
    try:
        resp = requests.post(
            f'http://localhost:{port}/v1',
            json={
                'cmd': 'request.get',
                'url': url,
                'session': FLARESOLVERR_SESSION,
                'maxTimeout': timeout_ms,
            },
            timeout=timeout_ms / 1000 + 10,
        )
        data = resp.json()
        solution = data.get('solution', {})
        status = solution.get('status', 0)
        html = solution.get('response', '')
        return html, status
    except Exception as e:
        logger.error(f'  FlareSolverr error: {e}')
        return None, 0


def fs_create_session(port: int):
    """Create a persistent FlareSolverr session (reuses CF cookies)."""
    try:
        r = requests.post(
            f'http://localhost:{port}/v1',
            json={'cmd': 'sessions.create', 'session': FLARESOLVERR_SESSION},
            timeout=30,
        )
        result = r.json()
        logger.info(f'FlareSolverr session: {result.get("message", result)}')
    except Exception as e:
        logger.warning(f'Could not create FlareSolverr session (may already exist): {e}')


def check_flaresolverr(port: int) -> bool:
    """Verify FlareSolverr is running."""
    try:
        r = requests.get(f'http://localhost:{port}/', timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def extract_from_html(html: str) -> tuple[str | None, str | None]:
    """Return (vimeo_id, site_audio_url) from lesson page HTML."""
    vimeo = VIMEO_RE.search(html)
    audio = AUDIO_RE.search(html)
    return (vimeo.group(1) if vimeo else None,
            audio.group(1) if audio else None)


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------

def load_cursor() -> dict:
    if os.path.exists(CURSOR_FILE):
        with open(CURSOR_FILE) as f:
            return json.load(f)
    return {'last_doc_id': None, 'processed': 0, 'updated': 0,
            'skipped': 0, 'errors': 0, 'started_at': datetime.now().isoformat()}


def save_cursor(cursor: dict):
    with open(CURSOR_FILE, 'w') as f:
        json.dump(cursor, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--reset', action='store_true', help='Clear cursor and start from scratch')
    parser.add_argument('--flaresolverr-port', type=int, default=8191)
    args = parser.parse_args()

    # ── preflight checks ──────────────────────────────────────────────────
    logger.info('=' * 60)
    logger.info('Arutz Meir vimeoId backfill — FlareSolverr edition')
    logger.info(f'  FlareSolverr port : {args.flaresolverr_port}')
    logger.info(f'  Dry run           : {args.dry_run}')
    logger.info(f'  Reset cursor      : {args.reset}')
    logger.info('=' * 60)

    if not check_flaresolverr(args.flaresolverr_port):
        logger.error(
            f'FlareSolverr is NOT running on port {args.flaresolverr_port}.\n'
            f'Start it with:\n'
            f'  docker run -d --name flaresolverr -p {args.flaresolverr_port}:8191 '
            f'ghcr.io/flaresolverr/flaresolverr:latest'
        )
        sys.exit(1)
    logger.info(f'✅ FlareSolverr is running on port {args.flaresolverr_port}')

    # Warm-up session (reuses CF cookie across requests)
    fs_create_session(args.flaresolverr_port)

    # ── cursor ────────────────────────────────────────────────────────────
    if args.reset and os.path.exists(CURSOR_FILE):
        os.remove(CURSOR_FILE)
        logger.info('Cursor reset — will process all lessons from the start.')

    cursor = load_cursor()
    logger.info(
        f'Resuming from: processed={cursor["processed"]} '
        f'updated={cursor["updated"]} last_doc={cursor["last_doc_id"]}'
    )

    # ── Firebase ──────────────────────────────────────────────────────────
    try: firebase_admin.get_app()
    except ValueError: firebase_admin.initialize_app(options={'projectId': 'tora-or'})
    db = firestore.client()

    # ── count total work ──────────────────────────────────────────────────
    total_to_process_result = (
        db.collection('lessons')
        .where('sourceId', '==', 2)
        .where('vimeoId', '==', None)
        .where('siteAudioUrl', '>', '')
        .count().get()
    )
    total_to_process = int(total_to_process_result[0][0].value)
    logger.info(f'Total lessons needing vimeoId: {total_to_process:,}')

    # ── main loop ─────────────────────────────────────────────────────────
    total_updated = cursor['updated']
    total_skipped = cursor['skipped']
    total_errors  = cursor.get('errors', 0)
    total_processed = cursor['processed']
    consecutive_failures = 0
    run_start = time.time()
    batch_num = 0

    while True:
        query = (
            db.collection('lessons')
            .where('sourceId', '==', 2)
            .where('vimeoId', '==', None)
            .where('siteAudioUrl', '>', '')
            .limit(BATCH_SIZE)
        )
        if cursor['last_doc_id']:
            snap = db.collection('lessons').document(cursor['last_doc_id']).get()
            if snap.exists:
                query = query.start_after(snap)

        docs = list(query.stream())
        if not docs:
            logger.info('✅ No more lessons to process. Backfill complete!')
            break

        batch_num += 1
        batch_updated = batch_skipped = batch_errors = 0
        pending_writes = []

        logger.info(
            f'--- Batch {batch_num} | {len(docs)} lessons | '
            f'total so far: processed={total_processed} updated={total_updated} '
            f'skipped={total_skipped} errors={total_errors} ---'
        )

        for doc in docs:
            data = doc.to_dict()
            orig_id = data['originalId']
            total_processed += 1

            # Try shiur-{id} slug first, then bare id
            vimeo_id = site_audio_url = None
            fetch_status = 'not_tried'

            for url in [
                f'https://meirtv.com/shiurim/shiur-{orig_id}/',
                f'https://meirtv.com/shiurim/{orig_id}/',
            ]:
                html, status_code = fs_get(url, args.flaresolverr_port)
                fetch_status = str(status_code)

                if status_code == 200 and html:
                    # FlareSolverr returns HTTP 200 even for WordPress 404 pages
                    # (Cloudflare passes them through). Detect WP 404 body class
                    # and fall through to try the next URL slug.
                    if 'error404' in html:
                        logger.debug(f'  WP-404 on {url}, trying next slug')
                        continue
                    vimeo_id, site_audio_url = extract_from_html(html)
                    consecutive_failures = 0
                    break
                elif status_code == 404:
                    consecutive_failures = 0
                    break
                else:
                    consecutive_failures += 1

            # ── log per-lesson outcome ─────────────────────────────────
            if fetch_status == '200':
                if vimeo_id or site_audio_url:
                    logger.info(
                        f'  ✓ orig={orig_id} | vimeoId={vimeo_id} | '
                        f'audio={"yes" if site_audio_url else "no"} | http=200'
                    )
                else:
                    logger.info(f'  NO_MEDIA orig={orig_id} | page ok but no vimeo/audio found')
                    batch_skipped += 1
                    total_skipped += 1
            elif fetch_status == '404':
                logger.info(f'  404 orig={orig_id} | page not found (old lesson removed from site)')
                batch_skipped += 1
                total_skipped += 1
            else:
                logger.warning(
                    f'  FAIL orig={orig_id} | http={fetch_status} | '
                    f'consecutive_failures={consecutive_failures}'
                )
                if consecutive_failures >= SITE_DOWN_THRESHOLD:
                    logger.error(
                        f'⚠️  {consecutive_failures} consecutive failures — '
                        f'site may be down or FlareSolverr session expired. '
                        f'Consider restarting FlareSolverr.'
                    )
                batch_errors += 1
                total_errors += 1
                continue

            # ── queue Firestore write ──────────────────────────────────
            if vimeo_id or (site_audio_url and not data.get('siteAudioUrl')):
                update = {'updatedAt': datetime.now().isoformat()}
                if vimeo_id:
                    update['vimeoId'] = vimeo_id
                if site_audio_url and not data.get('siteAudioUrl'):
                    update['siteAudioUrl'] = site_audio_url
                pending_writes.append((doc.reference, update))
                batch_updated += 1
                total_updated += 1

        # ── batch Firestore commit ─────────────────────────────────────
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
                        logger.error(f'Firestore batch commit failed: {e}')
                    else:
                        time.sleep(2 ** attempt)

        # ── save cursor + progress report ──────────────────────────────
        cursor['last_doc_id'] = docs[-1].id
        cursor['processed']   = total_processed
        cursor['updated']     = total_updated
        cursor['skipped']     = total_skipped
        cursor['errors']      = total_errors
        save_cursor(cursor)

        elapsed = time.time() - run_start
        rate_per_min = (total_processed / elapsed * 60) if elapsed > 0 else 0
        remaining = total_to_process - total_processed
        eta_hours = (remaining / rate_per_min / 60) if rate_per_min > 0 else float('inf')
        eta_str = str(timedelta(hours=eta_hours)).split('.')[0] if eta_hours != float('inf') else '?'

        prefix = '[DRY RUN] ' if args.dry_run else ''
        logger.info(
            f'{prefix}=== Batch {batch_num} summary: '
            f'+{batch_updated} updated, {batch_skipped} skipped, {batch_errors} errors | '
            f'TOTAL: processed={total_processed:,}/{total_to_process:,} '
            f'updated={total_updated:,} skipped={total_skipped:,} errors={total_errors:,} | '
            f'rate={rate_per_min:.0f}/min | ETA={eta_str} ==='
        )


if __name__ == '__main__':
    main()
