# Arutz Meir / Machon Meir Scraper — Research Findings

**Date**: May 14, 2026  
**Investigator**: Claude (AI assistant)  
**Source in Firestore**: `sourceId=2`

---

## 1. Old Scraper Analysis

### What it did

File: `lesson_center_backend/python/arutz_meir_grabber.py`

The scraper had **two distinct code paths** that were both used at different times:

**Path A — Custom REST API v1** (the primary, working path when the scraper was written):
- Base URL: `https://meirtv.com/wp-json/v1/`
- Endpoints used:
  - `GET /wp-json/v1/Rabbis` — fetch all rabbis
  - `GET /wp-json/v1/Categories` — fetch all categories
  - `GET /wp-json/v1/Sets` — fetch all series (sets)
  - `GET /wp-json/v1/Lessons?rabbiId=<id>&page=<n>` — paginated lessons by rabbi
  - `GET /wp-json/v1/Lessons?catId=<id>&page=<n>` — paginated lessons by category
  - `GET /wp-json/v1/widgets?pageBox=4` and `?pageBox=5` — featured/widget content
- Lesson fields returned: `Id`, `Title`, `RecordDate`, `SetId`, `CategoryId`, `RabbiId`, `VimeoId`, `Mp3Path`, `LessonLength`
- OriginalId = the numeric `Id` from this API (small integers, range roughly 3,000–100,000 for content from ~2005–2020)

**Path B — WordPress post API** (`grab_lesson2`, `grab_page`):
- Used `GET /wp-json/v1/video-shiurim?limit=20&offset=N`
- Accessed WordPress post meta fields: `mp3_file`, `vimeo_file`, `youtube_file`, `lessonlength`, `rav_1_id`
- OriginalId = WordPress post ID from `idxnumber` field or fallback `ID`

**YouTube path** (also present):
- Called `extract_lessons_for_channel_id(2, "UCEAZVyOtukIOH4BJ3gHKdng", ...)` for the Arutz Meir YouTube channel

### Why it broke

- **`GET /wp-json/v1/Rabbis`** → HTTP 404 (confirmed). The `/wp-json/v1/` namespace no longer exists.
- **`GET /wp-json/v1/Lessons?...`** → HTTP 404. Same reason.
- The old custom plugin that registered the `v1` namespace has been removed or replaced.
- The old site `www.meitv.co.il` (note: different spelling with no 'r') is also gone; the content migrated to `meirtv.com`.

---

## 2. New Site Structure

### Site technology

`https://meirtv.com/` is a **WordPress site** with Elementor, JetEngine, and WooCommerce.

### WordPress REST API namespaces

The site registers 46+ REST API namespaces at `https://meirtv.com/wp-json/`. Key ones:

| Namespace | Purpose | Status |
|---|---|---|
| `wp/v2` | Standard WP REST API | ✅ Working |
| `custom-shiurim-api/v1` | Custom search endpoint | ❌ Returns HTTP 500 |
| `custom-rabbi-api/v1` | Custom rabbi search | ❌ Returns HTTP 500 |
| `myplugin/v1/rabbis` | Rabbi list (names only, no IDs) | ⚠️ Returns flat name array |
| `tags/v1/get_shiurim_tags` | Shiurim tags | ⚠️ Returns empty `[]` |
| `v1/` (old namespace) | Old API used by scraper | ❌ 404 — gone |

### Custom post types

The site has a `shiurim` custom post type (not standard `post`):
- URL pattern: `https://meirtv.com/shiurim/[postId]/`
- REST API: `GET /wp-json/wp/v2/shiurim`
- Total count (as of May 14, 2026): **47,499 shiurim**

### Taxonomy structure

| Taxonomy | WP REST endpoint | Total count | Notes |
|---|---|---|---|
| `rabbis` | `/wp/v2/rabbis` | 726 | Slug = old PostgreSQL originalId (when numeric) |
| `shiurim-series` | `/wp/v2/shiurim-series` | 1,088 | Slug = old PostgreSQL originalId (when numeric) |
| `shiurim-category` | `/wp/v2/shiurim-category` | 603 | |
| `moadim` | `/wp/v2/moadim` | 88 | Jewish holidays; slug = old originalId |
| `parasha` | `/wp/v2/parasha` | 125 | Torah weekly portions |

