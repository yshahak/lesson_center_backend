#!/usr/bin/env python3
"""
Integration tests for the FlareSolverr-based Arutz Meir scraper.
Runs against live meirtv.com via FlareSolverr — requires Docker running.

Run from lesson_center_backend/functions/:
    python -m pytest ../scripts/tests/test_arutz_meir_scraper.py -v
"""
import json
import re
import sys
import os

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../../functions')

from scrapers.arutz_meir_scraper import (
    _fs_raw, _fs_json, _fs_html,
    _extract_vimeo_id, _extract_site_audio_url,
    check_flaresolverr, _FS_PORT,
)

# Known lesson we can test against (verified working)
KNOWN_LESSON_WP_ID = 389002
KNOWN_LESSON_URL = f"https://meirtv.com/shiurim/{KNOWN_LESSON_WP_ID}/"
KNOWN_VIMEO_ID = "1192180085"
KNOWN_AUDIO_PREFIX = "mp3.meirtv.co.il"
WP_API_URL = "https://meirtv.com/wp-json/wp/v2/shiurim"


# ---------------------------------------------------------------------------
# Test 1: FlareSolverr connectivity
# ---------------------------------------------------------------------------

def test_flaresolverr_is_running():
    assert check_flaresolverr(_FS_PORT), (
        f"FlareSolverr is NOT running on port {_FS_PORT}. "
        f"Start it: docker run -d --name flaresolverr -p {_FS_PORT}:8191 "
        f"ghcr.io/flaresolverr/flaresolverr:latest"
    )


# ---------------------------------------------------------------------------
# Test 2: WP API returns valid JSON via FlareSolverr
# ---------------------------------------------------------------------------

def test_wp_api_returns_json():
    url = f"{WP_API_URL}/{KNOWN_LESSON_WP_ID}?_fields=id,slug,title,date"
    data, status, headers = _fs_json(url, _FS_PORT)
    assert status == 200, f"WP API returned status {status}"
    assert data is not None, "WP API returned no data"
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert data.get("id") == KNOWN_LESSON_WP_ID, f"Unexpected lesson id: {data.get('id')}"
    print(f"  ✓ WP API lesson: id={data['id']} slug={data.get('slug')} date={data.get('date','')[:10]}")


def test_wp_api_pagination_returns_lessons():
    """API paginated list returns a non-empty list of lessons."""
    from urllib.parse import urlencode
    params = {"per_page": 5, "page": 1, "orderby": "date", "order": "desc"}
    url = f"{WP_API_URL}?{urlencode(params)}"
    data, status, headers = _fs_json(url, _FS_PORT)
    assert status == 200, f"WP API pagination returned status {status}"
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    assert len(data) > 0, "Expected non-empty list of lessons"
    assert "id" in data[0], "Lesson items should have 'id' field"
    print(f"  ✓ Pagination: got {len(data)} lessons, first id={data[0]['id']}")


# ---------------------------------------------------------------------------
# Test 3: Lesson page HTML contains vimeoId and audio
# ---------------------------------------------------------------------------

def test_lesson_html_fetched_successfully():
    html, status = _fs_html(KNOWN_LESSON_URL, _FS_PORT)
    assert status == 200, f"HTML fetch returned status {status}"
    assert html is not None, "HTML is None (partial render or 404)"
    assert len(html) >= 250_000, f"HTML too short ({len(html)}B) — partial render"
    assert "player.vimeo.com" in html, "No Vimeo player found in HTML"
    print(f"  ✓ HTML fetched: {len(html):,} bytes")


# ---------------------------------------------------------------------------
# Test 4: _extract_vimeo_id works on real HTML
# ---------------------------------------------------------------------------

def test_extract_vimeo_id_from_real_html():
    html, _ = _fs_html(KNOWN_LESSON_URL, _FS_PORT)
    assert html is not None, "Could not fetch HTML"
    vimeo_id = _extract_vimeo_id(html)
    assert vimeo_id is not None, "No vimeoId extracted from HTML"
    assert vimeo_id == KNOWN_VIMEO_ID, f"Expected {KNOWN_VIMEO_ID}, got {vimeo_id}"
    print(f"  ✓ vimeoId extracted: {vimeo_id}")


# ---------------------------------------------------------------------------
# Test 5: _extract_site_audio_url works on real HTML
# ---------------------------------------------------------------------------

def test_extract_audio_url_from_real_html():
    html, _ = _fs_html(KNOWN_LESSON_URL, _FS_PORT)
    assert html is not None, "Could not fetch HTML"
    audio_url = _extract_site_audio_url(html)
    assert audio_url is not None, "No audio URL extracted from HTML"
    assert KNOWN_AUDIO_PREFIX in audio_url, f"Expected mp3.meirtv.co.il in URL, got: {audio_url}"
    print(f"  ✓ audioUrl extracted: {audio_url[:60]}")


# ---------------------------------------------------------------------------
# Test 6: WP 404 detection works correctly
# ---------------------------------------------------------------------------

def test_wp_404_detected_correctly():
    """A non-existent slug should return None (WP 404 served as HTTP 200)."""
    fake_url = "https://meirtv.com/shiurim/shiur-999999999/"
    html, status = _fs_html(fake_url, _FS_PORT)
    assert html is None, f"Expected None for non-existent slug, got {len(html or '')}B"
    assert status == 404, f"Expected 404, got {status}"
    print(f"  ✓ WP 404 detected correctly for non-existent slug")


# ---------------------------------------------------------------------------
# Test 7: Full dry-run scrape of 1 page returns correct structure
# ---------------------------------------------------------------------------

