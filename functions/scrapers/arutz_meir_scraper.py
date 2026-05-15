#!/usr/bin/env python3
"""
Arutz Meir (meirtv.com) WordPress Scraper for Firebase Cloud Functions

Scrapes lessons from https://meirtv.com/wp-json/wp/v2/shiurim
and upserts them to Firestore under sourceId=2.

Upsert logic:
- EXISTS (sourceId=2 + originalId extracted from WP slug):
    UPDATE siteAudioUrl, vimeoId, scrapeSource, and any null taxonomy fields;
    null out audioUrl if it points to the defunct GCS bucket.
    Never touch videoUrl.
- NOT EXISTS: CREATE full lesson doc.

Taxonomy is resolved from Firestore at startup (term slug = originalId).
No JSON mapping files needed — meirtv.com WP taxonomy slugs are numeric originalIds.
"""

import logging
import re
import time
from datetime import datetime, timezone
from html import unescape

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.cloud.firestore import ArrayUnion

logger = logging.getLogger(__name__)

# Imported at module level so tests can patch scrapers.arutz_meir_scraper.get_hash_for_id
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
SOURCE_ID = 2
BASE_URL = "https://meirtv.com/wp-json/wp/v2"
SHIURIM_ENDPOINT = f"{BASE_URL}/shiurim"

# Rate limits (seconds)
_PAGE_SLEEP = 0.5
_LESSON_SLEEP = 0.5

# GCS bucket prefix that marks dead audio URLs
_BROKEN_AUDIO_PREFIX = "https://storage.googleapis.com"


# ---------------------------------------------------------------------------
# HTTP session with retry/backoff
# ---------------------------------------------------------------------------

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
    return session


_session = _make_session()


# ---------------------------------------------------------------------------
# Taxonomy maps — populated at startup from Firestore
# ---------------------------------------------------------------------------
# originalId (int) -> firestore doc_id (str)
_rav_map: dict[int, str] = {}
_series_map: dict[int, str] = {}
_category_map: dict[int, str] = {}


def _load_taxonomy_maps(db, collection_prefix: str) -> None:
    """
    Load all sourceId=2 ravs, series, and categories from Firestore.
    Term slug on WP = numeric originalId, so we key by originalId.
    """
    global _rav_map, _series_map, _category_map

    for collection_name, target_map, name_field in [
        ("ravs", _rav_map, "rav"),
        ("series", _series_map, "serie"),
        ("categories", _category_map, "category"),
    ]:
        ref = db.collection(f"{collection_prefix}{collection_name}")
        docs = ref.where("sourceId", "==", SOURCE_ID).get()
        for doc in docs:
            d = doc.to_dict()
            orig_id = d.get("originalId")
            if orig_id is not None:
                target_map[int(orig_id)] = doc.id
        logger.info(
            f"Loaded {len(target_map)} entries for {collection_name} (sourceId={SOURCE_ID})"
        )


# ---------------------------------------------------------------------------
# Slug / originalId extraction
# ---------------------------------------------------------------------------

def _extract_original_id_from_slug(slug: str) -> int | None:
    """
    Extract the originalId from a WP slug like 'shiur-10915'.
    Returns None if the slug does not match the expected pattern.
    """
    match = re.match(r'^shiur-(\d+)$', slug)
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# HTML extraction helpers
# ---------------------------------------------------------------------------

def _extract_site_audio_url(html: str) -> str | None:
    """
    Extract the audio URL from <audio src="..."> in lesson page HTML.
    Example: <audio class="jet-audio-player" src="https://mp3.meirtv.co.il//wp2/388996.mp3" ...>
    """
    match = re.search(r'<audio[^>]+\bsrc=["\']([^"\']+)["\']', html)
    if match:
        return match.group(1).strip()
    return None


def _extract_vimeo_id(html: str) -> str | None:
    """
    Extract Vimeo video ID from the [fwdevp video_path="https://vimeo.com/ID"] shortcode
    embedded in lesson page HTML.
    """
    match = re.search(r'\[fwdevp[^\]]*video_path=["\']https://vimeo\.com/(\d+)["\']', html)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Firestore upsert
# ---------------------------------------------------------------------------