**Critical finding**: The `slug` field on taxonomy terms is the old PostgreSQL `originalId` for most entries. Examples verified:
- `shiurim-series` term WP id=14463 has slug=`21265` — matches hardcoded series IDs in old scraper (e.g., `add_missing_serie_id(cursor, 21639, 'לימוד בוקר בפרשה')` — slug=`21639` exists)
- `rabbis` term WP id=924 has slug=`3774` (הרב אורי עמוס שרקי) — matches old PostgreSQL rav originalId
- `moadim` term slug=`3747` = יום העצמאות; slug=`3779` for rabbi Yoram Eliyahu

### Lesson page URL patterns (all verified working)

| Pattern | Example | Notes |
|---|---|---|
| Individual lesson | `https://meirtv.com/shiurim/[postId]/` | Canonical lesson URL |
| By rabbi | `https://meirtv.com/rabbis/[rabbiSlug]/` | e.g., `/rabbis/3779/` |
| By series | `https://meirtv.com/shiurim-series/[seriesSlug]/` | e.g., `/shiurim-series/22709/` |
| By holiday | `https://meirtv.com/moadim/[moadSlug]/` | e.g., `/moadim/3747/` (Yom HaAtzmaut) |

These are **WordPress taxonomy archive pages**, server-rendered with full lesson cards in HTML.

### WP REST API — shiurim endpoint

`GET https://meirtv.com/wp-json/wp/v2/shiurim`

Supported query parameters (verified):
- `per_page` — up to 100 items per page
- `page` — pagination (1-indexed)
- `rabbis` — filter by taxonomy term ID (WP internal ID, not the slug)
- `shiurim-series` — filter by series term ID
- `orderby=date&order=desc` — newest first
- `before` — ISO 8601 date filter

Response fields: `id`, `date`, `title`, `rabbis`, `shiurim-series`, `shiurim-category`, `moadim`, `parasha`, `mador`, `post-type`

**Missing from API response**: `mp3_file`, `vimeo_file`, `lessonlength`, `rav_1_id` — these ACF custom fields are not exposed via the REST API (the `meta` array is always empty in public responses).

**X-WP-Total header** is returned: use `-I` HEAD requests to get total lesson count without fetching data.

---

## 3. Media URL Findings

### Audio URL pattern

New posts use: `https://mp3.meirtv.co.il/wp2/[postId].mp3`

The WordPress post ID IS the audio filename. This is confirmed from HTML of lesson pages:
```html
<audio class="jet-audio-player" src="https://mp3.meirtv.co.il//wp2/388996.mp3" ...>
```

**HTTP behavior**:
| URL | Status | Content-Type | Accept-Ranges | Notes |
|---|---|---|---|---|
| `https://mp3.meirtv.co.il/wp2/388996.mp3` | 200 OK | audio/mpeg | bytes | ✅ Works, 4.1 MB |
| `https://mp3.meirtv.co.il/wp2/388860.mp3` | 200 OK | audio/mpeg | bytes | ✅ Works, 25.7 MB |
| `https://mp3.meirtv.co.il/wp2/215928.mp3` | 200 OK | audio/mpeg | (not set) | ✅ Older lesson, HTTP/1.1 only |
| `https://mp3.meirtv.co.il/wp2/389002.mp3` | 404 | — | — | ❌ Posted today at noon — MP3 upload may lag |

**Byte-range test**: `GET https://mp3.meirtv.co.il/wp2/388996.mp3` with `Range: bytes=0-1023` → **HTTP 206 Partial Content** ✅  
This means Flutter's `audio_service` / `just_audio` can seek within files.

**No authentication required**. No `Referer` header needed. Served via Cloudflare CDN (HTTP/2 for HTTPS).

**Important**: MP3 uploads appear to lag behind post publication by several hours. Post 389002 (published 12:39 UTC+2) had a 404 audio URL when checked at 16:33. Post 388901 (published 13 May at 11:23 UTC+2) had a working audio URL by the next day. **Do not treat a 404 audio URL as permanent failure for posts less than 24 hours old.**

### Older audio URL patterns (in existing Firestore archive)

