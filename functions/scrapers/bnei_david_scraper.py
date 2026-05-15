#!/usr/bin/env python3
"""
Bnei David WordPress Scraper for Firebase Cloud Functions

Scrapes lessons from https://bneidavid.org/wp-json/wp/v2/lessons
and upserts them to Firestore under sourceId=1.

Upsert logic:
- EXISTS (sourceId=1 + originalId): UPDATE vimeoId, scrapeSource, and any null taxonomy
  fields (ravId/seriesId/categoryId); never touch audioUrl.
- NOT EXISTS: CREATE full lesson doc.

Taxonomy is resolved from JSON mapping files (approved offline).
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from html import unescape

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.cloud.firestore import ArrayUnion

logger = logging.getLogger(__name__)

# Imported at module level so tests can patch scrapers.bnei_david_scraper.get_hash_for_id
try:
    from utils.firestore_helper import get_hash_for_id, FirestoreConnection
except ImportError:
    # Stub for unit tests that don't have the full package on the path
    FirestoreConnection = None  # type: ignore

    def get_hash_for_id(source_id: int, original_id: int) -> int:  # type: ignore
        import hashlib
        h = hashlib.md5(f"{source_id}_{original_id}".encode())
        return int(h.hexdigest(), 16) % 10 ** 18

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOURCE_ID = 1
BASE_URL = "https://bneidavid.org/wp-json/wp/v2"
LESSONS_ENDPOINT = f"{BASE_URL}/lessons"

# Mapping files are in functions/data/ so they deploy with the Cloud Function.
_FUNCTIONS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RAV_MAP_PATH = os.path.join(_FUNCTIONS_ROOT, "data", "bnei_david_ravs_mapping.json")
_SERIES_MAP_PATH = os.path.join(_FUNCTIONS_ROOT, "data", "bnei_david_series_mapping.json")

# Rate limits (seconds) — increased to be polite to bneidavid.org
_PAGE_SLEEP = 0.5
_LESSON_SLEEP = 0.5
_VIMEO_SLEEP = 0.2

# HTTP session with retry/backoff — bneidavid.org times out under load
def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1.5,       # waits: 1.5s, 3s, 6s, 12s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # bneidavid.org blocks Python's default User-Agent — send browser-like headers
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "he,en;q=0.5",
    })
    return session

_session = _make_session()

# ---------------------------------------------------------------------------
# Taxonomy maps (populated at startup)
# ---------------------------------------------------------------------------
# wp_rav_id -> firestore_doc_id (str) or None (means create_new)
_rav_map: dict[int, str | None] = {}
# wp_rav_id -> wp_name (for creating new docs)
_rav_names: dict[int, str] = {}
# Runtime cache for newly created rav doc IDs: wp_rav_id -> created_firestore_doc_id
_rav_created_cache: dict[int, str] = {}

# wp_series_id -> firestore_doc_id (str) or None (means create_new)
_series_map: dict[int, str | None] = {}
# wp_series_id -> wp_name (for creating new docs)
_series_names: dict[int, str] = {}
# Runtime cache for newly created series doc IDs
_series_created_cache: dict[int, str] = {}

# ---------------------------------------------------------------------------
# Category map loaded from Firestore at startup
# subject wp_id -> firestore category doc_id
_category_map: dict[int, str] = {}


def _load_taxonomy_maps():
    """Load rav and series maps from the approved JSON files."""
    global _rav_map, _rav_names, _series_map, _series_names

    with open(_RAV_MAP_PATH, encoding="utf-8") as f:
        rav_entries = json.load(f)

    for entry in rav_entries:
        wp_id = entry["wp_id"]
        _rav_names[wp_id] = entry["wp_name"]
        if entry.get("firestore_doc_id") and entry.get("action") != "create_new":
            _rav_map[wp_id] = str(entry["firestore_doc_id"])
        else:
            _rav_map[wp_id] = None  # needs create_new

    with open(_SERIES_MAP_PATH, encoding="utf-8") as f:
        series_entries = json.load(f)

    for entry in series_entries:
        wp_id = entry["wp_id"]
        _series_names[wp_id] = entry["wp_name"]
        if entry.get("firestore_doc_id") and entry.get("action") != "create_new":
            _series_map[wp_id] = str(entry["firestore_doc_id"])
        else:
            _series_map[wp_id] = None  # needs create_new

    logger.info(
        f"Loaded rav map: {len(_rav_map)} entries "
        f"({sum(1 for v in _rav_map.values() if v)} confirmed, "
        f"{sum(1 for v in _rav_map.values() if not v)} create_new)"
    )
    logger.info(
        f"Loaded series map: {len(_series_map)} entries "
        f"({sum(1 for v in _series_map.values() if v)} confirmed, "
        f"{sum(1 for v in _series_map.values() if not v)} create_new)"
    )


def _load_category_map(db, collection_prefix=""):
    """
    Load Firestore categories for sourceId=1 and build wp_subject_id -> doc_id map.

    The categories collection stores originalId (PG integer) and category name.
    We match WP subject IDs via fetching /wp-json/wp/v2/subject/{id} and comparing
    the name against the Firestore category name.

    This is done lazily on first encounter of each subject ID to avoid fetching
    162 subjects up-front.
    """
    # Pre-load all sourceId=1 categories by name for fast lookup
    global _category_map
    cats_ref = db.collection(f"{collection_prefix}categories")
    docs = cats_ref.where("sourceId", "==", SOURCE_ID).get()
    # name -> doc_id
    _cat_name_to_doc_id = {}
    for doc in docs:
        d = doc.to_dict()
        name = d.get("category", "")
        if name:
            _cat_name_to_doc_id[name] = doc.id
    logger.info(f"Loaded {len(_cat_name_to_doc_id)} categories for sourceId=1")
    return _cat_name_to_doc_id


# ---------------------------------------------------------------------------
# HTML extraction helpers
# ---------------------------------------------------------------------------

def _extract_audio_file_id(html: str) -> str | None:
    """Extract stream_audio file_id from lesson page HTML."""
    match = re.search(r'action=stream_audio&(?:amp;)?file_id=([^"&\s]+)', html)
    if match:
        return match.group(1)
    return None


def _extract_vimeo_id(html: str) -> str | None:
    """Extract Vimeo video ID from lesson page HTML."""
    match = re.search(r'player\.vimeo\.com/video/(\d+)', html)
    if match:
        return match.group(1)
    return None


def _build_audio_url(file_id: str) -> str:
    return (
        f"https://bneidavid.org/wp-admin/admin-ajax.php"
        f"?action=stream_audio&file_id={file_id}"
    )


def _get_vimeo_duration(vimeo_id: str) -> int:
    """Fetch duration (seconds) from Vimeo oEmbed API. Returns 0 on failure."""
    try:
        r = _session.get(
            f"https://vimeo.com/api/oembed.json?url=https://vimeo.com/{vimeo_id}",
            timeout=45,
        )
        if r.status_code == 200:
            return int(r.json().get("duration", 0))
    except Exception as e:
        logger.warning(f"Vimeo oEmbed failed for {vimeo_id}: {e}")
    return 0


# ---------------------------------------------------------------------------
# Taxonomy resolution
# ---------------------------------------------------------------------------

def _get_rav_firestore_id(wp_rav_id: int, db, collection_prefix: str, dry_run: bool) -> str | None:
    """Resolve wp rav id -> Firestore doc id. Creates new doc if needed."""
    if wp_rav_id in _rav_created_cache:
        return _rav_created_cache[wp_rav_id]

    if wp_rav_id not in _rav_map:
        logger.warning(f"Unknown WP rav id {wp_rav_id} — not in mapping file, skipping")
        return None

    doc_id = _rav_map[wp_rav_id]
    if doc_id is not None:
        return doc_id

    # create_new: generate a new Firestore doc
    rav_name = _rav_names.get(wp_rav_id, f"rav_{wp_rav_id}")
    new_doc_id = f"rav_{wp_rav_id}"
    doc_data = {
        "originalId": wp_rav_id,
        "sourceId": SOURCE_ID,
        "rav": rav_name,
        "totalCount": 0,
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
    }
    if not dry_run:
        db.collection(f"{collection_prefix}ravs").document(new_doc_id).set(doc_data)
        logger.info(f"Created new rav doc {new_doc_id}: {rav_name}")
    else:
        logger.info(f"[DRY RUN] Would create rav doc {new_doc_id}: {rav_name}")

    _rav_created_cache[wp_rav_id] = new_doc_id
    return new_doc_id


def _get_series_firestore_id(wp_series_id: int, db, collection_prefix: str, dry_run: bool) -> str | None:
    """Resolve wp series id -> Firestore doc id. Creates new doc if needed."""
    if wp_series_id in _series_created_cache:
        return _series_created_cache[wp_series_id]

    if wp_series_id not in _series_map:
        logger.warning(f"Unknown WP series id {wp_series_id} — not in mapping file, skipping")
        return None

    doc_id = _series_map[wp_series_id]
    if doc_id is not None:
        return doc_id

    # create_new
    series_name = _series_names.get(wp_series_id, f"series_{wp_series_id}")
    new_doc_id = f"ser_bd_{wp_series_id}"
    doc_data = {
        "originalId": wp_series_id,
        "sourceId": SOURCE_ID,
        "serie": series_name,
        "totalCount": 0,
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
    }
    if not dry_run:
        db.collection(f"{collection_prefix}series").document(new_doc_id).set(doc_data)
        logger.info(f"Created new series doc {new_doc_id}: {series_name}")
    else:
        logger.info(f"[DRY RUN] Would create series doc {new_doc_id}: {series_name}")

    _series_created_cache[wp_series_id] = new_doc_id
    return new_doc_id


def _get_category_firestore_id(
    wp_subject_ids: list[int],
    cat_name_to_doc_id: dict,
    db,
    collection_prefix: str,
) -> str | None:
    """
    Resolve the first matching WP subject id to a Firestore category doc id.
    Fetches /wp-json/wp/v2/subject/{id} and matches by name against Firestore.
    """
    for wp_subject_id in wp_subject_ids:
        if wp_subject_id in _category_map:
            return _category_map[wp_subject_id]
        # Fetch the WP subject term to get its name
        try:
            r = _session.get(
                f"{BASE_URL}/subject/{wp_subject_id}",
                timeout=45,
            )
            if r.status_code == 200:
                term_name = r.json().get("name", "").strip()
                doc_id = cat_name_to_doc_id.get(term_name)
                if doc_id:
                    _category_map[wp_subject_id] = doc_id
                    return doc_id
                else:
                    logger.debug(f"Subject '{term_name}' (wp_id={wp_subject_id}) not in Firestore categories")
        except Exception as e:
            logger.warning(f"Failed to fetch WP subject {wp_subject_id}: {e}")
    return None


# ---------------------------------------------------------------------------
# Firestore upsert
# ---------------------------------------------------------------------------

def _upsert_lesson(
    lesson_data: dict,
    db,
    collection_prefix: str,
    dry_run: bool,
    stats: dict,
):
    """
    Check if lesson exists (sourceId=1, originalId=wp_post_id).
    If exists: UPDATE vimeoId, scrapeSource, and null taxonomy fields.
    If not: CREATE full lesson doc.

    Importantly: update() does NOT set audioUrl (preserves existing).
    """
    wp_post_id = lesson_data["originalId"]
    lessons_ref = db.collection(f"{collection_prefix}lessons")

    # Query for existing doc
    existing = (
        lessons_ref
        .where("sourceId", "==", SOURCE_ID)
        .where("originalId", "==", wp_post_id)
        .limit(1)
        .get()
    )

    if existing:
        # UPDATE path
        doc_ref = existing[0].reference
        existing_data = existing[0].to_dict()

        update_payload = {
            "streamAudioFileId": lesson_data.get("streamAudioFileId"),  # always set, even if None
            "vimeoId": lesson_data.get("vimeoId"),  # always set, even if None
            "scrapeSource": ArrayUnion(["new_site"]),
            "updatedAt": datetime.now().isoformat(),
        }

        # Only update taxonomy fields if currently null
        for field in ("ravId", "seriesId", "categoryId"):
            if existing_data.get(field) is None and lesson_data.get(field) is not None:
                update_payload[field] = lesson_data[field]

        if not dry_run:
            doc_ref.update(update_payload)
        else:
            logger.info(
                f"[DRY RUN] UPDATE wp_id={wp_post_id} "
                f"title='{lesson_data.get('title', '')[:50]}' "
                f"update={update_payload}"
            )

        stats["updated"] += 1
        return "updated"

    else:
        # CREATE path
        lesson_id = get_hash_for_id(SOURCE_ID, wp_post_id)
        doc = {
            "id": lesson_id,
            "originalId": wp_post_id,
            "sourceId": SOURCE_ID,
            "title": lesson_data["title"],
            "streamAudioFileId": lesson_data.get("streamAudioFileId"),
            "audioUrl": None,
            "vimeoId": lesson_data.get("vimeoId"),
            "videoUrl": None,
            "ravId": lesson_data.get("ravId"),
            "seriesId": lesson_data.get("seriesId"),
            "categoryId": lesson_data.get("categoryId"),
            "dateStr": lesson_data["dateStr"],
            "duration": lesson_data.get("duration", 0),
            "timestamp": lesson_data["timestamp"],
            "scrapeSource": ["new_site"],
            "createdAt": datetime.now().isoformat(),
            "updatedAt": datetime.now().isoformat(),
        }

        if not dry_run:
            lessons_ref.document(str(lesson_id)).set(doc)
        else:
            logger.info(
                f"[DRY RUN] CREATE wp_id={wp_post_id} "
                f"title='{lesson_data.get('title', '')[:50]}' "
                f"streamAudioFileId={lesson_data.get('streamAudioFileId')} "
                f"vimeoId={lesson_data.get('vimeoId')} "
                f"ravId={lesson_data.get('ravId')} "
                f"seriesId={lesson_data.get('seriesId')} "
                f"categoryId={lesson_data.get('categoryId')} "
                f"duration={lesson_data.get('duration', 0)}s"
            )

        stats["created"] += 1
        return "created"


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape_bnei_david(collection_prefix="", dry_run=False, max_pages=None):
    """
    Main entry point for the Bnei David WordPress scraper.

    Args:
        collection_prefix: Firestore collection prefix (e.g. "test_").
        dry_run: If True, log what would be written but make no Firestore writes.
        max_pages: Limit number of WP API pages to fetch (None = all).

    Returns:
        dict with scraping statistics.
    """
    from utils.firestore_helper import FirestoreConnection

    logger.info(f"Starting Bnei David scraper (dry_run={dry_run}, max_pages={max_pages})")

    # Initialize Firestore
    from utils.firestore_helper import FirestoreConnection as _FC
    conn = _FC(collection_prefix=collection_prefix)
    db = conn.db

    # Load taxonomy maps from JSON files
    _load_taxonomy_maps()

    # Load category name->doc_id map from Firestore
    cat_name_to_doc_id = _load_category_map(db, collection_prefix)

    # Determine incremental start: read lastScrapedAt from source doc
    sources_ref = db.collection(f"{collection_prefix}sources")
    source_query = sources_ref.where("originalId", "==", SOURCE_ID).limit(1).get()

    last_scraped_at = None
    source_doc_ref = None

    if source_query:
        source_doc = source_query[0]
        source_doc_ref = source_doc.reference
        last_scraped_at = source_doc.to_dict().get("lastScrapedAt")
        logger.info(f"Source doc found, lastScrapedAt={last_scraped_at}")
    else:
        logger.info("No source doc for sourceId=1 found — will do full scrape")

    # Build pagination parameters
    if last_scraped_at:
        # Incremental: newest-first so we can stop early when we see known posts
        params = {
            "per_page": 100,
            "orderby": "date",
            "order": "desc",
            "after": last_scraped_at,
        }
        logger.info(f"Incremental mode: fetching lessons after {last_scraped_at}")
    else:
        # First run: oldest-first so we can paginate forward chronologically
        params = {
            "per_page": 100,
            "orderby": "date",
            "order": "asc",
        }
        logger.info("Full scrape mode: fetching all lessons oldest-first")

    stats = {
        "created": 0,
        "updated": 0,
        "skipped_no_media": 0,
        "skipped_no_lesson_type": 0,
        "errors": 0,
        "pages_fetched": 0,
        "lessons_examined": 0,
        "sample_lessons": [],  # up to 3 detailed samples
    }

    page = 1
    total_pages = None

    while True:
        if max_pages is not None and page > max_pages:
            logger.info(f"Reached max_pages={max_pages}, stopping")
            break

        params["page"] = page
        try:
            response = _session.get(LESSONS_ENDPOINT, params=params, timeout=45)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch page {page}: {e}")
            stats["errors"] += 1
            break

        if total_pages is None:
            total_pages = int(response.headers.get("X-WP-TotalPages", 1))
            total_lessons = int(response.headers.get("X-WP-Total", 0))
            logger.info(f"WP API reports {total_lessons} lessons across {total_pages} pages")

        lessons_page = response.json()
        if not lessons_page:
            logger.info(f"Empty page {page}, stopping")
            break

        stats["pages_fetched"] += 1
        logger.info(f"Page {page}/{total_pages}: {len(lessons_page)} lessons")

        for lesson_api in lessons_page:
            stats["lessons_examined"] += 1
            wp_post_id = lesson_api["id"]

            # Skip lessons with no lesson_type (test/demo)
            lesson_type = lesson_api.get("lesson_type", [])
            if not lesson_type:
                logger.debug(f"Skipping wp_id={wp_post_id} (no lesson_type)")
                stats["skipped_no_lesson_type"] += 1
                continue

            # Parse title (strip HTML entities)
            title = unescape(lesson_api.get("title", {}).get("rendered", "")).strip()

            # Parse date
            date_str_raw = lesson_api.get("date", "")
            try:
                dt = datetime.fromisoformat(date_str_raw)
                date_str = dt.strftime("%Y-%m-%d")
                # WP dates are local time (Israel), treat as UTC for timestamp
                timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                date_str = date_str_raw[:10] if date_str_raw else ""
                timestamp = 0

            # Fetch lesson page HTML
            lesson_url = lesson_api.get("link", "")
            audio_file_id = None
            vimeo_id = None
            duration = 0

            try:
                html_response = _session.get(lesson_url, timeout=45)
                html = html_response.text

                audio_file_id = _extract_audio_file_id(html)
                vimeo_id = _extract_vimeo_id(html)

                # Get duration from Vimeo oEmbed if video present
                if vimeo_id:
                    time.sleep(_VIMEO_SLEEP)
                    duration = _get_vimeo_duration(vimeo_id)

                time.sleep(_LESSON_SLEEP)
            except Exception as e:
                logger.warning(f"Failed to fetch HTML for wp_id={wp_post_id}: {e}")

            if not audio_file_id and not vimeo_id:
                logger.debug(f"wp_id={wp_post_id} title='{title[:40]}' — no media found in HTML")
                stats["skipped_no_media"] += 1
                # Still upsert — the lesson exists in WP but uses old media format
                # (media-line CDN) — don't skip entirely, just set streamAudioFileId=None

            # Resolve taxonomy
            wp_rav_ids = lesson_api.get("rav", [])
            wp_series_ids = lesson_api.get("series", [])
            wp_subject_ids = lesson_api.get("subject", [])

            rav_id = None
            if wp_rav_ids:
                rav_id = _get_rav_firestore_id(wp_rav_ids[0], db, collection_prefix, dry_run)

            series_id = None
            if wp_series_ids:
                series_id = _get_series_firestore_id(wp_series_ids[0], db, collection_prefix, dry_run)

            category_id = None
            if wp_subject_ids:
                category_id = _get_category_firestore_id(
                    wp_subject_ids, cat_name_to_doc_id, db, collection_prefix
                )

            lesson_data = {
                "originalId": wp_post_id,
                "title": title,
                "streamAudioFileId": audio_file_id,  # raw file_id, NOT a URL
                "vimeoId": vimeo_id,
                "ravId": rav_id,
                "seriesId": series_id,
                "categoryId": category_id,
                "dateStr": date_str,
                "duration": duration,
                "timestamp": timestamp,
            }

            try:
                action = _upsert_lesson(lesson_data, db, collection_prefix, dry_run, stats)

                # Collect sample lessons for reporting
                if len(stats["sample_lessons"]) < 3:
                    stats["sample_lessons"].append({
                        "action": action,
                        "wp_post_id": wp_post_id,
                        "title": title,
                        "streamAudioFileId": audio_file_id,
                        "vimeoId": vimeo_id,
                        "ravId": rav_id,
                        "seriesId": series_id,
                        "categoryId": category_id,
                        "duration": duration,
                        "dateStr": date_str,
                    })
            except Exception as e:
                logger.error(f"Error upserting wp_id={wp_post_id}: {e}")
                stats["errors"] += 1

        if page >= total_pages:
            logger.info(f"Fetched all {total_pages} pages")
            break

        page += 1
        time.sleep(_PAGE_SLEEP)

    # Update lastScrapedAt on source doc (skip in dry_run)
    if not dry_run and source_doc_ref and (stats["created"] + stats["updated"]) > 0:
        source_doc_ref.update({
            "lastScrapedAt": datetime.now().isoformat(),
            "updatedAt": datetime.now().isoformat(),
        })
        logger.info("Updated lastScrapedAt on source doc")

    logger.info(
        f"Bnei David scraper done: "
        f"created={stats['created']} updated={stats['updated']} "
        f"skipped_no_media={stats['skipped_no_media']} "
        f"skipped_no_lesson_type={stats['skipped_no_lesson_type']} "
        f"errors={stats['errors']} pages={stats['pages_fetched']}"
    )
    return stats
