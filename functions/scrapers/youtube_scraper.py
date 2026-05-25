#!/usr/bin/env python3
"""
YouTube Scraper for Firebase Cloud Functions
Scrapes YouTube channels and writes directly to Firestore
"""

from utils.firestore_helper import (
    FirestoreConnection, add_lesson_to_db, get_hash_for_id,
    get_hash_for_string, get_timestamp, get_iso_duration_in_seconds
)
from datetime import datetime
from collections import defaultdict
from google.cloud.firestore import Increment
import googleapiclient.discovery
import googleapiclient.errors
import logging
import sys
import os

# Inherit root logger config (stdout) set in main.py
logger = logging.getLogger(__name__)

# YouTube API configuration
youtube_base_url = "https://www.youtube.com/watch?v=%s"
# Loaded from YOUTUBE_API_KEY env var, which Cloud Functions injects from Secret Manager.
youtube_api_key = os.environ.get("YOUTUBE_API_KEY")
api_service_name = "youtube"
api_version = "v3"

# Global connection - will be initialized when needed
firestore_db = None
youtube = None

def initialize_services(collection_prefix=""):
    """Initialize YouTube API and Firestore connection"""
    global firestore_db, youtube

    if not firestore_db:
        firestore_db = FirestoreConnection(collection_prefix=collection_prefix)
        logger.info("✅ Firestore connection initialized")

    if not youtube:
        if not youtube_api_key:
            raise RuntimeError("YOUTUBE_API_KEY environment variable is not set")
        youtube = googleapiclient.discovery.build(
            api_service_name, api_version, developerKey=youtube_api_key
        )
        logger.info("✅ YouTube API client initialized")