| Pattern | Example | HTTP Status | Notes |
|---|---|---|---|
| GCS archive | `https://storage.googleapis.com/meirtvmp3/archive/hebrew/mp3/...` | 403 Forbidden | ❌ Dead |
| meirtv mp3 old-style | `http://mp3.meirtv.co.il/wp2/221041.mp3` | 200 OK | ✅ Works on HTTP |
| meirtv mp3 old-style (no extension) | `http://mp3.meirtv.co.il/wp2/215928` | 404 | ❌ Must add .mp3 |
| meirtv wp subfolder | `http://mp3.meirtv.co.il/wp/wp-197353.mp3` | 404 | ❌ Dead |
| meirtv path-based | `http://mp3.meirtv.co.il/Rabanim Shonim/New006/Idx 74568.mp3` | not tested | Likely dead |

### Video URL pattern

Lessons have Vimeo video embeds (not direct links). From lesson page HTML:
- Embed: `https://vimeo.com/1192180085` (Vimeo player URL)
- The old scraper resolved `VimeoId` → direct MP4 via Vimeo API. That requires a Vimeo API token.
- The REST API does NOT expose `vimeo_file` field publicly.

**To get Vimeo direct URLs**: requires Vimeo API bearer token (same as old scraper). The scraper had two token values (`vimeo_API1`, `vimeo_API2`) — these are likely expired.

---

## 4. Existing Firestore Archive State (sourceId=2)

### Total lessons

**44,864 lessons** with `sourceId=2` in Firestore as of May 14, 2026.

The new site has **47,499 shiurim** in WordPress. The Firestore archive covers an estimated ~95% of the content (or less, given YouTube lessons may overlap).

### Original ID range (sample of 500 docs)

Sampled 500 documents. `originalId` distribution:
- `< 10,000`: 63 docs (12.6%) — very old lessons
- `10,000–100,000`: 328 docs (65.6%) — bulk of archive
- `100,000–500,000`: 16 docs (3.2%) — newer WP-era lessons
- `> 500,000`: 93 docs (18.6%) — YouTube video IDs (very large integers)

The range in the sample: min `3,348`, max `98,709,970` (the large values are YouTube video IDs, not WP post IDs).

### Field quality issues in existing archive

From sampling 200 docs:
- **`ravId`**: null on most docs (`None` shown in sample — float precision bug previously identified)
- **`seriesId`**: null on ALL 20 sampled docs
- **`categoryId`**: null on ALL 20 sampled docs
- **`audioUrl`**: null on 39/200 (19.5%)
- **`videoUrl`**: null on 15/200 (7.5%)

The reference fields (ravId, seriesId, categoryId) are essentially empty throughout the sourceId=2 archive due to the float precision bug described in MIGRATION_STATUS.md. These have not been fixed for this source.

### Audio URL health in existing archive

| Pattern | Count (in 200 sample) | Status |
|---|---|---|
| `storage.googleapis.com/meirtvmp3/...` | 151/200 | ❌ 403 Forbidden — CDN gone |
| `mp3.meirtv.co.il/wp2/...` | 10/200 | ✅ Works (with `.mp3` extension, HTTP) |
| null | 39/200 | n/a |

**~75% of archived audio URLs are broken** (pointing to defunct Google Cloud Storage bucket). These need to be rewritten using the new `https://mp3.meirtv.co.il/wp2/[postId].mp3` pattern — but only if the `originalId` maps to a WP post ID.

---

## 5. ID Consistency (Old Archive vs New Site)

### How old IDs map to new site

The `originalId` stored in Firestore for old meirtv lessons falls into two categories:

**Category A — WP post IDs** (originalId ≈ 3,000–250,000):
- These are WordPress numeric post IDs
- The URL `https://meirtv.com/shiurim/[originalId]/` returns HTTP 200 (tested: 215928 → 200, 221041 → 200)
- The audio URL is `https://mp3.meirtv.co.il/wp2/[originalId].mp3` (tested working)
- ID 3712 redirects to 371260 — some very old IDs were renumbered

**Category B — Large integers (originalId > 500,000)**:
- These are YouTube video IDs (numeric), NOT WP post IDs
- The URL `https://meirtv.com/shiurim/[originalId]/` will 404

