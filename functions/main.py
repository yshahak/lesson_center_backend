#!/usr/bin/env python3
"""
Firebase Cloud Functions - Main Entry Point
Handles scheduled scraping of lesson content to Firestore
"""

import functions_framework
from scrapers.youtube_scraper import scrape_youtube_channels
from scrapers.bnei_david_scraper import scrape_bnei_david  # TODO: Create this
from scrapers.arutz_meir_scraper import scrape_arutz_meir  # TODO: Create this
from utils.firestore_helper import get_timestamp
import json
import logging
import sys
import subprocess
import re
import time
import datetime

import firebase_admin
from firebase_admin import firestore as admin_firestore

# Disable stdout buffering so print() appears immediately in Cloud Logging
sys.stdout.reconfigure(line_buffering=True)

# Force logs to stdout — Cloud Run captures stdout but not stderr from Python's logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)
logger = logging.getLogger(__name__)

@functions_framework.http
def scrape_lessons_http(request):
    """HTTP Cloud Function for manual triggering"""
    try:
        request_json = request.get_json(silent=True)
        scraper_type = request_json.get('scraper', 'all') if request_json else 'all'
        
        result = run_scrapers(scraper_type)
        
        return {
            'status': 'success',
            'message': 'Scraping completed',
            'details': result
        }
    except Exception as e:
        logger.error(f"HTTP function error: {e}")
        return {
            'status': 'error',
            'message': str(e)
        }, 500

@functions_framework.cloud_event
def scrape_lessons_scheduled(cloud_event):
    """Scheduled Cloud Function (triggered by Cloud Scheduler)"""
    try:
        logger.info("Starting scheduled lesson scraping...")
        result = run_scrapers('all')
        logger.info(f"Scheduled scraping completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Scheduled function error: {e}")
        raise

def run_scrapers(scraper_type='all'):
    """Run the specified scrapers"""
    results = {}
    start_time = get_timestamp()
    
    logger.info(f"🚀 Starting scraping session - type: {scraper_type}")
    
    if scraper_type in ['all', 'youtube']:
        try:
            logger.info("📺 Running YouTube scraper...")
            youtube_result = scrape_youtube_channels()
            results['youtube'] = youtube_result
            logger.info(f"✅ YouTube scraping complete: {youtube_result}")
        except Exception as e:
            logger.error(f"❌ YouTube scraping failed: {e}")
            results['youtube'] = {'error': str(e)}
    
    if scraper_type in ['all', 'bnei_david']:
        try:
            logger.info("🏛️ Running Bnei David scraper...")
            bnei_david_result = scrape_bnei_david()
            results['bnei_david'] = bnei_david_result
            logger.info(f"✅ Bnei David scraping complete: {bnei_david_result}")
        except Exception as e:
            logger.error(f"❌ Bnei David scraping failed: {e}")
            results['bnei_david'] = {'error': str(e)}
    
    if scraper_type in ['all', 'arutz_meir']:
        try:
            logger.info("📻 Running Arutz Meir scraper...")
            # TODO: Implement when converted
            results['arutz_meir'] = {'status': 'not_implemented'}
            logger.info("⚠️ Arutz Meir scraper not yet implemented")
        except Exception as e:
            logger.error(f"❌ Arutz Meir scraping failed: {e}")
            results['arutz_meir'] = {'error': str(e)}
    
    end_time = get_timestamp()
    duration = end_time - start_time
    
    final_result = {
        'start_time': start_time,
        'end_time': end_time,
        'duration_seconds': duration,
        'scrapers_run': scraper_type,
        'results': results
    }
    
    logger.info(f"🎯 Scraping session complete - Duration: {duration}s")
    return final_result

###############################################################################
# Vimeo URL Resolver — with Firestore cache
###############################################################################

# Vimeo progressive URL TTL is ~24 hours. We cache for 20 hours to give a
# 4-hour buffer before expiry (so in-flight playback sessions aren't cut short).
_CACHE_TTL_SECONDS = 20 * 3600  # 20 hours

# yt-dlp format selector: prefer progressive HTTPS MP4 (best for Flutter
# video_player seeking), falling back to HLS if no progressive stream exists.
_FORMAT_SELECTOR = "http-720p/http-540p/http-360p/http-240p/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best"

# Firestore collection for cached URLs
_CACHE_COLLECTION = "vimeo_cache"


def _get_db():
    """Return the Firestore client, initialising the Firebase app if needed."""
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": "tora-or"})
    return admin_firestore.client()


