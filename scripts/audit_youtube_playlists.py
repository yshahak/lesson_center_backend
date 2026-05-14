#!/usr/bin/env python3
"""
Weekly audit: compare YouTube playlist video counts vs Firestore lesson counts.

For each of the 18 YouTube channels, fetches every named playlist from the
YouTube API and compares its item count to the number of lessons we actually
have in Firestore for that series. Gaps surface scraper failures, quota
exhaustion, or partial syncs.

Usage:
    cd lesson_center_backend
    YOUTUBE_API_KEY=... python scripts/audit_youtube_playlists.py
    YOUTUBE_API_KEY=... python scripts/audit_youtube_playlists.py --threshold 5   # only flag gaps > 5
    YOUTUBE_API_KEY=... python scripts/audit_youtube_playlists.py --source 63     # single channel
    YOUTUBE_API_KEY=... python scripts/audit_youtube_playlists.py --csv out.csv   # save report

Exit code: 0 if no gaps found, 1 if gaps above threshold exist.
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime

import firebase_admin
from firebase_admin import firestore
import googleapiclient.discovery

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))
from utils.firestore_helper import get_hash_for_id, get_hash_for_string

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CHANNELS = [
    {"source_id": 50, "channel_id": "UCeDrtyuUbMLB_z6razI33dQ", "label": "הסדר חיפה"},
    {"source_id": 51, "channel_id": "UCBN2YMjFoJHX1qlpEcra29w", "label": "ישיבת המאירי"},
    {"source_id": 52, "channel_id": "UCMSm6HR03oQ7HfgOhtumEhQ", "label": "הסדר טפחות"},
    {"source_id": 60, "channel_id": "UCS6OvEopzPGEEwYbAG4ismA", "label": "מעלה אדומים"},
    {"source_id": 61, "channel_id": "UCAcP4Dx-c66fPD5fYcYF0PQ", "label": "ישיבת הכותל"},
    {"source_id": 62, "channel_id": "UCjswceInZ37d8RIjHDz5ifw", "label": "ישיבת ר״ג"},
    {"source_id": 63, "channel_id": "UCpEUk0Kpt07ms4zHWFsXxhg", "label": "ישיבת הר עציון"},
    {"source_id": 64, "channel_id": "UCkwxRNj-7Iu1LlHJfKzl2Gw", "label": "ישיבת הר ברכה"},
    {"source_id": 65, "channel_id": "UC1BIlJW-jVw_EUnj0p-LIgQ", "label": "חב״ד"},
    {"source_id": 66, "channel_id": "UCp_YIYD7Ol3DXp6iR8A0ppg", "label": "הרב אורי שרקי"},
    {"source_id": 67, "channel_id": "UC1UJunP8IpS4xfCRtB2HrPQ", "label": "ישיבת שבי חברון"},
    {"source_id": 68, "channel_id": "UCLUz-ovexcSqyW1xjShqZ7A", "label": "דף יומי"},
    {"source_id": 69, "channel_id": "UC3Kr93MBtpTJ0T-SIT7YM1g", "label": "הרב ראובן ששון"},
    {"source_id": 70, "channel_id": "UC5WgSWUKh-I_G-rDCYanTsg", "label": "הרב אשר וייס"},
    {"source_id": 71, "channel_id": "UCE5C5A71vpM0INCP7IJ53hg", "label": "ישיבת ברוכין"},
    {"source_id": 72, "channel_id": "UCoLW4u9Mj9XIMNOlIn2ICKg", "label": "מכינת עצמונה"},
    {"source_id": 73, "channel_id": "UCLlBotitx4zAGffm_Wdh7Bg", "label": "הרב מאיר אליהו"},
    {"source_id": 74, "channel_id": "UCewVpZ62BD241aNxjIMX_Yw", "label": "ישיבת המקובלים בית אל"},
]


def get_uploads_playlist_id(yt, channel_id):
    resp = yt.channels().list(part="contentDetails", id=channel_id).execute()
    items = resp.get('items', [])
    if not items:
        return None
    return items[0]['contentDetails']['relatedPlaylists']['uploads']


def get_series_doc_id(source_id, playlist_id):
    """Same deterministic ID as the scraper — must stay in sync."""
    original_playlist_id = int(str(get_hash_for_string(playlist_id))[:8])
    numeric_series_id = get_hash_for_id(source_id, original_playlist_id)
    return f"ser_{str(numeric_series_id)[:16]}"


def get_channel_playlists(yt, channel_id, uploads_playlist_id):
    """Return list of {id, title, youtube_count} for all named playlists."""
    playlists = []
    page_token = None
    while True:
        kwargs = dict(part="snippet,contentDetails", channelId=channel_id, maxResults=50)
        if page_token:
            kwargs['pageToken'] = page_token
        resp = yt.playlists().list(**kwargs).execute()
        for pl in resp.get('items', []):
            pl_id = pl['id']
            if pl_id == uploads_playlist_id or pl_id.startswith('UU'):
                continue
            playlists.append({
                'id': pl_id,
                'title': pl['snippet']['title'],
                'youtube_count': pl['contentDetails']['itemCount'],
            })
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return playlists


def get_firestore_count(db, series_doc_id):
    """Count lessons in Firestore for a given series doc ID."""
    result = db.collection('lessons').where('seriesId', '==', series_doc_id).count().get()
    return int(result[0][0].value) if result and result[0] else 0


def audit_channel(db, yt, source_id, channel_id, label, threshold):
    """
    Audit one channel. Returns list of gap dicts, one per playlist with gap > threshold.
    """
    logger.info(f"🔍 Auditing source {source_id} ({label})")

    uploads_id = get_uploads_playlist_id(yt, channel_id)
    if not uploads_id:
        logger.warning(f"  ⚠️ Channel {channel_id} not found — skipping")
        return []

    playlists = get_channel_playlists(yt, channel_id, uploads_id)
    logger.info(f"  📋 {len(playlists)} named playlists")

    gaps = []
    for pl in playlists:
        series_doc_id = get_series_doc_id(source_id, pl['id'])
        firestore_count = get_firestore_count(db, series_doc_id)
        youtube_count = pl['youtube_count']
        gap = youtube_count - firestore_count

        status = "✅" if gap <= threshold else "⚠️"
        logger.info(f"  {status} {pl['title'][:50]}: youtube={youtube_count} firestore={firestore_count} gap={gap}")

        if gap > threshold:
            gaps.append({
                'source_id': source_id,
                'channel': label,
                'playlist_id': pl['id'],
                'playlist_title': pl['title'],
                'series_doc_id': series_doc_id,
                'youtube_count': youtube_count,
                'firestore_count': firestore_count,
                'gap': gap,
            })

    return gaps


def main():
    parser = argparse.ArgumentParser(description='Audit YouTube playlist counts vs Firestore lesson counts')
    parser.add_argument('--source', type=int, help='Only audit this source ID')
    parser.add_argument('--threshold', type=int, default=0,
                        help='Only flag gaps larger than this (default: 0 = flag any gap)')
    parser.add_argument('--csv', metavar='FILE', help='Save full report to CSV file')
    args = parser.parse_args()

    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={'projectId': 'tora-or'})
    db = firestore.client()

    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        logger.error("YOUTUBE_API_KEY not set")
        sys.exit(1)
    yt = googleapiclient.discovery.build('youtube', 'v3', developerKey=api_key)

    channels = CHANNELS
    if args.source:
        channels = [c for c in CHANNELS if c['source_id'] == args.source]
        if not channels:
            logger.error(f"Unknown source_id {args.source}")
            sys.exit(1)

    all_gaps = []
    all_rows = []

    for ch in channels:
        gaps = audit_channel(db, yt, ch['source_id'], ch['channel_id'], ch['label'], args.threshold)
        all_gaps.extend(gaps)

    # Summary
    print(f"\n{'='*60}")
    print(f"AUDIT COMPLETE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Channels audited: {len(channels)}")
    print(f"Playlists with gap > {args.threshold}: {len(all_gaps)}")
    print(f"{'='*60}")

    if all_gaps:
        print(f"\n⚠️  GAPS FOUND:\n")
        for g in sorted(all_gaps, key=lambda x: x['gap'], reverse=True):
            print(f"  [{g['source_id']}] {g['channel']} — {g['playlist_title']}")
            print(f"       YouTube: {g['youtube_count']}  Firestore: {g['firestore_count']}  Gap: {g['gap']}")
            print(f"       series_doc_id: {g['series_doc_id']}")
    else:
        print(f"\n✅ No gaps found — scraper is up to date.")

    if args.csv:
        with open(args.csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'source_id', 'channel', 'playlist_title', 'playlist_id',
                'series_doc_id', 'youtube_count', 'firestore_count', 'gap'
            ])
            writer.writeheader()
            writer.writerows(all_gaps)
        logger.info(f"Report saved to {args.csv}")

    sys.exit(1 if all_gaps else 0)


if __name__ == '__main__':
    main()