def scrape_youtube_channels(collection_prefix=""):
    """Main function to scrape all configured YouTube channels"""
    try:
        initialize_services(collection_prefix)
        
        # ALL 25 channels from original script
        channels = [
            {"source_id": 50, "channel_id": "UCeDrtyuUbMLB_z6razI33dQ", "category": "אמונה-הסדר חיפה", "label": "הסדר חיפה - אחרונים"},
            {"source_id": 51, "channel_id": "UCBN2YMjFoJHX1qlpEcra29w", "category": "ישיבת המאירי", "label": "ישיבת המאירי - אחרונים"},
            {"source_id": 52, "channel_id": "UCMSm6HR03oQ7HfgOhtumEhQ", "category": "הסדר טפחות", "label": "הסדר טפחות - אחרונים"},
            {"source_id": 60, "channel_id": "UCS6OvEopzPGEEwYbAG4ismA", "category": "מעלה אדומים", "label": "ברכת משה- מעלה אדומים"},
            {"source_id": 61, "channel_id": "UCAcP4Dx-c66fPD5fYcYF0PQ", "category": "ישיבת הכותל", "label": "ישיבת הכותל - אחרונים"},
            {"source_id": 62, "channel_id": "UCjswceInZ37d8RIjHDz5ifw", "category": "ישיבת ר״ג", "label": "ישיבת רמת גן - אחרונים"},
            {"source_id": 63, "channel_id": "UCpEUk0Kpt07ms4zHWFsXxhg", "category": "ישיבת הר עציון", "label": "ישיבת הר עציון - אחרונים"},
            {"source_id": 64, "channel_id": "UCkwxRNj-7Iu1LlHJfKzl2Gw", "category": "ישיבת הר ברכה", "label": "ישיבת הר ברכה - אחרונים"},
            {"source_id": 65, "channel_id": "UC1BIlJW-jVw_EUnj0p-LIgQ", "category": "חב״ד", "label": "הרב שניאור אשכנזי"},
            {"source_id": 66, "channel_id": "UCp_YIYD7Ol3DXp6iR8A0ppg", "category": "הרב אורי שרקי", "label": "הרב אורי שרקי - אחרונים"},
            {"source_id": 67, "channel_id": "UC1UJunP8IpS4xfCRtB2HrPQ", "category": "ישיבת שבי חברון", "label": "ישיבת שבי חברון - אחרונים"},
            {"source_id": 68, "channel_id": "UCLUz-ovexcSqyW1xjShqZ7A", "category": "דף יומי", "label": "סיני - דף יומי"},
            {"source_id": 69, "channel_id": "UC3Kr93MBtpTJ0T-SIT7YM1g", "category": "הרב ראובן ששון", "label": "הרב ראובן ששון - אחרונים"},
            {"source_id": 70, "channel_id": "UC5WgSWUKh-I_G-rDCYanTsg", "category": "הרב אשר וייס", "label": "הרב אשר וייס - אחרונים"},
            {"source_id": 71, "channel_id": "UCE5C5A71vpM0INCP7IJ53hg", "category": "ישיבת ברוכין", "label": "ישיבת ברוכין - אחרונים"},
            {"source_id": 72, "channel_id": "UCoLW4u9Mj9XIMNOlIn2ICKg", "category": "מכינת עצמונה", "label": "מכינת עצמונה - אחרונים"},
            {"source_id": 73, "channel_id": "UCLlBotitx4zAGffm_Wdh7Bg", "category": "הרב מאיר אליהו", "label": "הרב מאיר אליהו - אחרונים"},
            {"source_id": 74, "channel_id": "UCewVpZ62BD241aNxjIMX_Yw", "category": "ישיבת המקובלים בית אל", "label": "ישיבת המקובלים בית אל - אחרונים"},
            {"source_id": 75, "channel_id": "UCOpMu7Q8T-Y9PrvxRiRCYgg", "category": "ישיבה גבוהה איתמר", "label": "ישיבה גבוהה איתמר"},
            {"source_id": 76, "channel_id": "UCQ1y3pMsmhtUpfE-cYdaZgg", "category": "בית מדרש קהילתי כפר סבא", "label": "בית מדרש קהילתי כפר סבא"},
            {"source_id": 77, "channel_id": "UCTZDTOM7lJQia5sqZOZ4tZg", "category": "הרב חגי לונדין", "label": "הרב חגי לונדין"},
            {"source_id": 78, "channel_id": "UCHOD7ezqUbpV1_AjGzdcT7A", "category": "הרב גיא אללוף", "label": "הרב גיא אללוף"},
            {"source_id": 79, "channel_id": "UCl1JXo-MwQD1gf9pTyAVy4A", "category": "הרב שמואל אליהו", "label": "הרב שמואל אליהו"},
            {"source_id": 80, "channel_id": "UCllz39jFUb3HL1zJx7PCKEg", "category": "מכון עולמות", "label": "מכון עולמות"},
            {"source_id": 81, "channel_id": "UCcHGO9721RdM4Bj9BATgnGQ", "category": "ישיבת רועה ישראל - יצהר", "label": "ישיבת רועה ישראל - יצהר"},
            {"source_id": 82, "channel_id": "UCP79eU_7Mky-_p2kSA8PGMQ", "category": "הרב שלמה אבינר", "label": "הרב שלמה אבינר"},
            {"source_id": 83, "channel_id": "UCgl-zxph-htP5qqPjMC7BMQ", "category": "הרב ניר מנוסי", "label": "הרב ניר מנוסי"},
            {"source_id": 84, "channel_id": "UCsD1AZVfS5YI8ZBbt7ErApQ", "category": "הרב יוני לביא", "label": "הרב יוני לביא"},
            {"source_id": 85, "channel_id": "UCdHjt2ox7DrxuwkrKRBDsTA", "category": "הרב יגאל לוינשטיין", "label": "הרב יגאל לוינשטיין"},
            {"source_id": 86, "channel_id": "UCbT4-nZcIQlSfGTQs9easlQ", "category": "הרב בנימין חותה", "label": "הרב בנימין חותה"},
            {"source_id": 87, "channel_id": "UC0tUHdaR25XS2RnemJSUVJX", "category": "הרב בנימין טבדי", "label": "הרב בנימין טבדי"},
            {"source_id": 88, "channel_id": "UCGKMTTAiv5KRJFkKte3ILvA", "category": "רוח הזמן - מתן חסידים", "label": "רוח הזמן - מתן חסידים"},
            {"source_id": 2, "channel_id": "UCEAZVyOtukIOH4BJ3gHKdng", "category": "ערוץ מאיר", "label": "ערוץ מאיר - יוטיוב"},
            {"source_id": 1, "channel_id": "UC3MjXqiy3SNNSWiixX2Mybw", "category": "בני דוד - כללי", "label": "בני דוד - ערוץ יוטיוב"}
        ]
        
        results = {
            'channels_processed': 0,
            'lessons_added': 0,
            'channel_details': [],
            'errors': []
        }

        logger.info(f"📺 Processing {len(channels)} YouTube channels")

        for channel in channels:
            try:
                logger.info(f"📺 Processing channel: {channel['label']}")
                channel_result = extract_lessons_for_channel_id(
                    channel['source_id'],
                    channel['channel_id'],
                    channel['category'],
                    channel['label']
                )
                results['channels_processed'] += 1
                added = channel_result.get('lessons_added', 0)
                results['lessons_added'] += added

                if added > 0:
                    results['channel_details'].append({
                        'label': channel['label'],
                        'lessons': channel_result.get('lesson_details', []),
                    })

                logger.info(f"✅ {channel['label']}: {added} new lessons")

            except Exception as e:
                logger.error(f"❌ Error processing channel {channel['label']}: {e}")
                results['errors'].append({
                    'source_id': channel['source_id'],
                    'channel_id': channel['channel_id'],
                    'label': channel['label'],
                    'error': str(e)
                })
        
        logger.info(f"🎯 YouTube scraping complete: {results}")
        return results
        
    except Exception as e:
        logger.error(f"❌ YouTube scraping failed: {e}")
        raise