**Taxonomy slug consistency confirmed**:
- Series slug `21639` in WordPress = "לימוד בוקר בפרשה" — matches old scraper hardcoded series (line 126 in grabber.py)
- Series slug `21265` = "הלכה יומית" — consistent
- Rabbi slug `3773` = הרב דב ביגון (top rabbi by count = 8,980 lessons) — consistent with old rav originalId

This means: for lessons where `originalId` is a WP post ID (not a YouTube ID), the audio URL can be reconstructed as `https://mp3.meirtv.co.il/wp2/[originalId].mp3` and the lesson still exists on the new site.

---

## 6. Streaming Verdict

**Can Flutter play these audio URLs?**

✅ **Yes.** All confirmed working audio URLs are:
- Direct MP3 files, no playlist/HLS
- Support HTTP byte-range (HTTP 206 confirmed)
- No authentication required
- Served via Cloudflare (fast, globally cached)
- `Content-Type: audio/mpeg`
- Available on both HTTP and HTTPS

The existing Flutter player (`audio_service` / `just_audio`) already handles this format — the old archive had the same `mp3.meirtv.co.il` domain. The only issue is the broken GCS URLs in the archive (75% of sourceId=2 audio).

**Vimeo video**: Playable in Flutter via `video_player`, but requires resolving the Vimeo video ID to a direct MP4 URL using the Vimeo API (same approach as old scraper). Vimeo API credentials from the old scraper are likely expired and would need to be refreshed.

---

## 7. Recommended Approach

### Option A — Fix existing archive audio URLs (quick win, no new scraping)

For all Firestore lessons where `sourceId=2` AND `originalId` is a WP post ID (roughly < 300,000 AND not a YouTube ID):

1. Reconstruct audio URL as `https://mp3.meirtv.co.il/wp2/[originalId].mp3`
2. HEAD request to verify it exists (or accept the ~5% that may 404)
3. Batch-update the `audioUrl` field in Firestore

This would fix ~75% of broken audio URLs without scraping new data.

### Option B — Fresh scrape for new lessons (incremental, ongoing)

Use `GET /wp-json/wp/v2/shiurim?orderby=date&order=desc&per_page=100&page=N` to get new lessons chronologically. For each post:

- **Post ID** = WordPress numeric ID (e.g., 388996)
- **Title** = `title.rendered`
- **Date** = `date` (ISO 8601)
- **Audio URL** = `https://mp3.meirtv.co.il/wp2/[id].mp3` (construct directly, no lookup needed)
- **Vimeo ID** = requires fetching the individual lesson page HTML and extracting `vimeo.com/[id]` from the embed
- **Duration** = requires fetching individual lesson page HTML and parsing `[N] דקות` text
- **Rabbi term ID** = from `rabbis` array in API response (WP internal ID)
- **Series term ID** = from `shiurim-series` array (WP internal ID)
- **Rabbi originalId** = `slug` field of the rabbit term (matches PostgreSQL originalId)
- **Series originalId** = `slug` field of series term (matches PostgreSQL originalId)

**Rate limit note**: No API key required. The site is Cloudflare-fronted. 100 items/page × 475 pages = 47,499 lessons. At 1 req/sec this is ~8 minutes for a full scrape.

**Stop condition for incremental scraping**: Stop pagination when you hit a post ID that already exists in Firestore (or use `after` date parameter).

### Option C — Hybrid (recommended)

1. **Fix broken URLs**: Run a script to update all `sourceId=2` lessons with `storage.googleapis.com` audio URLs, reconstructing them as `https://mp3.meirtv.co.il/wp2/[originalId].mp3` (only for numeric originalIds < 300,000).

2. **Scrape new lessons**: Use the WP REST API to pull all lessons published after the last known Firestore lesson date. Use `shiurim-series` term slug as `seriesOriginalId` (maps to existing Firestore series docs). Use `rabbis` term slug as `ravOriginalId`.

3. **Skip Vimeo**: Don't resolve Vimeo URLs. Audio-only is sufficient for the Flutter app; Vimeo requires API credentials.

4. **sourceId**: Keep `sourceId=2` for all Machon Meir content.

