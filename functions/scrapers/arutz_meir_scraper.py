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

import json
import logging
import re
import time
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlencode

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
_PAGE_SLEEP = 1.0
_LESSON_SLEEP = 1.0

# GCS bucket prefix that marks dead audio URLs
_BROKEN_AUDIO_PREFIX = "https://storage.googleapis.com"

# FlareSolverr session name
_FS_SESSION = "arutz_meir_scraper"
_FS_PORT = 8191  # overridden by scrape_arutz_meir(flaresolverr_port=...)


# ---------------------------------------------------------------------------
# FlareSolverr helpers — replaces plain requests (Cloudflare-blocked)
# ---------------------------------------------------------------------------

def _fs_raw(url: str, port: int = _FS_PORT) -> tuple[str | None, int, dict]:
    """Fetch URL via FlareSolverr. Returns (body, status_code, headers)."""
    try:
        resp = requests.post(
            f'http://localhost:{port}/v1',
            json={'cmd': 'request.get', 'url': url, 'session': _FS_SESSION, 'maxTimeout': 60000},
            timeout=75,
        )
        sol = resp.json().get('solution', {})
        headers = {k.lower(): v for k, v in sol.get('headers', {}).items()}
        return sol.get('response'), sol.get('status', 0), headers
    except Exception as e:
        logger.error(f'FlareSolverr error fetching {url}: {e}')
        return None, 0, {}


def _fs_json(url: str, port: int = _FS_PORT) -> tuple[dict | list | None, int, dict]:
    """
    Fetch a JSON API endpoint via FlareSolverr.
    Chrome wraps JSON responses in <html><body><pre>...</pre></body></html>,
    so we extract the content of the <pre> tag.
    """
    body, status, headers = _fs_raw(url, port)
    if status == 200 and body:
        # Try raw JSON first
        stripped = body.strip()
        if stripped.startswith(('{', '[')):
            try:
                return json.loads(stripped), status, headers
            except json.JSONDecodeError:
                pass
        # Chrome wraps JSON in <pre> tag
        pre_match = re.search(r'<pre[^>]*>([\s\S]*?)</pre>', body)
        if pre_match:
            try:
                return json.loads(pre_match.group(1)), status, headers
            except json.JSONDecodeError as e:
                logger.error(f'JSON parse error in <pre> for {url}: {e}')
        else:
            logger.error(f'No JSON or <pre> found in response for {url}: {body[:100]!r}')
    return None, status, headers


def _fs_html(url: str, port: int = _FS_PORT, min_size: int = 250_000) -> tuple[str | None, int]:
    """
    Fetch an HTML page via FlareSolverr.
    Returns (html, status). Returns (None, status) for partial renders (<min_size bytes)
    or WP 404 pages (error404 in body class).
    """
    for attempt in range(3):
        body, status, _ = _fs_raw(url, port)
        if status != 200 or not body:
            return None, status
        if re.search(r'<body[^>]+class="[^"]*error404', body):
            return None, 404  # WP 404 served as HTTP 200 via Cloudflare
        if len(body) < min_size:
            logger.debug(f'Partial render {len(body)}B for {url}, attempt {attempt + 1}/3, retrying')
            continue
        return body, 200
    return None, 200  # all retries returned partial render