def extract_lessons_for_channel_id(source_id: int, channel_id: str, category: str, label: str):
    """Extract lessons for a YouTube channel - ZERO-COST VERSION using sources collection"""
    logger.info(f"🔍 Extracting lessons for source {source_id}")

    # 1. Load source document (1 read!) - contains lessonIds array
    sources_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}sources')
    source_query = sources_ref.where('originalId', '==', source_id).limit(1).get()

    if not source_query:
        # Source doesn't exist, create it with empty lessonIds
        logger.info(f"Creating new source {source_id}")
        new_source_doc = sources_ref.document()
        new_source_doc.set({
            'originalId': source_id,
            'label': category,
            'totalCount': 0,
            'lessonIds': [],  # Start with empty array
            'channelId': channel_id,
            'createdAt': datetime.now().isoformat(),
            'updatedAt': datetime.now().isoformat()
        })
        source_doc_ref = new_source_doc
        exists_lesson_ids = set()
    else:
        source_doc = source_query[0]
        source_doc_ref = source_doc.reference
        source_data = source_doc.to_dict()

        # 2. Load existing lesson IDs into memory (O(1) lookup with set)
        exists_lesson_ids = set(source_data.get('lessonIds', []))
        logger.info(f"📦 Loaded {len(exists_lesson_ids)} existing lesson IDs for source {source_id}")


    # 3. Track new lessons and counters in memory
    new_lesson_ids = []
    categories_affected = defaultdict(int)
    series_affected = defaultdict(int)

    # 4. Clear labels FIRST (like original scraper)
    clear_labels_for_source(source_id)

    # 5. Create or get category
    categories_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}categories')
    original_category_id = int(str(get_hash_for_string(category))[:8])
    numeric_category_id = get_hash_for_id(source_id, original_category_id)
    category_doc_id = f"cat_{str(numeric_category_id)[:16]}"

    category_doc = categories_ref.document(category_doc_id).get()
    if not category_doc.exists:
        categories_ref.document(category_doc_id).set({
            'id': numeric_category_id,
            'originalId': original_category_id,
            'sourceId': source_id,
            'category': category,
            'totalCount': 0,
            'createdAt': datetime.now().isoformat(),
            'updatedAt': datetime.now().isoformat()
        })

    # 6. Process videos from YouTube
    result = process_channel_videos(
        channel_id, source_id, category, label,
        exists_lesson_ids, new_lesson_ids,
        categories_affected, series_affected,
        category_doc_id, source_doc_ref
    )

    # 7. Batch update counters at END of channel (if we added new lessons)
    if new_lesson_ids:
        batch = firestore_db.db.batch()

        # Update source: totalCount + lastScrapedAt (no more lessonIds array)
        batch.update(source_doc_ref, {
            'totalCount': Increment(len(new_lesson_ids)),
            'lastScrapedAt': datetime.now().isoformat(),
            'updatedAt': datetime.now().isoformat()
        })

        # Update affected categories
        for cat_id, count in categories_affected.items():
            batch.update(categories_ref.document(cat_id), {
                'totalCount': Increment(count),
                'updatedAt': datetime.now().isoformat()
            })

        # Update affected series
        series_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}series')
        for ser_id, count in series_affected.items():
            batch.update(series_ref.document(ser_id), {
                'totalCount': Increment(count),
                'updatedAt': datetime.now().isoformat()
            })

        batch.commit()
        logger.info(f"✅ Updated counters: +{len(new_lesson_ids)} lessons")

    # 8. Add labels for the 10 most recent lessons
    add_labels_for_recent_lessons(source_id, category_doc_id, label)

    logger.info(f"✅ Extracted {len(new_lesson_ids)} new lessons for source {source_id}")
    return {'lessons_added': len(new_lesson_ids), 'lesson_details': result.get('lesson_details', [])}

