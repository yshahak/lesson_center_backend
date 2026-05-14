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
            {"source_id": 74, "channel_id": "UCewVpZ62BD241aNxjIMX_Yw", "category": "ישיבת המקובלים בית אל", "label": "ישיבת המקובלים בית אל - אחרונים"}
        ]
        
        results = {
            'channels_processed': 0,
            'lessons_added': 0,
            'errors': []
        }

        logger.info(f"📺 Processing {len(channels)} YouTube channels")

        # Process ALL channels
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
                results['lessons_added'] += channel_result.get('lessons_added', 0)

                logger.info(f"✅ {channel['label']}: {channel_result['lessons_added']} new lessons")

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

        # Update source: totalCount + lessonIds + lastScrapedAt
        batch.update(source_doc_ref, {
            'totalCount': Increment(len(new_lesson_ids)),
            'lessonIds': list(exists_lesson_ids),  # Updated array with new IDs
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
    return {'lessons_added': len(new_lesson_ids)}

def clear_labels_for_source(source_id: int):
    """Delete the label doc for this source (deterministic ID = label_{source_id})."""
    labels_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}labels')
    labels_ref.document(f"label_{source_id}").delete()
    logger.info(f"🧹 Cleared label for source {source_id}")

def add_labels_for_recent_lessons(source_id: int, category_id: str, label: str):
    """Add one label doc with the 10 most recent lesson IDs for this source+category."""
    lessons_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}lessons')
    query = lessons_ref.where('sourceId', '==', source_id).where('categoryId', '==', category_id).order_by('timestamp', direction='DESCENDING').limit(10)
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

        # Create series entry for uploads playlist
        series_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}series')
        original_playlist_id = int(str(get_hash_for_string(uploads_playlist_id))[:8])
        numeric_series_id = get_hash_for_id(source_id, original_playlist_id)
        series_doc_id = f"ser_{str(numeric_series_id)[:16]}"
        series_title = "כללי"

        series_doc = series_ref.document(series_doc_id).get()
        if not series_doc.exists:
            series_ref.document(series_doc_id).set({
                'id': numeric_series_id,
                'originalId': original_playlist_id,
                'sourceId': source_id,
                'serie': series_title[:80],
                'totalCount': 0,
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat()
            })
            logger.info(f"📂 Created series: {series_title}")

        next_page_token = ""
        videos_processed = 0
        lessons_ref = firestore_db.db.collection(f'{firestore_db.collection_prefix}lessons')

        # YouTube returns videos newest-first. Stop when a full page is all already-seen —
        # that means we've caught up to previously scraped content.
        while True:
            playlist_request = youtube.playlistItems().list(
                part="snippet",
                playlistId=uploads_playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            playlist_response = playlist_request.execute()

            video_ids = [item['snippet']['resourceId']['videoId'] for item in playlist_response['items']]

            if not video_ids:
                break

            # Get video details
            videos_request = youtube.videos().list(
                part="snippet,contentDetails",
                id=','.join(video_ids)
            )
            videos_response = videos_request.execute()

            new_in_page = 0
            for video in videos_response['items']:
                video_id = video['id']
                snippet = video['snippet']
                content_details = video['contentDetails']

                # Create lesson ID
                original_video_id = get_hash_for_string(video_id)
                lesson_id = get_hash_for_id(source_id, original_video_id)

                # Skip if already exists (O(1) lookup in set)
                if lesson_id in exists_lesson_ids:
                    continue

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
                    "createdAt": datetime.now().isoformat(),
                    "updatedAt": datetime.now().isoformat()
                }

                lessons_ref.document(str(lesson_id)).set(lesson_data)
                print(f"  ➕ NEW: [{source_id}] {snippet.get('title', '')[:60]} | {date_str} | {duration_seconds}s | {youtube_base_url % video_id}", flush=True)

                new_lesson_ids.append(lesson_id)
                exists_lesson_ids.add(lesson_id)
                categories_affected[category_doc_id] += 1
                series_affected[series_doc_id] += 1
                new_in_page += 1

            videos_processed += len(video_ids)
            logger.info(f"📊 Processed {videos_processed} videos so far, +{new_in_page} new this page")

            # All videos in this page already existed → we've caught up, stop paginating
            if new_in_page == 0:
                logger.info("🏁 Full page already seen, stopping pagination")
                break

            next_page_token = playlist_response.get('nextPageToken')
            if not next_page_token:
                break

        logger.info(f"✅ Finished processing {videos_processed} videos, added {len(new_lesson_ids)} new lessons")
        return {'lessons_added': len(new_lesson_ids)}

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