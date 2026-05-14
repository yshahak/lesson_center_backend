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
            # TODO: Implement when converted
            results['bnei_david'] = {'status': 'not_implemented'}
            logger.info("⚠️ Bnei David scraper not yet implemented")
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

if __name__ == '__main__':
    # For local testing
    print("🧪 Testing Cloud Functions locally...")
    result = run_scrapers('youtube')
    print(f"Result: {json.dumps(result, indent=2)}") 