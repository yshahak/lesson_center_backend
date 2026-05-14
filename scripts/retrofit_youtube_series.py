#!/usr/bin/env python3
"""
Retrofit YouTube lesson series IDs from "כללי" to their actual playlist.

Run once per channel until all 18 channels are done. Progress is saved to
data/retrofit_checkpoint.json so you can interrupt and resume safely.

Usage:
    cd lesson_center_backend
    python scripts/retrofit_youtube_series.py               # all pending channels
    python scripts/retrofit_youtube_series.py --source 63   # single channel
    python scripts/retrofit_youtube_series.py --dry-run     # preview, no writes
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import firebase_admin
from firebase_admin import firestore
import googleapiclient.discovery

# Allow importing from functions/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))
from utils.firestore_helper import get_hash_for_id, get_hash_for_string

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

CHECKPOINT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'retrofit_checkpoint.json')
FIRESTORE_BATCH_SIZE = 400  # stay well under 500 limit

CHANNELS = [
    {"source_id": 50, "channel_id": "UCeDrtyuUbMLB_z6razI33dQ"},
    {"source_id": 51, "channel_id": "UCBN2YMjFoJHX1qlpEcra29w"},
    {"source_id": 52, "channel_id": "UCMSm6HR03oQ7HfgOhtumEhQ"},
    {"source_id": 60, "channel_id": "UCS6OvEopzPGEEwYbAG4ismA"},
    {"source_id": 61, "channel_id": "UCAcP4Dx-c66fPD5fYcYF0PQ"},
    {"source_id": 62, "channel_id": "UCjswceInZ37d8RIjHDz5ifw"},
    {"source_id": 63, "channel_id": "UCpEUk0Kpt07ms4zHWFsXxhg"},
    {"source_id": 64, "channel_id": "UCkwxRNj-7Iu1LlHJfKzl2Gw"},
    {"source_id": 65, "channel_id": "UC1BIlJW-jVw_EUnj0p-LIgQ"},
    {"source_id": 66, "channel_id": "UCp_YIYD7Ol3DXp6iR8A0ppg"},
    {"source_id": 67, "channel_id": "UC1UJunP8IpS4xfCRtB2HrPQ"},
    {"source_id": 68, "channel_id": "UCLUz-ovexcSqyW1xjShqZ7A"},
    {"source_id": 69, "channel_id": "UC3Kr93MBtpTJ0T-SIT7YM1g"},
    {"source_id": 70, "channel_id": "UC5WgSWUKh-I_G-rDCYanTsg"},
    {"source_id": 71, "channel_id": "UCE5C5A71vpM0INCP7IJ53hg"},
    {"source_id": 72, "channel_id": "UCoLW4u9Mj9XIMNOlIn2ICKg"},
    {"source_id": 73, "channel_id": "UCLlBotitx4zAGffm_Wdh7Bg"},
    {"source_id": 74, "channel_id": "UCewVpZ62BD241aNxjIMX_Yw"},
]


# ── Checkpoint ────────────────────────────────────────────────────────────────

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {}


def save_checkpoint(checkpoint):
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(checkpoint, f, indent=2)


# ── URL helpers ───────────────────────────────────────────────────────────────

def extract_video_id(video_url):
    """Extract YouTube video ID from a watch URL. Returns None for non-YouTube URLs."""
    if not video_url or 'youtube.com' not in video_url:
        return None
    params = parse_qs(urlparse(video_url).query)
    ids = params.get('v', [])
    return ids[0] if ids else None


# ── Playlist fetching ─────────────────────────────────────────────────────────

def get_uploads_playlist_id(youtube_client, channel_id):
    """Return the auto-generated uploads playlist ID for a channel."""
    resp = youtube_client.channels().list(
        part="contentDetails", id=channel_id
    ).execute()
    items = resp.get('items', [])
    if not items:
        return None
    return items[0]['contentDetails']['relatedPlaylists']['uploads']


def get_or_create_series_doc(db, source_id, playlist_id, playlist_title):
    """Deterministic series doc creation — same logic as scraper."""
    original_playlist_id = int(str(get_hash_for_string(playlist_id))[:8])
    numeric_series_id = get_hash_for_id(source_id, original_playlist_id)
    series_doc_id = f"ser_{str(numeric_series_id)[:16]}"
    ref = db.collection('series').document(series_doc_id)
    if not ref.get().exists:
        ref.set({
            'id': numeric_series_id,
            'originalId': original_playlist_id,
            'sourceId': source_id,
            'serie': playlist_title[:80],
            'totalCount': 0,
            'createdAt': datetime.now().isoformat(),
            'updatedAt': datetime.now().isoformat(),
        })
        logger.info(f"  📂 Created series doc: {playlist_title} → {series_doc_id}")
    return series_doc_id


def build_playlist_map(youtube_client, db, channel_id, source_id, uploads_playlist_id):
    """
    Returns {youtube_video_id: series_doc_id} for all videos in named playlists.
    Excludes the auto-generated uploads playlist (UU-prefix or exact ID match).
    """
    playlist_map = {}
    page_token = None

    while True:
        kwargs = dict(part="snippet", channelId=channel_id, maxResults=50)
        if page_token:
            kwargs['pageToken'] = page_token
        resp = youtube_client.playlists().list(**kwargs).execute()

        for pl in resp.get('items', []):
            pl_id = pl['id']
            pl_title = pl['snippet']['title']

            if pl_id == uploads_playlist_id or pl_id.startswith('UU'):
                continue  # skip auto-generated uploads playlist

            series_doc_id = get_or_create_series_doc(db, source_id, pl_id, pl_title)

            # Fetch all video IDs in this playlist
            items_token = None
            while True:
                iresp = youtube_client.playlistItems().list(
                    part="snippet", playlistId=pl_id, maxResults=50,
                    **({"pageToken": items_token} if items_token else {})
                ).execute()
                for item in iresp.get('items', []):
                    vid = item['snippet']['resourceId']['videoId']
                    playlist_map[vid] = series_doc_id  # last playlist wins
                items_token = iresp.get('nextPageToken')
                if not items_token:
                    break

        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    logger.info(f"  📋 Playlist map: {len(playlist_map)} video→series entries")
    return playlist_map


# ── Retrofit logic ────────────────────────────────────────────────────────────

def retrofit_channel(db, youtube_client, source_id, channel_id, dry_run=False):
    """
    Retrofit all lessons for one channel: assign seriesId from playlist map.
    Returns dict with stats.
    """
    logger.info(f"🔄 Retrofitting source {source_id} (channel {channel_id})")

    uploads_playlist_id = get_uploads_playlist_id(youtube_client, channel_id)
    if not uploads_playlist_id:
        logger.warning(f"  ⚠️ Channel {channel_id} not found — skipping")
        return {'updated': 0, 'skipped': 0, 'no_playlist': 0, 'errors': 0}

    # Build כללי fallback series (same doc the scraper uses)
    כללי_doc_id = get_or_create_series_doc(db, source_id, uploads_playlist_id, "כללי")

    playlist_map = build_playlist_map(youtube_client, db, channel_id, source_id, uploads_playlist_id)

    # Paginate through all lessons for this source
    stats = {'updated': 0, 'skipped': 0, 'no_playlist': 0, 'errors': 0}
    series_lesson_counts = defaultdict(int)  # track actual count per series for totalCount update
    batch = db.batch()
    batch_count = 0
    last_doc = None

    while True:
        query = db.collection('lessons').where('sourceId', '==', source_id).limit(500)
        if last_doc:
            query = query.start_after(last_doc)
        docs = list(query.stream())
        if not docs:
            break
        last_doc = docs[-1]

        for doc in docs:
            try:
                data = doc.to_dict()
                video_url = data.get('videoUrl', '')
                video_id = extract_video_id(video_url)

                if not video_id:
                    stats['no_playlist'] += 1
                    continue

                target_series_id = playlist_map.get(video_id, כללי_doc_id)
                current_series_id = data.get('seriesId')

                # Always count toward series total regardless of whether update needed
                series_lesson_counts[target_series_id] += 1

                if current_series_id == target_series_id:
                    stats['skipped'] += 1
                    continue

                if not dry_run:
                    batch.update(doc.reference, {
                        'seriesId': target_series_id,
                        'updatedAt': datetime.now().isoformat(),
                    })
                    batch_count += 1
                    if batch_count >= FIRESTORE_BATCH_SIZE:
                        batch.commit()
                        batch = db.batch()
                        batch_count = 0

                stats['updated'] += 1

            except Exception as e:
                logger.error(f"  ❌ Error on doc {doc.id}: {e}")
                stats['errors'] += 1

        if len(docs) < 500:
            break

    if not dry_run and batch_count > 0:
        batch.commit()

    # Update totalCount on every series that has lessons for this source.
    # This is critical: the retrofit moves lessons between series but the
    # series docs' totalCount fields are stale (0 for new playlist series,
    # inflated for the old כללי series).
    # Using individual updates (not batch) — at most ~50 series per channel.
    if not dry_run and series_lesson_counts:
        series_ref = db.collection('series')
        for series_doc_id, count in series_lesson_counts.items():
            series_ref.document(series_doc_id).update({
                'totalCount': count,
                'updatedAt': datetime.now().isoformat(),
            })
        logger.info(f"  📊 Updated totalCount on {len(series_lesson_counts)} series docs")

    prefix = "[DRY RUN] " if dry_run else ""
    logger.info(f"  {prefix}✅ source {source_id}: updated={stats['updated']} "
                f"skipped={stats['skipped']} no_playlist={stats['no_playlist']} errors={stats['errors']}")
    return stats


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Retrofit YouTube lesson series IDs from playlist membership')
    parser.add_argument('--source', type=int, help='Only retrofit this source ID')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes, no writes')
    parser.add_argument('--reset', action='store_true', help='Clear checkpoint and reprocess all')
    args = parser.parse_args()

    # Init Firebase
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={'projectId': 'tora-or'})
    db = firestore.client()

    # Init YouTube API
    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        logger.error("YOUTUBE_API_KEY environment variable not set")
        sys.exit(1)
    youtube_client = googleapiclient.discovery.build('youtube', 'v3', developerKey=api_key)

    checkpoint = {} if args.reset else load_checkpoint()

    channels = CHANNELS
    if args.source:
        channels = [c for c in CHANNELS if c['source_id'] == args.source]
        if not channels:
            logger.error(f"Unknown source_id {args.source}")
            sys.exit(1)

    total_stats = {'updated': 0, 'skipped': 0, 'no_playlist': 0, 'errors': 0}

    for ch in channels:
        sid = ch['source_id']
        if str(sid) in checkpoint and checkpoint[str(sid)].get('done') and not args.dry_run:
            logger.info(f"⏭️  source {sid} already done — skipping (use --reset to reprocess)")
            continue

        stats = retrofit_channel(db, youtube_client, sid, ch['channel_id'], dry_run=args.dry_run)

        for k in total_stats:
            total_stats[k] += stats.get(k, 0)

        if not args.dry_run:
            checkpoint[str(sid)] = {
                'done': True,
                'completedAt': datetime.now().isoformat(),
                **stats,
            }
            save_checkpoint(checkpoint)

    logger.info(f"\n🎯 Retrofit complete: {total_stats}")
    if args.dry_run:
        logger.info("(dry run — no changes written)")


if __name__ == '__main__':
    main()