def test_dry_run_one_page():
    """Full dry-run of 1 page returns dict with expected keys and no errors."""
    from scrapers.arutz_meir_scraper import scrape_arutz_meir
    result = scrape_arutz_meir(dry_run=True, max_pages=1, flaresolverr_port=_FS_PORT)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    for key in ("created", "updated", "errors", "pages_fetched", "lessons_examined"):
        assert key in result, f"Missing key: {key}"
    assert result["errors"] == 0, f"Scrape had errors: {result['errors']}"
    assert result["pages_fetched"] == 1, f"Expected 1 page, got {result['pages_fetched']}"
    assert result["lessons_examined"] > 0, "No lessons examined"
    print(f"  ✓ Dry-run: {result['lessons_examined']} lessons examined, "
          f"{result['created']} created, {result['updated']} updated, 0 errors")


# ---------------------------------------------------------------------------
# Test 8: lastScrapedAt=now → 0 new lessons (incremental cutoff works)
# ---------------------------------------------------------------------------

def test_incremental_cutoff_returns_zero():
    """When lastScrapedAt is set to future, incremental mode finds nothing."""
    import firebase_admin
    from firebase_admin import firestore as fs
    from datetime import timezone

    try: firebase_admin.get_app()
    except ValueError: firebase_admin.initialize_app(options={"projectId": "tora-or"})
    db = fs.client()

    # Read current lastScrapedAt to restore after test
    src = db.collection('sources').where('originalId', '==', 2).limit(1).get()
    assert src, "sourceId=2 source doc not found"
    original_last = src[0].to_dict().get('lastScrapedAt')
    src_ref = src[0].reference

    # Set lastScrapedAt to far future
    future = "2099-01-01T00:00:00"
    src_ref.update({'lastScrapedAt': future})

    try:
        result = scrape_arutz_meir(dry_run=True, max_pages=1, flaresolverr_port=_FS_PORT)
        total = result.get('created', 0) + result.get('updated', 0)
        assert total == 0, f"Expected 0 new lessons with future lastScrapedAt, got {total}"
        print(f"  ✓ Incremental cutoff: 0 lessons when lastScrapedAt=future")
    finally:
        # Restore original lastScrapedAt
        src_ref.update({'lastScrapedAt': original_last})


# Import scrape_arutz_meir for test 7 and 8 at module level
from scrapers.arutz_meir_scraper import scrape_arutz_meir


# ---------------------------------------------------------------------------
# Test 9: new_lesson_details populated for created lessons
# ---------------------------------------------------------------------------

def test_new_lesson_details_populated():
    """Created lessons appear in new_lesson_details with title, date, vimeoId."""
    import firebase_admin
    from firebase_admin import firestore as fs
    from datetime import timezone

    try: firebase_admin.get_app()
    except ValueError: firebase_admin.initialize_app(options={"projectId": "tora-or"})
    db = fs.client()

    # Set lastScrapedAt far in the past so we get some lessons
    src = db.collection('sources').where('originalId', '==', 2).limit(1).get()[0]
    original_last = src.to_dict().get('lastScrapedAt')
    src.reference.update({'lastScrapedAt': '2026-05-24T00:00:00'})

    try:
        result = scrape_arutz_meir(dry_run=True, max_pages=1, flaresolverr_port=_FS_PORT)
        created = result.get('created', 0)
        details = result.get('new_lesson_details', [])

        if created > 0:
            assert len(details) == created, f"Expected {created} detail entries, got {len(details)}"
            for d in details:
                assert 'title' in d, "Missing title in new_lesson_details"
                assert 'date' in d, "Missing date in new_lesson_details"
            print(f"  ✓ {created} created lessons, {len(details)} detail entries")
            print(f"  Sample: {details[0]['title'][:50]} [{details[0]['date']}] vimeoId={details[0].get('vimeoId')}")
        else:
            print(f"  ✓ No new lessons in this 1-page window (correct if up to date)")
    finally:
        src.reference.update({'lastScrapedAt': original_last})


# ---------------------------------------------------------------------------
# Test 10: Telegram notification includes lesson details
# ---------------------------------------------------------------------------

def test_telegram_notification_includes_details():
    """notify_scrape_results formats Arutz Meir lesson details correctly."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../../functions')
    from utils.telegram_notifier import notify_scrape_results
    import unittest.mock as mock

    fake_result = {
        'scrapers_run': 'arutz_meir',
        'duration_seconds': 60,
        'results': {
            'arutz_meir': {
                'created': 2,
                'updated': 0,
                'errors': 0,
                'pages_fetched': 1,
                'sample_lessons': [],
                'new_lesson_details': [
                    {'title': 'שיעור ראשון', 'date': '2026-05-25', 'vimeoId': '123456', 'siteAudioUrl': 'https://mp3.meirtv.co.il/wp2/1.mp3'},
                    {'title': 'שיעור שני', 'date': '2026-05-25', 'vimeoId': None, 'siteAudioUrl': 'https://mp3.meirtv.co.il/wp2/2.mp3'},
                ],
            }
        }
    }

    sent_messages = []
    with mock.patch('utils.telegram_notifier._send', side_effect=lambda token, text: sent_messages.append(text)):
        with mock.patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'fake_token'}):
            notify_scrape_results(fake_result)

    assert len(sent_messages) == 1, "Expected exactly 1 Telegram message"
    msg = sent_messages[0]
    assert 'שיעור ראשון' in msg, "First lesson title missing from message"
    assert 'שיעור שני' in msg, "Second lesson title missing from message"
    assert '🎥' in msg, "Video icon missing (lesson with vimeoId)"
    assert '🔊' in msg, "Audio icon missing (audio-only lesson)"
    assert '2026-05-25' in msg, "Date missing from message"
    print(f"  ✓ Telegram message contains all lesson details")
    print(f"  Message preview:\n{msg[:300]}")