def clear_labels_for_source(source_id: int):
    """Delete the label doc for this source (deterministic ID = label_{source_id})."""
    labels_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}labels')
    labels_ref.document(f"label_{source_id}").delete()
    logger.info(f"🧹 Cleared label for source {source_id}")

def add_labels_for_recent_lessons(source_id: int, category_id: str, label: str):
    """Add one label doc with the 10 most recent lesson IDs for this source+category.

    For sources shared with a WP scraper (sourceId=1 Bnei David, sourceId=2 Arutz Meir),
    filter by scrapeSource containing 'youtube' so WP lessons don't crowd out YouTube ones.
    For YouTube-only sources (50–74), filter by categoryId as before.
    """
    lessons_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}lessons')

    # Sources 1 and 2 are shared with WP scrapers — identify YouTube lessons by scrapeSource
    SHARED_SOURCES = {1, 2}
    if source_id in SHARED_SOURCES:
        query = (
            lessons_ref
            .where('sourceId', '==', source_id)
            .where('scrapeSource', 'array_contains', 'youtube')
            .order_by('timestamp', direction='DESCENDING')
            .limit(10)
        )
    else:
        query = (
            lessons_ref
            .where('sourceId', '==', source_id)
            .where('categoryId', '==', category_id)
            .order_by('timestamp', direction='DESCENDING')
            .limit(10)
        )

    lesson_docs = query.get()

    lesson_ids = [d.to_dict().get('id') for d in lesson_docs if d.to_dict().get('id')]
    if not lesson_ids:
        logger.info(f"⚠️ No lessons found for label '{label}' (source {source_id})")
        return

    # One document per label, with lessonIds array — matches Flutter app schema
    labels_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}labels')
    label_doc_id = f"label_{source_id}"
    labels_ref.document(label_doc_id).set({
        'label': label,
        'sourceId': source_id,
        'lessonIds': [str(lid) for lid in lesson_ids],
        'updatedAt': datetime.now().isoformat(),
    })
    logger.info(f"✅ Label '{label}': {len(lesson_ids)} lesson IDs written")

def _should_refresh_playlist_map(source_data, new_videos_found):
    """
    Return True if the playlist map needs to be refreshed.

    Refresh when ANY of the following:
    - new_videos_found: new lessons were added this run
    - playlistMap is missing (first run)
    - lastPlaylistScanAt is missing (first run)
    - more than 7 days have elapsed since lastPlaylistScanAt
    """
    if new_videos_found:
        return True
    if 'playlistMap' not in source_data:
        return True
    last_scan_str = source_data.get('lastPlaylistScanAt')
    if not last_scan_str:
        return True
    try:
        from datetime import timezone
        last_scan = datetime.fromisoformat(last_scan_str.replace('Z', '+00:00'))
        # Make timezone-aware if naive
        if last_scan.tzinfo is None:
            last_scan = last_scan.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - last_scan
        if elapsed.days >= 7:
            return True
    except Exception:
        return True  # unparseable → refresh
    return False