def check_flaresolverr(port: int = _FS_PORT) -> bool:
    """Return True if FlareSolverr is reachable."""
    try:
        r = requests.get(f'http://localhost:{port}/', timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def create_fs_session(port: int = _FS_PORT):
    """Create a persistent FlareSolverr session (reuses CF cookies)."""
    try:
        r = requests.post(f'http://localhost:{port}/v1',
                          json={'cmd': 'sessions.create', 'session': _FS_SESSION}, timeout=30)
        logger.info(f'FlareSolverr session: {r.json().get("message", "")}')
    except Exception as e:
        logger.warning(f'FlareSolverr session create failed (may already exist): {e}')


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
    Extract Vimeo video ID from the player iframe in lesson page HTML.
    Matches: src="https://player.vimeo.com/video/ID?..."
    """
    match = re.search(r'player\.vimeo\.com/video/(\d+)', html)
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
        # Slug fallback was used — try to find an existing doc by title to avoid duplicates.
        # Only treat as the same lesson if the date also matches — daily/recurring series
        # (e.g. "הלכה יומית") have the same title every episode but different dates.
        doc_ref, existing_data = _find_existing_by_title(db, title, collection_prefix)
        if doc_ref and existing_data:
            existing_date = existing_data.get("dateStr", "")
            new_date = lesson_data.get("dateStr", "")
            if existing_date != new_date:
                # Different date → different episode of a recurring series → create new
                logger.info(
                    f"[TITLE DEDUP] Skipped — same title but different date "
                    f"(existing={existing_date}, new={new_date}) title='{title[:50]}'"
                )
                doc_ref, existing_data = None, None
            else:
                stats["title_fallback_hit"] = stats.get("title_fallback_hit", 0) + 1
                logger.info(
                    f"[TITLE DEDUP] Found existing doc via title+date match for "
                    f"originalId={original_id} title='{title[:50]}' date={new_date}"
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
        if doc_ref:
            stats["_to_embed"].append(doc_ref.id)
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
            stats["_to_embed"].append(str(lesson_id))
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
    start_page: int | None = None,
    end_page: int | None = None,
    worker_id: int = 0,
    flaresolverr_port: int = 8191,
) -> dict:
    """
    Main entry point for the Arutz Meir WordPress scraper.

    Args:
        collection_prefix: Firestore collection prefix (e.g. "test_").
        dry_run: If True, log what would be written but make no Firestore writes.
        max_pages: Limit number of WP API pages to fetch (None = all).
        oldest_first: If True, fetch lessons in ascending ID order (oldest first).
        start_page: Start from this page (overrides checkpoint). For parallel workers.
        end_page: Stop after this page. For parallel workers.
        worker_id: Worker ID for logging (default 0 = single worker).

    Returns:
        dict with scraping statistics.
    """
    from utils.firestore_helper import FirestoreConnection as _FC

    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)

    def _log(msg):
        logger.info(msg)
        print(msg, flush=True)

    fs_port = flaresolverr_port
    global _FS_PORT
    _FS_PORT = fs_port

    # Preflight: FlareSolverr must be running
    if not check_flaresolverr(fs_port):
        raise RuntimeError(
            f"FlareSolverr is not running on port {fs_port}. "
            f"Start it with: docker run -d --name flaresolverr -p {fs_port}:8191 "
            f"ghcr.io/flaresolverr/flaresolverr:latest"
        )
    create_fs_session(fs_port)
    _log(f"[ARUTZ MEIR] FlareSolverr ready on port {fs_port}")
    _log(f"[ARUTZ MEIR] Starting scraper dry_run={dry_run} max_pages={max_pages}")

    # Initialize Firestore
    _log("[ARUTZ MEIR] Initializing Firestore connection...")
    conn = _FC(collection_prefix=collection_prefix)
    db = conn.db
    _log("[ARUTZ MEIR] Firestore connected")

    # Load taxonomy maps from Firestore
    _log("[ARUTZ MEIR] Loading taxonomy maps (ravs, series, categories)...")
    _load_taxonomy_maps(db, collection_prefix)
    _log("[ARUTZ MEIR] Taxonomy maps loaded")

    # Determine incremental start: read lastScrapedAt from sourceId=2 source doc
    _log("[ARUTZ MEIR] Looking up source doc...")
    sources_ref = db.collection(f"{collection_prefix}sources")
    source_query = sources_ref.where("originalId", "==", SOURCE_ID).limit(1).get()

    last_scraped_at = None
    source_doc_ref = None
    resume_from_page = 1

    if source_query:
        source_doc = source_query[0]
        source_doc_ref = source_doc.reference
        source_data = source_doc.to_dict()
        last_scraped_at = source_data.get("lastScrapedAt")
        # Page-level checkpoint: per-worker key so parallel workers don't collide
        ck_key = f"lastPageProcessed" if worker_id == 0 else f"lastPageProcessed_w{worker_id}"
        resume_from_page = source_data.get(ck_key) or (start_page or 1)
        if resume_from_page > 1:
            _log(f"[ARUTZ MEIR] W{worker_id} resuming from page {resume_from_page} (checkpoint)")
        _log(f"[ARUTZ MEIR] Source doc found, lastScrapedAt={last_scraped_at}")
    else:
        _log("[ARUTZ MEIR] No source doc found — full scrape mode")
        resume_from_page = start_page or 1

    # Build in-memory index of existing lessons for HTML skip optimization.
    # One bulk scan at startup avoids N per-lesson Firestore reads during scrape.
    _log("[ARUTZ MEIR] Loading existing lessons index for HTML skip optimization...")
    lessons_ref_idx = db.collection(f"{collection_prefix}lessons")
    existing_index = {}  # originalId -> {"siteAudioUrl": ..., "vimeoId": ...}
    last_idx_doc = None
    while True:
        q = lessons_ref_idx.where("sourceId", "==", SOURCE_ID).limit(500)
        if last_idx_doc:
            q = q.start_after(last_idx_doc)
        batch = list(q.stream())
        if not batch:
            break
        for doc in batch:
            d = doc.to_dict()
            oid = d.get("originalId")
            if oid is not None:
                existing_index[oid] = {
                    "siteAudioUrl": d.get("siteAudioUrl"),
                    "vimeoId": d.get("vimeoId"),
                }
        last_idx_doc = batch[-1]
        if len(batch) < 500:
            break
    _log(f"[ARUTZ MEIR] Loaded {len(existing_index)} existing lessons into index")

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
        "_to_embed": [],          # doc IDs of created/updated lessons
    }

    page = resume_from_page
    total_pages = None

    while True:
        if max_pages is not None and page > max_pages:
            logger.info(f"Reached max_pages={max_pages}, stopping")
            break
        if end_page is not None and page > end_page:
            _log(f"[ARUTZ MEIR] W{worker_id} reached end_page={end_page}, stopping")
            break

        params["page"] = page
        api_url = f"{SHIURIM_ENDPOINT}?{urlencode(params)}"
        lessons_page, api_status, api_headers = _fs_json(api_url, fs_port)
        if api_status != 200 or lessons_page is None:
            logger.error(f"Failed to fetch page {page}: status={api_status}")
            stats["errors"] += 1
            break

        if total_pages is None:
            # FlareSolverr doesn't pass HTTP headers through — use large sentinel,
            # rely on empty-page check to stop naturally.
            total_pages = 9999
            logger.info(f"WP API: paginating until empty page (headers not available via FlareSolverr)")

        if not lessons_page or not isinstance(lessons_page, list):
            logger.info(f"Empty page {page} (or WP error response), stopping")
            break

        stats["pages_fetched"] += 1
        print(f"[ARUTZ MEIR] Page {page}/{total_pages}: {len(lessons_page)} lessons examined={stats['lessons_examined']} created={stats['created']} updated={stats['updated']}", flush=True)

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

            # HTML skip: check in-memory index (O(1)) instead of Firestore read per lesson
            lesson_url = lesson_api.get("link", f"https://meirtv.com/shiurim/{wp_post_id}/")
            site_audio_url = None
            vimeo_id = None

            idx_entry = existing_index.get(original_id)
            already_has_audio = idx_entry and idx_entry.get("siteAudioUrl")
            already_has_vimeo = idx_entry and idx_entry.get("vimeoId")

            if already_has_audio and already_has_vimeo:
                # Both media fields already populated — skip HTML fetch entirely
                site_audio_url = idx_entry["siteAudioUrl"]
                vimeo_id = idx_entry["vimeoId"]
                stats["skipped_html_fetch"] = stats.get("skipped_html_fetch", 0) + 1
            else:
                # Try both URL patterns: bare post ID first (new lessons), then shiur- slug
                html = None
                for candidate_url in [lesson_url, f"https://meirtv.com/shiurim/shiur-{original_id}/"]:
                    html, html_status = _fs_html(candidate_url, fs_port)
                    if html:
                        break
                if html:
                    site_audio_url = _extract_site_audio_url(html)
                    vimeo_id = _extract_vimeo_id(html)
                else:
                    logger.warning(f"Failed to fetch HTML for wp_id={wp_post_id}")
                time.sleep(_LESSON_SLEEP)

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

        # Save page checkpoint so restarts resume here instead of page 1
        if not dry_run and source_doc_ref:
            ck_key = f"lastPageProcessed" if worker_id == 0 else f"lastPageProcessed_w{worker_id}"
            source_doc_ref.update({ck_key: page})

        page += 1
        time.sleep(_PAGE_SLEEP)

    # Update lastScrapedAt only when NOT in oldest_first mode (historical backfill).
    # In oldest_first mode we clear lastPageProcessed but don't set lastScrapedAt
    # so subsequent runs continue in oldest_first until all pages are done.
    if not dry_run and source_doc_ref:
        update_data: dict = {
            "lastPageProcessed": None,  # clear page checkpoint on successful completion
            "updatedAt": datetime.now().isoformat(),
        }
        if not oldest_first:
            update_data["lastScrapedAt"] = datetime.now().isoformat()
        source_doc_ref.update(update_data)
        logger.info("Updated source doc: cleared page checkpoint" +
                    (", set lastScrapedAt" if not oldest_first else " (oldest_first mode — lastScrapedAt not updated)"))

    # Embed new/updated lessons for smart search
    if not dry_run and stats["_to_embed"]:
        from utils.embedder import embed_lessons_batch
        embed_lessons_batch(db, stats["_to_embed"], collection_prefix)

    # Refresh "ערוץ מאיר - אחרונים" label with 10 most recent lessons
    if not dry_run:
        _update_arutz_meir_label(db, collection_prefix)

    logger.info(
        f"Arutz Meir scraper done: "
        f"created={stats['created']} updated={stats['updated']} "
        f"broken_audio_nulled={stats['broken_audio_nulled']} "
        f"skipped_no_media={stats['skipped_no_media']} "
        f"slug_fallback={stats['slug_fallback']} "
        f"title_fallback_hit={stats.get('title_fallback_hit', 0)} "
        f"errors={stats['errors']} pages={stats['pages_fetched']}"
    )
    print(f"[ARUTZ MEIR] FINAL: created={stats['created']} updated={stats['updated']} slug_fallback={stats['slug_fallback']} title_fallback_hit={stats.get('title_fallback_hit',0)} errors={stats['errors']} pages={stats['pages_fetched']}", flush=True)
    return stats


def _update_arutz_meir_label(db, collection_prefix: str):
    """Refresh 'ערוץ מאיר - אחרונים' with the 10 most recent lessons."""
    from scrapers.bnei_david_scraper import _upsert_label

    SOURCE_ID = 2
    recent = (
        db.collection(f'{collection_prefix}lessons')
        .where('sourceId', '==', SOURCE_ID)
        .order_by('timestamp', direction='DESCENDING')
        .limit(10)
        .get()
    )
    lesson_ids = [str(d.id) for d in recent if d.exists]
    if lesson_ids:
        _upsert_label(
            db.collection(f'{collection_prefix}labels'),
            'ערוץ מאיר - אחרונים',
            SOURCE_ID,
            lesson_ids,
        )
        logger.info(f"✅ Label 'ערוץ מאיר - אחרונים' updated with {len(lesson_ids)} lessons")


# ---------------------------------------------------------------------------
# Taxonomy term resolution (WP internal term ID → Firestore doc ID)
# ---------------------------------------------------------------------------

# Per-run cache: (taxonomy, wp_term_id) -> firestore_doc_id or None
_term_doc_cache: dict[tuple[str, int], str | None] = {}

# Firestore collection name per taxonomy
_TAXONOMY_COLLECTION = {
    "rabbis":           "ravs",
    "shiurim-series":   "series",
    "shiurim-category": "categories",
}
# Name field per collection
_NAME_FIELD = {"ravs": "rav", "series": "serie", "categories": "category"}


def _resolve_term_id(
    wp_term_ids: list[int],
    taxonomy: str,
    orig_to_doc_map: dict[int, str],
    db,
    collection_prefix: str,
) -> str | None:
    """
    Resolve a WP term ID to a Firestore doc ID.
    If the term exists in the preloaded map: return immediately.
    If not: fetch from WP API, compute originalId, create Firestore doc if needed.
    """
    for wp_term_id in wp_term_ids:
        cache_key = (taxonomy, wp_term_id)
        if cache_key in _term_doc_cache:
            doc_id = _term_doc_cache[cache_key]
            if doc_id:
                return doc_id
            continue

        # Fetch term from WP via FlareSolverr
        term_data, term_status, _ = _fs_json(f"{BASE_URL}/{taxonomy}/{wp_term_id}", _FS_PORT)
        if term_status != 200 or term_data is None:
            logger.warning(f"Failed to fetch WP term {taxonomy}/{wp_term_id}: status={term_status}")
            _term_doc_cache[cache_key] = None
            continue
        term = term_data

        slug = term.get("slug", "")
        name = term.get("name", "")

        # Compute originalId and look up existing Firestore doc
        collection = _TAXONOMY_COLLECTION.get(taxonomy)
        if not collection:
            _term_doc_cache[cache_key] = None
            continue

        if slug.isdigit():
            if collection == "ravs":
                orig_id = int(slug)          # ravs: originalId = small int
            else:
                orig_id = get_hash_for_id(SOURCE_ID, int(slug))  # others: bigint hash
            doc_id = orig_to_doc_map.get(orig_id)
            if doc_id:
                _term_doc_cache[cache_key] = doc_id
                return doc_id
        else:
            orig_id = None  # non-numeric slug — genuinely new term

        # Not in map → create new Firestore doc
        from datetime import datetime
        name_field = _NAME_FIELD[collection]
        new_doc_id = f"{collection[:3]}_{wp_term_id}"  # e.g. rav_1248, ser_25402
        new_doc = {
            name_field:   name,
            "sourceId":   SOURCE_ID,
            "originalId": orig_id,
            "wpTermId":   wp_term_id,
            "totalCount": 0,
            "createdAt":  datetime.now().isoformat(),
            "updatedAt":  datetime.now().isoformat(),
        }
        doc_ref = db.collection(f"{collection_prefix}{collection}").document(new_doc_id)
        doc_ref.set(new_doc)
        orig_to_doc_map[orig_id] = new_doc_id  # update in-memory map
        logger.info(f"Created new {collection} doc {new_doc_id}: {name}")

        _term_doc_cache[cache_key] = new_doc_id
        return new_doc_id

    return None