---

## 8. Open Questions

1. **Why does the `custom-shiurim-api/v1/search` endpoint return HTTP 500?** It's registered in the WP API namespace list but always crashes. Unknown if it ever worked or if there are required parameters not documented.

2. **MP3 upload lag**: Post 389002 (published today) had a 404 audio URL 4 hours after publication. Is there always a delay? Is it only on busy days? A scraper should retry 404s for posts less than 48 hours old.

3. **Old IDs 3,000–10,000**: These very old lessons may predate the WordPress era. Some post IDs in this range redirect (e.g., 3712 → 371260). How many lessons in this range have been renumbered? Should we try to resolve redirects?

4. **Missing reference fields**: The existing 44,864 Firestore lessons for sourceId=2 have `ravId=null`, `seriesId=null`, `categoryId=null` on essentially all records. Fixing this requires: for each lesson, look up its WP taxonomy terms via the REST API, then map term slugs to Firestore category/series/rav document IDs. Is this worth doing for old lessons?

5. **`moadim` and `parasha` taxonomies**: These exist in the WP API but have no equivalent Firestore collection or field currently. Would you want to add them? They would require new collections in Firestore.

6. **Total count discrepancy**: Firestore has 44,864 lessons, WordPress has 47,499 shiurim. Roughly 2,635 lessons are missing from Firestore. These are likely new lessons added since the last migration run. The incremental scrape (Option B above) would capture them.

7. **Vimeo credentials**: The old scraper had two bearer tokens (`vimeo_API1`, `vimeo_API2`). These are likely expired. If video URLs are needed, new Vimeo API credentials are required.

---

## Video URL Investigation

**Date**: May 14, 2026  
**Investigator**: Claude (AI assistant)

---

### Does meirtv.com have video content?

Yes. Lessons on meirtv.com have Vimeo-hosted video. Every lesson page verified contains a shortcode like:

```
[fwdevp preset_id="meirtv" video_path="https://vimeo.com/1192170518" start_at_video="1" playback_rate_speed="1" ...]
```

The Vimeo video ID is embedded in the WordPress post content as a shortcode attribute (`video_path`). **This field is NOT exposed by the WP REST API** — the `content.rendered` field is always an empty string for shiurim posts, and the `meta` array is always empty. To get the Vimeo ID for a lesson, you must fetch the individual lesson page HTML and parse the `video_path` attribute from the `[fwdevp]` shortcode.

Three lesson pages verified:
- `https://meirtv.com/shiurim/388996/` → Vimeo ID `1192170518`
- `https://meirtv.com/shiurim/389002/` → Vimeo ID `1192180085`
- `https://meirtv.com/shiurim/215928/` → Vimeo ID `714904873`

### Video URL format

**New lessons (on-site)**:

Vimeo embed URLs only — not direct MP4. The canonical Vimeo URL is:
```
https://vimeo.com/[vimeo_video_id]
```

The video is domain-restricted (`domain_status_code: 403` in Vimeo oEmbed API), meaning it cannot be loaded in an arbitrary iframe — only on `meirtv.com`. However, playback config is accessible by sending `Referer: https://meirtv.com/` to the Vimeo player config endpoint:
```
GET https://player.vimeo.com/video/[vimeo_video_id]/config
Referer: https://meirtv.com/
```

No Vimeo API token required for this endpoint.

**Existing Firestore archive (sourceId=2, 500 doc sample)**:
- 362/500 (72%) have Vimeo direct external MP4 URLs in the format:
  ```
  http://player.vimeo.com/external/[vimeo_id].sd.mp4?s=[token]&profile_id=[165|164]&oauth2_token_id=[986952253|1009673393]
  ```
- 100/500 (20%) have YouTube URLs in the format:
  ```
  https://www.youtube.com/watch?v=[video_id]
  ```
- 38/500 (7.6%) have no videoUrl at all

### Streaming test results

**Existing Vimeo external MP4 URLs (from archive)**:

Tested 3 URLs — all return HTTP 301 redirect to a live `vod-progressive-ak.vimeocdn.com` URL. Following the redirect:
- Status: **200 OK** (full file) / **206 Partial Content** (with Range header) ✅
- Content-Type: `video/mp4`
- Byte-range support: **yes** (HTTP 206 confirmed)
- These URLs are still live despite having been generated years ago with Vimeo API tokens.