def _find_existing_by_title(db, title: str, collection_prefix: str):
    """Fallback dedup: search by exact title for sourceId=2 lessons.
    Used only when slug-based originalId lookup fails.
    Returns (doc_ref, doc_data) or (None, None).
    """
    results = list(
        db.collection(f"{collection_prefix}lessons")
        .where("sourceId", "==", SOURCE_ID)
        .where("title", "==", title)
        .limit(1)
        .stream()
    )
    if results:
        return results[0].reference, results[0].to_dict()
    return None, None


def _upsert_lesson(
    lesson_data: dict,
    db,
    collection_prefix: str,
    dry_run: bool,
    stats: dict,
    is_slug_fallback: bool = False,
) -> str:
    """
    Check if lesson exists (sourceId=2, originalId).
    If exists: UPDATE siteAudioUrl, vimeoId, scrapeSource, null broken audioUrl,
               and any currently-null taxonomy fields. NEVER touch videoUrl.
    If not (and is_slug_fallback=True): try title-based dedup before creating.
    If not: CREATE full lesson doc.

    Returns 'created' or 'updated'.
    """
    original_id = lesson_data["originalId"]
    title = lesson_data.get("title", "")
    lessons_ref = db.collection(f"{collection_prefix}lessons")

    # Query for existing doc by originalId
    existing = (
        lessons_ref
        .where("sourceId", "==", SOURCE_ID)
        .where("originalId", "==", original_id)
        .limit(1)
        .get()
    )

    doc_ref = None
    existing_data = None

    if existing:
        doc_ref = existing[0].reference
        existing_data = existing[0].to_dict()
    elif is_slug_fallback and title:
        # Slug fallback was used — try to find an existing doc by title to avoid duplicates
        doc_ref, existing_data = _find_existing_by_title(db, title, collection_prefix)
        if doc_ref:
            stats["title_fallback_hit"] = stats.get("title_fallback_hit", 0) + 1
            logger.info(
                f"[TITLE DEDUP] Found existing doc via title match for "
                f"originalId={original_id} title='{title[:50]}'"
            )

    if doc_ref is not None and existing_data is not None:
        # UPDATE path
        update_payload = {
            "siteAudioUrl": lesson_data.get("siteAudioUrl"),
            "vimeoId": lesson_data.get("vimeoId"),
            "scrapeSource": ArrayUnion(["new_site"]),
            "updatedAt": datetime.now().isoformat(),
        }

        # Null out broken GCS audioUrl
        existing_audio = existing_data.get("audioUrl")
        if existing_audio and existing_audio.startswith(_BROKEN_AUDIO_PREFIX):
            update_payload["audioUrl"] = None
            stats["broken_audio_nulled"] = stats.get("broken_audio_nulled", 0) + 1

        # Only update taxonomy fields if currently null
        for field in ("ravId", "seriesId", "categoryId"):
            if existing_data.get(field) is None and lesson_data.get(field) is not None:
                update_payload[field] = lesson_data[field]

        if not dry_run:
            doc_ref.update(update_payload)
        else:
            logger.info(
                f"[DRY RUN] UPDATE originalId={original_id} "
                f"title='{title[:50]}' "
                f"siteAudioUrl={lesson_data.get('siteAudioUrl')} "
                f"vimeoId={lesson_data.get('vimeoId')} "
                f"audioUrl_nulled={'audioUrl' in update_payload}"
            )

        stats["updated"] += 1
        return "updated"

    else:
        # CREATE path
        lesson_id = get_hash_for_id(SOURCE_ID, original_id)
        doc = {
            "id": lesson_id,
            "originalId": original_id,
            "sourceId": SOURCE_ID,
            "title": title,
            "siteAudioUrl": lesson_data.get("siteAudioUrl"),
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
                f"[DRY RUN] CREATE originalId={original_id} "
                f"title='{title[:50]}' "
                f"siteAudioUrl={lesson_data.get('siteAudioUrl')} "
                f"vimeoId={lesson_data.get('vimeoId')} "
                f"ravId={lesson_data.get('ravId')} "
                f"seriesId={lesson_data.get('seriesId')} "
                f"categoryId={lesson_data.get('categoryId')}"
            )

        stats["created"] += 1
        return "created"


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape_arutz_meir(
    collection_prefix: str = "",
    dry_run: bool = False,
    max_pages: int | None = None,
    oldest_first: bool = False,
) -> dict:
    """
    Main entry point for the Arutz Meir WordPress scraper.

    Args:
        collection_prefix: Firestore collection prefix (e.g. "test_").
        dry_run: If True, log what would be written but make no Firestore writes.
        max_pages: Limit number of WP API pages to fetch (None = all).
        oldest_first: If True, fetch lessons in ascending ID order (oldest first).
                      Useful for verifying the update path on old content already in Firestore.

    Returns:
        dict with scraping statistics.
    """
    from utils.firestore_helper import FirestoreConnection as _FC

    logger.info(f"Starting Arutz Meir scraper (dry_run={dry_run}, max_pages={max_pages})")

    # Initialize Firestore
    conn = _FC(collection_prefix=collection_prefix)
    db = conn.db

    # Load taxonomy maps from Firestore
    _load_taxonomy_maps(db, collection_prefix)

    # Determine incremental start: read lastScrapedAt from sourceId=2 source doc
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
        logger.info("No source doc for sourceId=2 found — will do full scrape")

    # Build pagination parameters
    if oldest_first:
        params = {
            "per_page": 100,
            "orderby": "id",
            "order": "asc",
        }
        logger.info("Oldest-first mode: fetching lessons in ascending ID order")
    elif last_scraped_at:
        params = {
            "per_page": 100,
            "orderby": "date",
            "order": "desc",
            "after": last_scraped_at,
        }
        logger.info(f"Incremental mode: fetching lessons after {last_scraped_at}")
    else:
        params = {
            "per_page": 100,
            "orderby": "date",
            "order": "desc",
        }
        logger.info("Full scrape mode: fetching all lessons newest-first")

    stats = {
        "created": 0,
        "updated": 0,
        "broken_audio_nulled": 0,
        "skipped_no_media": 0,
        "slug_fallback": 0,       # lessons where slug didn't match shiur-{id}
        "title_fallback_hit": 0,  # slug fallback + title match found existing doc
        "errors": 0,
        "pages_fetched": 0,
        "lessons_examined": 0,
        "sample_lessons": [],     # up to 3 detailed samples
    }

    page = 1
    total_pages = None

    while True:
        if max_pages is not None and page > max_pages:
            logger.info(f"Reached max_pages={max_pages}, stopping")
            break

        params["page"] = page
        try:
            response = _session.get(SHIURIM_ENDPOINT, params=params, timeout=45)
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

            # Extract originalId from slug (e.g. "shiur-10915" → 10915)
            slug = lesson_api.get("slug", "")
            original_id = _extract_original_id_from_slug(slug)
            is_slug_fallback = False
            if original_id is None:
                # Fallback: use WP post ID as originalId
                original_id = wp_post_id
                is_slug_fallback = True
                stats["slug_fallback"] += 1
                logger.debug(f"Slug '{slug}' did not match shiur-{{id}} — using wp_post_id={wp_post_id} as originalId")

            # Parse title (strip HTML entities)
            title = unescape(lesson_api.get("title", {}).get("rendered", "")).strip()

            # Parse date
            date_str_raw = lesson_api.get("date", "")
            try:
                dt = datetime.fromisoformat(date_str_raw)
                date_str = dt.strftime("%Y-%m-%d")
                timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                date_str = date_str_raw[:10] if date_str_raw else ""
                timestamp = 0

            # Fetch lesson page HTML for audio URL and Vimeo ID
            lesson_url = lesson_api.get("link", f"https://meirtv.com/shiurim/{wp_post_id}/")
            site_audio_url = None
            vimeo_id = None

            try:
                html_response = _session.get(lesson_url, timeout=45)
                html = html_response.text

                site_audio_url = _extract_site_audio_url(html)
                vimeo_id = _extract_vimeo_id(html)

                time.sleep(_LESSON_SLEEP)
            except Exception as e:
                logger.warning(f"Failed to fetch HTML for wp_id={wp_post_id}: {e}")

            if not site_audio_url and not vimeo_id:
                logger.debug(f"wp_id={wp_post_id} title='{title[:40]}' — no media found in HTML")
                stats["skipped_no_media"] += 1

            # Resolve taxonomy from WP term IDs via slug → originalId mapping
            # WP API returns arrays of integer term IDs (internal WP IDs, NOT slugs)
            # We need to fetch each term to get its slug (= originalId)
            rav_id = _resolve_term_id(lesson_api.get("rabbis", []), "rabbis", _rav_map, db, collection_prefix)
            series_id = _resolve_term_id(lesson_api.get("shiurim-series", []), "shiurim-series", _series_map, db, collection_prefix)
            category_id = _resolve_term_id(lesson_api.get("shiurim-category", []), "shiurim-category", _category_map, db, collection_prefix)

            lesson_data = {
                "originalId": original_id,
                "title": title,
                "siteAudioUrl": site_audio_url,
                "vimeoId": vimeo_id,
                "ravId": rav_id,
                "seriesId": series_id,
                "categoryId": category_id,
                "dateStr": date_str,
                "duration": 0,  # duration not available without Vimeo API
                "timestamp": timestamp,
            }

            try:
                action = _upsert_lesson(lesson_data, db, collection_prefix, dry_run, stats, is_slug_fallback=is_slug_fallback)

                # Collect sample lessons for reporting
                if len(stats["sample_lessons"]) < 3:
                    stats["sample_lessons"].append({
                        "action": action,
                        "wp_post_id": wp_post_id,
                        "original_id": original_id,
                        "title": title,
                        "siteAudioUrl": site_audio_url,
                        "vimeoId": vimeo_id,
                        "ravId": rav_id,
                        "seriesId": series_id,
                        "categoryId": category_id,
                        "dateStr": date_str,
                        "scrapeSource": ["new_site"],
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
        f"Arutz Meir scraper done: "
        f"created={stats['created']} updated={stats['updated']} "
        f"broken_audio_nulled={stats['broken_audio_nulled']} "
        f"skipped_no_media={stats['skipped_no_media']} "
        f"slug_fallback={stats['slug_fallback']} "
        f"title_fallback_hit={stats.get('title_fallback_hit', 0)} "
        f"errors={stats['errors']} pages={stats['pages_fetched']}"
    )
    return stats


# ---------------------------------------------------------------------------
# Taxonomy term resolution (WP internal term ID → Firestore doc ID)
# ---------------------------------------------------------------------------

# Per-run cache: wp_term_id -> originalId (slug as int) or None
_term_slug_cache: dict[tuple[str, int], int | None] = {}


def _resolve_term_id(
    wp_term_ids: list[int],
    taxonomy: str,
    orig_to_doc_map: dict[int, str],
    db,
    collection_prefix: str,
) -> str | None:
    """
    Given a list of WP internal term IDs, resolve the first one to a Firestore doc ID.

    Strategy:
    1. Fetch the WP term via /wp/v2/{taxonomy}/{term_id} to get its slug.
    2. The slug is a numeric string = originalId in Firestore.
    3. Look up originalId in the pre-loaded map.
    """
    for wp_term_id in wp_term_ids:
        cache_key = (taxonomy, wp_term_id)
        if cache_key in _term_slug_cache:
            orig_id = _term_slug_cache[cache_key]
        else:
            orig_id = _fetch_term_original_id(taxonomy, wp_term_id)
            _term_slug_cache[cache_key] = orig_id

        if orig_id is not None:
            doc_id = orig_to_doc_map.get(orig_id)
            if doc_id:
                return doc_id
    return None


def _fetch_term_original_id(taxonomy: str, wp_term_id: int) -> int | None:
    """Fetch WP taxonomy term and return its slug as int (= originalId), or None."""
    try:
        r = _session.get(
            f"{BASE_URL}/{taxonomy}/{wp_term_id}",
            timeout=10,
        )
        if r.status_code == 200:
            slug = r.json().get("slug", "")
            if slug and slug.isdigit():
                return int(slug)
    except Exception as e:
        logger.warning(f"Failed to fetch WP term {taxonomy}/{wp_term_id}: {e}")
    return None