def _get_or_create_series_doc(series_ref, source_id, playlist_id, playlist_title):
    """
    Get or create a Firestore series doc for a named playlist.
    Returns the series doc ID.
    """
    original_playlist_id = int(str(get_hash_for_string(playlist_id))[:8])
    numeric_series_id = get_hash_for_id(source_id, original_playlist_id)
    series_doc_id = f"ser_{str(numeric_series_id)[:16]}"

    series_doc = series_ref.document(series_doc_id).get()
    if not series_doc.exists:
        series_ref.document(series_doc_id).set({
            'id': numeric_series_id,
            'originalId': original_playlist_id,
            'sourceId': source_id,
            'serie': playlist_title[:80],
            'totalCount': 0,
            'createdAt': datetime.now().isoformat(),
            'updatedAt': datetime.now().isoformat()
        })
        logger.info(f"📂 Created series: {playlist_title}")
    return series_doc_id


def _fetch_playlist_map(channel_id, source_id, uploads_playlist_id, series_ref):
    """
    Fetch all user-created playlists for the channel and build a
    {videoId: seriesDocId} map.

    The uploads playlist (auto-generated, whose ID matches uploads_playlist_id)
    is excluded. Any playlist whose ID starts with 'UU' is also excluded
    (YouTube's auto-generated uploads playlist naming convention).

    Returns: dict {videoId: series_doc_id}
    """
    playlist_map = {}

    # Fetch all playlists for the channel
    next_page_token = None
    while True:
        req_kwargs = dict(part="snippet", channelId=channel_id, maxResults=50)
        if next_page_token:
            req_kwargs['pageToken'] = next_page_token

        response = youtube.playlists().list(**req_kwargs).execute()
        items = response.get('items', [])

        for playlist in items:
            pl_id = playlist['id']
            pl_title = playlist['snippet']['title']

            # Exclude the auto-generated uploads playlist
            if pl_id == uploads_playlist_id:
                continue
            # Exclude any playlist with auto-generated 'UU' prefix
            if pl_id.startswith('UU'):
                continue

            # Create/get series doc for this playlist
            series_doc_id = _get_or_create_series_doc(series_ref, source_id, pl_id, pl_title)

            # Fetch all video IDs in this playlist
            items_page_token = None
            while True:
                items_kwargs = dict(part="snippet", playlistId=pl_id, maxResults=50)
                if items_page_token:
                    items_kwargs['pageToken'] = items_page_token

                items_response = youtube.playlistItems().list(**items_kwargs).execute()
                for item in items_response.get('items', []):
                    video_id = item['snippet']['resourceId']['videoId']
                    playlist_map[video_id] = series_doc_id  # last one wins

                items_page_token = items_response.get('nextPageToken')
                if not items_page_token:
                    break

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    logger.info(f"📋 Built playlist map: {len(playlist_map)} video→series entries")
    return playlist_map