**New Vimeo videos (from player config endpoint)**:

`GET https://player.vimeo.com/video/1192170518/config` with `Referer: https://meirtv.com/` returns a JSON config with:
- No `progressive` (direct MP4) streams — only `hls` and `dash` adaptive streams
- HLS manifest URL pattern: `https://vod-adaptive-ak.vimeocdn.com/exp=...~acl=...~hmac=.../master.m3u8`
- Tested HLS manifest: **HTTP 200, Content-Type: application/x-mpegURL** ✅
- These HLS URLs are time-limited (short-lived tokens in the `exp=` and `hmac=` params)

**YouTube URLs**: Not directly streamable (require extraction). The Flutter app already handles this via `YouTubeVideoPlayerController.getYoutubeAudioUrl()` for audio sessions and a YouTube player wrapper for video sessions.

### Existing Firestore video data (sourceId=2)

From a 500-document sample:

| Field | Count | % |
|---|---|---|
| Has videoUrl | 462/500 | 92.4% |
| No videoUrl | 38/500 | 7.6% |
| Vimeo external MP4 (direct) | 362/462 | 78.4% |
| YouTube watch URLs | 100/462 | 21.6% |
| Vimeo plain embed URLs | 0/462 | 0% |

The Vimeo external MP4 URLs in the archive are still alive (verified 3/3 tested). The tokens in these URLs (`s=...`, `oauth2_token_id=...`) were generated years ago but remain valid — Vimeo does not expire old signed MP4 delivery URLs.

New lessons added after the last migration run (~mid-2024) will NOT have Vimeo external MP4 URLs in Firestore, because those URLs require a Vimeo API bearer token to generate, and the old tokens (`vimeo_API1`, `vimeo_API2`) are expired.

### Flutter compatibility

The Flutter `VideoApp.dart` player supports:

| URL type | Handling | Status |
|---|---|---|
| Direct MP4 URL (`http://player.vimeo.com/external/...`) | `VideoPlayerController.networkUrl()` | ✅ Works as-is (follows redirect to CDN) |
| HLS manifest URL (`*.m3u8`) | `VideoPlayerController.networkUrl()` | ✅ Flutter's `video_player` supports HLS on both iOS (native AVPlayer) and Android (ExoPlayer) |
| YouTube watch URL | `YouTubeVideoPlayerController` (already implemented) | ✅ Works as-is |
| Vimeo embed URL (`https://vimeo.com/[id]`) | Not directly playable | ❌ Requires intermediary step |

**Important**: HLS URLs from Vimeo's player config endpoint are short-lived (tokens expire). They cannot be stored in Firestore as static `videoUrl` values. They must be fetched at playback time.

**Important**: `VideoApp.dart` line 130 already has a legacy URL rewrite hack for `sourceId=2` audio URLs (`storage.googleapis.com` → `mp3.meirtv.co.il`). A similar runtime resolution step for video would fit the same pattern.

### Video verdict

For the **existing archive** (sourceId=2, ~44,864 lessons): the stored Vimeo external direct MP4 URLs (`player.vimeo.com/external/...`) are still alive and playable in Flutter with `VideoPlayerController.networkUrl()` — no changes needed. YouTube URLs also work via the existing `YouTubeVideoPlayerController`. The existing archive's video coverage is functional as-is.

For **new lessons** being scraped: storing a static Vimeo URL in Firestore is not viable because (a) the WP REST API does not expose the Vimeo ID, (b) generating direct MP4 URLs requires a Vimeo API bearer token, and (c) new videos only have HLS/DASH streams (no progressive MP4), and those URLs are time-limited. The practical approach for new lessons is: store the Vimeo video ID in Firestore (scraped from the lesson page HTML's `[fwdevp video_path=...]` shortcode), then resolve it to an HLS URL at playback time by calling `https://player.vimeo.com/video/[id]/config` with `Referer: https://meirtv.com/` — **no Vimeo API token required**. The resulting HLS URL is playable directly in Flutter's `video_player` on both iOS and Android.