def _resolve_via_ytdlp(video_id: str) -> str:
    """
    Run yt-dlp to resolve a Vimeo video ID to a direct playable URL.

    Returns the first non-empty URL from stdout.
    Raises RuntimeError if yt-dlp fails or returns no URL.
    """
    result = subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "-f", _FORMAT_SELECTOR,
            "--get-url",
            f"https://vimeo.com/{video_id}",
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"yt-dlp exited {result.returncode}: {stderr[:300]}")

    urls = [u.strip() for u in result.stdout.splitlines() if u.strip()]
    if not urls:
        raise RuntimeError("yt-dlp returned no URLs")

    # Prefer a progressive HTTPS URL over an adaptive stream when multiple are returned.
    for url in urls:
        if "progressive_redirect" in url or (".mp4" in url and "vimeocdn.com" not in url):
            return url
    # Fall back to the first URL (HLS/DASH)
    return urls[0]


@functions_framework.http
def resolve_vimeo_url(request):
    """Resolve a Bnei David Vimeo video ID to a playable stream URL.

    Query param: ?video_id=1191960680
    Returns: {"url": "https://...", "cached": true/false, "expires_in_seconds": 72000}
    Error:   {"error": "..."} with HTTP 400 or 500
    """
    video_id = request.args.get("video_id", "").strip()
    if not video_id:
        return (json.dumps({"error": "Missing required query parameter: video_id"}), 400,
                {"Content-Type": "application/json"})

    # Validate: Vimeo IDs are purely numeric
    if not re.match(r"^\d+$", video_id):
        return (json.dumps({"error": f"Invalid video_id: must be numeric, got '{video_id}'"}), 400,
                {"Content-Type": "application/json"})

    db = _get_db()
    cache_ref = db.collection(_CACHE_COLLECTION).document(video_id)

    # --- Cache read ---
    now = time.time()
    try:
        doc = cache_ref.get()
        if doc.exists:
            data = doc.to_dict()
            expires_at = data.get("expires_at")  # Unix timestamp (float)
            url = data.get("url", "")
            if expires_at and expires_at > now and url:
                expires_in = int(expires_at - now)
                logger.info(f"vimeo_cache HIT for {video_id}, expires in {expires_in}s")
                return (
                    json.dumps({"url": url, "cached": True, "expires_in_seconds": expires_in}),
                    200,
                    {"Content-Type": "application/json"},
                )
    except Exception as e:
        # Cache read failure is non-fatal — fall through to yt-dlp
        logger.warning(f"vimeo_cache read failed for {video_id}: {e}")

    # --- Cache miss: resolve via yt-dlp ---
    logger.info(f"vimeo_cache MISS for {video_id}, invoking yt-dlp")
    try:
        start = time.time()
        url = _resolve_via_ytdlp(video_id)
        elapsed = time.time() - start
        logger.info(f"yt-dlp resolved {video_id} in {elapsed:.2f}s → {url[:80]}")
    except subprocess.TimeoutExpired:
        logger.error(f"yt-dlp timed out for {video_id}")
        return (json.dumps({"error": "yt-dlp timed out resolving Vimeo URL"}), 500,
                {"Content-Type": "application/json"})
    except RuntimeError as e:
        logger.error(f"yt-dlp failed for {video_id}: {e}")
        return (json.dumps({"error": str(e)}), 500,
                {"Content-Type": "application/json"})

    if not url:
        return (json.dumps({"error": "yt-dlp returned empty URL"}), 500,
                {"Content-Type": "application/json"})

    # --- Cache write ---
    expires_at = now + _CACHE_TTL_SECONDS
    try:
        cache_ref.set({
            "url": url,
            "resolved_at": datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc).isoformat(),
            "expires_at": expires_at,
            "video_id": video_id,
        })
        logger.info(f"vimeo_cache STORED for {video_id}, TTL={_CACHE_TTL_SECONDS}s")
    except Exception as e:
        # Cache write failure is non-fatal — still return the URL
        logger.warning(f"vimeo_cache write failed for {video_id}: {e}")

    expires_in = _CACHE_TTL_SECONDS
    return (
        json.dumps({"url": url, "cached": False, "expires_in_seconds": expires_in}),
        200,
        {"Content-Type": "application/json"},
    )


if __name__ == '__main__':
    # For local testing
    print("🧪 Testing Cloud Functions locally...")
    result = run_scrapers('youtube')
    print(f"Result: {json.dumps(result, indent=2)}") 