def process_channel_videos(channel_id, source_id, category, label,
                           exists_lesson_ids, new_lesson_ids,
                           categories_affected, series_affected,
                           category_doc_id, source_doc_ref):
    """Process videos from YouTube channel - tracks counters in memory"""
    logger.info(f"📥 Getting videos for channel {channel_id}")

    try:
        # Get channel details to find uploads playlist
        channel_request = youtube.channels().list(
            part="contentDetails",
            id=channel_id
        )
        channel_response = channel_request.execute()

        if not channel_response.get('items'):
            logger.warning(f"Channel {channel_id} not found")
            return {'lessons_added': 0}

        uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

        series_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}series')

        # Always ensure the כללי (fallback) series exists
        כללי_series_doc_id = _get_or_create_series_doc(
            series_ref, source_id, uploads_playlist_id, "כללי"
        )

        # Load current source data to check playlist map cache
        source_data = source_doc_ref.get().to_dict() or {}

        # Safety: if exists_lesson_ids is empty for an existing source, the migration
        # may have seeded Firestore with lessons under a different ID scheme (e.g.
        # PostgreSQL bigint IDs). Scan existing videoUrls and compute their hash-based
        # IDs so the dedup check correctly skips already-present videos.
        # This is a one-time O(N) cost per channel on the first scrape after migration.
        if not exists_lesson_ids:
            logger.info(f"⚠️ exists_lesson_ids empty — scanning Firestore videoUrls to prevent duplicates from ID-scheme mismatch")
            lessons_ref_scan = firestore_db.db.collection(f'{firestore_db.collection_prefix}lessons')
            from urllib.parse import urlparse, parse_qs
            # Use paginated .get() with limit to avoid _retry streaming bug on large collections
            PAGE_SIZE = 500
            last_doc = None
            while True:
                q = lessons_ref_scan.where('sourceId', '==', source_id).limit(PAGE_SIZE)
                if last_doc:
                    q = q.start_after(last_doc)
                page = q.get()
                if not page:
                    break
                for doc in page:
                    url = doc.to_dict().get('videoUrl', '')
                    if url and 'youtube.com/watch?v=' in url:
                        try:
                            vid = parse_qs(urlparse(url).query).get('v', [None])[0]
                            if vid:
                                exists_lesson_ids.add(get_hash_for_id(source_id, get_hash_for_string(vid)))
                        except Exception:
                            pass
                last_doc = page[-1]
                if len(page) < PAGE_SIZE:
                    break
            logger.info(f"📦 Populated {len(exists_lesson_ids)} synthetic IDs from existing videoUrls")

        # Phase 1: collect all new videos first (before deciding on playlist refresh)
        # We need to know if new_videos_found to decide whether to refresh.
        # So we do a two-pass approach:
        #   Pass 1 — collect raw video items from uploads playlist (no writes yet)
        #   Decide refresh
        #   Fetch playlist map if needed
        #   Pass 2 — write lessons with correct seriesId

        raw_videos = []  # list of (video_id, snippet, content_details) for new videos only
        next_page_token = ""
        last_scraped_at = source_data.get('lastScrapedAt')  # ISO string or None

        while True:
            playlist_request = youtube.playlistItems().list(
                part="snippet",
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            playlist_response = playlist_request.execute()

            video_ids_in_page = [
                item['snippet']['resourceId']['videoId']
                for item in playlist_response['items']
            ]

            if not video_ids_in_page:
                break

            # Fetch video details
            videos_request = youtube.videos().list(
                part="snippet,contentDetails",
                id=','.join(video_ids_in_page)
            )
            videos_response = videos_request.execute()

            new_in_page = 0
            stop_pagination = False
            for video in videos_response['items']:
                video_id = video['id']
                published_at = video['snippet'].get('publishedAt', '')

                # On incremental runs: stop when we reach content older than last scrape.
                # YouTube returns newest-first so everything after this is already processed.
                if last_scraped_at and published_at and published_at <= last_scraped_at:
                    logger.info(f"🏁 Reached content from {published_at} ≤ lastScrapedAt {last_scraped_at}, stopping")
                    stop_pagination = True
                    break

                original_video_id = get_hash_for_string(video_id)
                lesson_id = get_hash_for_id(source_id, original_video_id)

                # Dedup check — needed for first run against PostgreSQL-migrated lessons
                if lesson_id in exists_lesson_ids:
                    continue

                raw_videos.append((video_id, video['snippet'], video['contentDetails'], lesson_id, original_video_id))
                new_in_page += 1

            logger.info(f"📊 Scanned page: {new_in_page} new videos")

            if stop_pagination:
                break

            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break

        new_videos_found = len(raw_videos) > 0

        # Decide whether to refresh the playlist map
        if _should_refresh_playlist_map(source_data, new_videos_found):
            logger.info("🔄 Refreshing playlist map from YouTube API")
            playlist_map = _fetch_playlist_map(
                channel_id, source_id, uploads_playlist_id, series_ref
            )
            # Persist updated map to source doc
            source_doc_ref.update({
                'playlistMap': playlist_map,
                'lastPlaylistScanAt': datetime.now().isoformat(),
            })
        else:
            playlist_map = source_data.get('playlistMap', {})
            logger.info(f"✅ Using cached playlist map ({len(playlist_map)} entries)")

        # Write new lessons with correct seriesId
        lessons_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}lessons')

        for video_id, snippet, content_details, lesson_id, original_video_id in raw_videos:
            # Determine seriesId: use playlist map, fallback to כללי
            series_doc_id = playlist_map.get(video_id, כללי_series_doc_id)

            # Parse publish date
            published_at = snippet.get('publishedAt', '')
            try:
                publish_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                timestamp = int(publish_date.timestamp())
                date_str = publish_date.strftime('%Y-%m-%d')
            except Exception:
                timestamp = get_timestamp()
                date_str = datetime.now().strftime('%Y-%m-%d')

            # Parse duration
            duration_iso = content_details.get('duration', 'PT0S')
            duration_seconds = get_iso_duration_in_seconds(duration_iso)

            lesson_data = {
                "id": lesson_id,
                "sourceId": source_id,
                "originalId": original_video_id,
                "title": snippet.get('title', ''),
                "categoryId": category_doc_id,
                "seriesId": series_doc_id,
                "ravId": None,  # YouTube videos don't have rabbi info
                "videoUrl": youtube_base_url % video_id,
                "audioUrl": None,
                "dateStr": date_str,
                "duration": duration_seconds,
                "timestamp": timestamp,
                "scrapeSource": ["youtube"],
                "createdAt": datetime.now().isoformat(),
                "updatedAt": datetime.now().isoformat()
            }

            lessons_ref.document(str(lesson_id)).set(lesson_data)
            print(f"  ➕ NEW: [{source_id}] {snippet.get('title', '')[:60]} | {date_str} | {duration_seconds}s | {youtube_base_url % video_id}", flush=True)

            new_lesson_ids.append(lesson_id)
            exists_lesson_ids.add(lesson_id)
            categories_affected[category_doc_id] += 1
            series_affected[series_doc_id] += 1

        # Embed new lessons for smart search
        if new_lesson_ids:
            try:
                from utils.embedder import embed_lessons_batch
                embed_lessons_batch(firestore_db.db, [str(lid) for lid in new_lesson_ids])
            except Exception as e:
                logger.warning(f"Embedding failed for {len(new_lesson_ids)} lessons: {e}")

        logger.info(f"✅ Finished processing, added {len(new_lesson_ids)} new lessons")

        # Build lesson detail list for Telegram notification
        lesson_details = []
        for video_id, snippet, content_details, lesson_id, _ in raw_videos:
            series_doc_id = playlist_map.get(video_id, כללי_series_doc_id)
            serie_name = ''
            try:
                serie_doc = firestore_db.db.collection(f'{firestore_db.collection_prefix}series').document(series_doc_id).get()
                if serie_doc.exists:
                    serie_name = serie_doc.to_dict().get('serie', '')
            except Exception:
                pass
            published_at = snippet.get('publishedAt', '')[:10]
            duration_iso = content_details.get('duration', 'PT0S')
            lesson_details.append({
                'title': snippet.get('title', ''),
                'serie': serie_name,
                'date': published_at,
                'duration': get_iso_duration_in_seconds(duration_iso),
                'url': youtube_base_url % video_id,
            })

        return {'lessons_added': len(new_lesson_ids), 'lesson_details': lesson_details}

    except Exception as e:
        logger.error(f"❌ Error processing channel videos: {e}")
        raise

def cleanup_test_collections(collection_prefix="test_"):
    """Clean up test collections"""
    if not collection_prefix:
        logger.warning("🚫 Cleanup only for test collections!")
        return False
    
    global firestore_db
    if not firestore_db:
        firestore_db = FirestoreConnection(collection_prefix=collection_prefix)
    
    try:
        collections = ['lessons', 'categories', 'ravs', 'sources', 'labels']
        deleted_count = 0
        
        for collection_name in collections:
            full_name = f'{collection_prefix}{collection_name}'
            docs = firestore_db.db.collection(full_name).get()
            for doc in docs:
                doc.reference.delete()
                deleted_count += 1
            
            if len(docs) > 0:
                logger.info(f"🗑️  Deleted {len(docs)} documents from {full_name}")
        
        logger.info(f"✅ Cleanup complete! Deleted {deleted_count} total documents")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        return False

# For backwards compatibility
def grab_yotube():
    """Legacy function name - calls the new function"""
    return scrape_youtube_channels() 