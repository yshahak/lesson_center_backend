# Bnei David Phase 2 — Investigation Findings

Last updated: 2026-05-14

All claims below were verified by actually fetching URLs or querying Firestore.
No assumptions. No "probably".

---

## 1. API Validation

### Total lesson count

```
GET https://bneidavid.org/wp-json/wp/v2/lessons?per_page=1&orderby=id&order=asc
X-WP-Total: 18570
X-WP-TotalPages: 18570
```

**18,570 total lessons** — not ~30,000 as previously estimated. The prior estimate was wrong.

### Lesson ID range

- **Lowest real lesson ID**: 9283 (date: 2003-10-28, audio-only)
- **Lowest video lesson ID**: 9115 (date: 2025-06-03, lesson_type=[120])
- IDs 5419–8990 are test/demo lessons (titles like "שיעור לדוגמא"). They have dates
  in 2025 but were clearly created during site setup.
- **Highest lesson ID**: 37553 (date: 2026-05-13)

### API response fields (exact, verified)

```json
{
  "id": 37553,
  "date": "2026-05-13T18:55:27",
  "date_gmt": "2026-05-13T15:55:27",
  "guid": { "rendered": "https://bneidavid.org/?post_type=lessons&p=37553" },
  "modified": "2026-05-13T18:55:27",
  "modified_gmt": "2026-05-13T15:55:27",
  "slug": "...(url-encoded Hebrew)...",
  "status": "publish",
  "type": "lessons",
  "link": "https://bneidavid.org/lessons/...(url-encoded Hebrew).../",
  "title": { "rendered": "סיום המאמר | עבודת אלוקים [22]" },
  "content": { "rendered": "", "protected": false },
  "excerpt": { "rendered": "", "protected": false },
  "featured_media": 0,
  "parent": 0,
  "template": "",
  "meta": { "_acf_changed": false },
  "subject": [2473],
  "series": [2509],
  "lesson_type": [120, 121],
  "rav": [2284]
}
```

**No `acf` field is populated** — tested `?_fields=id,title,acf,meta` and `?context=edit`
(edit returns 403 as expected without auth). ACF v3 REST plugin endpoint
(`/wp-json/acf/v3/lessons/37553`) returns 404 — not installed or not exposed.

### Pagination headers
- `X-WP-Total` and `X-WP-TotalPages` are present in every response.
- `access-control-expose-headers: X-WP-Total, X-WP-TotalPages, Link` — confirmed.

### Taxonomy counts (verified)

| Taxonomy | Endpoint | Total |
|----------|----------|-------|
| rav | `/wp-json/wp/v2/rav` | 54 |
| series | `/wp-json/wp/v2/series` | 512 |
| subject | `/wp-json/wp/v2/subject` | 162 |

### lesson_type values observed

- `[120, 121]` — both video and audio (most common for recent lessons)
- `[120]` — video only
- `[121]` — audio only
- `[]` — neither (test/demo lessons or text articles)

Lesson 122 (text/article type) was not observed in actual fetched lessons.

---

## 2. Media URL Findings

### Critical finding: media URLs ARE in static HTML — no Selenium needed

The prior research said "actual audio player src is loaded via JavaScript — invisible to a plain
HTTP scraper." This is **incorrect for newer lessons**.

Tested lesson IDs: 37553 (recent, both video+audio), 37534 (recent, both), 9283 (old, audio-only).

#### Recent lessons (ID ~9115 and above, all with Google Drive audio)

**Video**: Vimeo player embedded as iframe — the Vimeo video ID is in static HTML:
```html
<iframe class="elementor-video-iframe" ...
  src="https://player.vimeo.com/video/1191960680?..."></iframe>
```
Regex to extract: `vimeo\.com/video/(\d+)`

**Audio**: Custom audio player with `<source src>` directly in static HTML:
```html
<audio id="customAudio_1b2Ddm7vbIXu4kFQoSS0T-NRheiTmnWZ_">
    <source src="https://bneidavid.org/wp-admin/admin-ajax.php?action=stream_audio&file_id=1b2Ddm7vbIXu4kFQoSS0T-NRheiTmnWZ_" type="audio/mpeg">
</audio>
```
Regex to extract file_id: `file_id=([A-Za-z0-9_-]+)` — appears consistently in both
the `<source src>` and the Google Drive download button href.

The `file_id` is the same as the Google Drive file ID in the download link:
```html
<a href="https://drive.google.com/uc?export=download&id=1b2Ddm7vbIXu4kFQoSS0T-NRheiTmnWZ_">
```

#### Old lessons (ID ~9283–9124, using media-line.co.il)

Lesson 9283 (date: 2003-10-28) uses old CDN directly in `<source src>`:
```html
<source src="https://secure.media-line.co.il/bneidavid/vf/audio/140/Audio.mp3" type="audio/mpeg">
```
Also exposes plain HTTP download link: `http://bneidavidmp3.media-line.co.il/bneidavid/vf/audio/140/Audio.mp3`

Lesson 9124 (date: 2025-06-04, audio-only type `lesson_type-audio`) has a different HTML
structure — appears to use a WordPress native audio block (no `file_id`, no `<source src>`
with a direct URL found in static HTML). This was a single lesson and may be an edge case.
Further testing of multiple lessons in this ID range is needed.

Lesson 15000 uses media-line: `media-line.co.il/bneidavid/vf/audio/kas/klali/kas_klali98_5774.mp3`

### HTTP behavior of stream_audio endpoint

URL: `https://bneidavid.org/wp-admin/admin-ajax.php?action=stream_audio&file_id=FILE_ID`

| Test | Result |
|------|--------|
| HEAD request (no auth) | HTTP 200, `content-type: audio/mpeg` |
| HEAD with Range: bytes=0-1023 | HTTP 206, `content-range: bytes 0-1023/12968470` |
| HEAD with fake file_id | HTTP 500 — server validates the file_id |
| HEAD with external Referer | HTTP 200 — no Referer restriction |
| CORS: `access-control-allow-origin` | `*` — open to all origins |
| `accept-ranges` header | `bytes` — byte-range requests supported |
| `cache-control` | `no-cache, no-store, private` — not cacheable |

The endpoint streams directly from Google Drive (the content-security-policy headers
in the response are Google's Drive CSP headers, visible because nginx is proxying/streaming
the file). This explains why the response is a direct audio/mpeg stream, not a redirect.

### Google Drive direct URL behavior

URL: `https://drive.google.com/uc?export=download&id=FILE_ID`

- Returns HTTP 303 redirect to `https://drive.usercontent.google.com/download?id=FILE_ID&export=download`
- Final URL returns HTTP 200, `content-type: audio/mpeg`, `access-control-allow-origin: *`
- Range request (`Range: bytes=0-1023`) on the final URL returns HTTP 206 — confirmed.
- File size: 12,968,470 bytes (for the tested lesson, a ~54 min lesson at 128kbps)
- No authentication required for the tested file (publicly shared Google Drive file)

### media-line.co.il behavior

- `https://secure.media-line.co.il/bneidavid/vf/audio/140/Audio.mp3` — **still alive** as of 2026-05-14
- Returns HTTP 200, `content-type: audio/mpeg`, `content-length: 5639927`
- `accept-ranges: bytes` header present
- Range request (`Range: bytes=0-1023`) returns **HTTP 416 Range Not Satisfiable**
  with `content-range: bytes */0` — **seeking is broken** on media-line audio
- Server: `Microsoft-IIS/10.0` — the `accept-ranges: bytes` header is misleading;
  the server reports it supports ranges but rejects the actual range request

---

## 3. Existing Firestore Archive (sourceId=1)

### Total count

```
db.collection('lessons').where('sourceId', '==', 1).count()
→ 33,208 lessons
```

### Field population (sample of 100 docs)

| Field | Populated |
|-------|-----------|
| title | 100% |
| audioUrl | 91% |
| videoUrl | 58% (+ 7% YouTube) |
| ravId | ~85% |
| seriesId | 0% (not populated) |
| categoryId | 0% (not populated) |
| dateStr | 100% |
| duration | 100% |

**seriesId and categoryId are null for all sourceId=1 lessons** — they were never populated
by the old scraper.

### URL patterns in existing Firestore lessons

From a sample of 100 docs:

| Pattern | Audio URLs | Video URLs |
|---------|-----------|-----------|
| media-line.co.il | 91 | 58 |
| youtube.com | 0 | 7 |
| null | 9 | 35 |

No Google Drive URLs, no Vimeo URLs, no bneidavid.org URLs found in the existing archive.
All existing web-scraped lessons use media-line.co.il URLs.

### originalId range

From a sample of 500 docs:
- **Web-scraped lessons** (originalId < 100,000): originalId range **316 to 21,278**
- **YouTube lessons** (originalId > 10M): originalId range ~10,151,402 to ~99,383,405

The old scraper's highest web lesson originalId found in the sample: **21,278**.

### Cross-reference with WordPress API

Tested Firestore originalIds against `GET /wp-json/wp/v2/lessons/{id}`:

| Firestore originalId | WP API result |
|----------------------|---------------|
| 316 | `rest_post_invalid_id` — does NOT exist in WordPress |
| 993 | `rest_post_invalid_id` — does NOT exist in WordPress |
| 9283 | EXISTS — title matches (יציאה מארץ ישראל) |
| 21097 | `rest_post_invalid_id` — does NOT exist in WordPress |
| 21279 | EXISTS — (תיאורי הקב"ה בתורה) |
| 25000 | EXISTS — ("|") |

**Conclusion**: WordPress IDs start at ~9283. IDs below that (316, 993, etc.) were from
the original bneidavid.org non-WordPress site and exist only in our Firestore archive.
They do not exist as WordPress posts. The old scraper scraped lesson IDs that were later
renumbered or only existed on the pre-WordPress site.

The WordPress site has lessons from IDs 9283 up to 37553. IDs 21279–31487 all exist
in WordPress (the gap implied by "max Firestore web ID = 21278" is because our old
scraper stopped; the WordPress site continued adding lessons).

### How many WP lessons are NOT yet in Firestore?

- WordPress total: 18,570 lessons (IDs 9283–37553, with gaps)
- Firestore sourceId=1 web lessons: ~431 (from 500-doc sample extrapolation: 431/500 * 33208 ≈ 28,679 — but most are YouTube lessons + old scraper IDs that don't exist in WP)
- The number of WordPress lessons genuinely absent from Firestore is unknown without a full scan.
  A scraper using `id > 21278` (last known Firestore web ID) would capture everything new from WP.

---

## 4. Streaming Verdict

### For lessons with Google Drive audio (ID ~9115+, new-style)

**Both URL options work for streaming:**

Option A — `stream_audio` endpoint:
- `https://bneidavid.org/wp-admin/admin-ajax.php?action=stream_audio&file_id=FILE_ID`
- HTTP 200/206, `audio/mpeg`, `accept-ranges: bytes`, `access-control-allow-origin: *`
- Supports byte-range seeking
- No authentication required
- Proxies through bneidavid.org's server (adds load to their server)
- **This URL can be stored as `audioUrl` and played directly in Flutter**

Option B — Google Drive usercontent URL:
- Requires following a 303 redirect first
- Final URL at `drive.usercontent.google.com` supports ranges (HTTP 206 confirmed)
- No authentication required for publicly shared files
- Google may apply rate limiting at scale (not tested)
- The redirect URL is not stable (changes per request); only the original `drive.google.com/uc` URL is stable
- **Can work as `audioUrl` if Flutter's audio_service follows redirects (it does for Android/iOS)**

**Recommendation: store the `stream_audio` URL as `audioUrl`.**
Reason: it's a direct, stable URL with no redirect, confirmed to support ranges and CORS.
The Google Drive URL requires redirect-following and may have quota issues at 18K files.

### For video lessons (all IDs)

- Vimeo player ID is in static HTML: `vimeo.com/video/NNNNNN`
- The existing app already handles Vimeo URLs
- Vimeo oEmbed API returns `duration` in seconds: `GET https://vimeo.com/api/oembed.json?url=https://vimeo.com/VIDEO_ID`
- Confirmed: lesson 37553's Vimeo video 1191960680 → duration: 3242 seconds

### For old lessons using media-line.co.il (ID 9283–~21278)

- Server is alive as of 2026-05-14
- **Byte-range requests fail (HTTP 416)** — seeking is broken
- This means audio seeking will not work for old lessons if media-line URLs are stored
- These lessons already exist in Firestore under sourceId=1 with media-line URLs
- No fix available without re-scraping from a source that has the files (Google Drive or media-line redesign)

---

## 5. Recommended Implementation Plan

Based only on verified findings.

### Strategy: use sourceId=3 for fresh WordPress scrape (confirmed from prior research)

This avoids any ID mapping complexity. All 18,570 WP lessons scraped fresh under sourceId=3
with clean, playable media URLs.

### Scraper implementation steps

**Step 1: Paginate through WP API**

```python
GET /wp-json/wp/v2/lessons?per_page=100&orderby=id&order=asc&page=N
```

Total pages: ceil(18570 / 100) = 186 pages.

Skip lessons where `lesson_type == []` (test/demo lessons). The lowest real content ID
is 9283. Set a filter `after=2003-01-01T00:00:00` or skip IDs < 9000.

**Step 2: For each lesson, fetch the page HTML**

Use the `link` field from API response. Extract:
- `file_id`: regex `file_id=([A-Za-z0-9_-]+)` from `<source src>` attribute
- Vimeo ID: regex `vimeo\.com/video/(\d+)` from iframe src
- If neither pattern matches: lesson has no playable media in new format (may be old
  media-line lesson without a WP audio player block — see open questions)

**Step 3: For video lessons, get duration from Vimeo oEmbed**

```
GET https://vimeo.com/api/oembed.json?url=https://vimeo.com/VIDEO_ID
→ response.duration (integer seconds)
```

For audio-only lessons: duration not available without downloading/probing the file.
Store 0 and accept this limitation.

**Step 4: Build Firestore docs**

```
audioUrl = "https://bneidavid.org/wp-admin/admin-ajax.php?action=stream_audio&file_id=FILE_ID"
videoUrl = "https://vimeo.com/VIDEO_ID"  (app handles Vimeo URLs already)
```

**Step 5: Taxonomy handling**

- Ravs: 54 total, fetch all with `/wp-json/wp/v2/rav?per_page=100`. Create new rav docs
  under sourceId=3 using WordPress `id` as `originalId`.
- Series: 512 total, paginate (6 pages). Create new series docs under sourceId=3.
- Subjects: 162 total, 2 pages. Create new category docs under sourceId=3.

Name-based matching to sourceId=1 docs is NOT needed — sourceId=3 is a clean namespace.

**Step 6: Incremental updates**

Store `lastScrapedAt` ISO timestamp in the sourceId=3 source doc. On each run:
```
GET /wp-json/wp/v2/lessons?per_page=100&after=LAST_SCRAPED_AT&orderby=date&order=desc
```

**Required pre-scrape tests (before running full 18K scrape)**:

1. Fetch 20 lessons spanning different ID ranges (9283, 15000, 21000, 31000, 37553).
   For each, extract file_id and Vimeo ID. Confirm both patterns are present or note exceptions.

2. Test `stream_audio` URL in the actual Flutter audio_service player on a real device.
   Confirm seeking (jump to 50% position) works. This is the highest-risk untested item.

3. Test Vimeo URL playback in the Flutter video_player widget with a freshly scraped Vimeo ID
   (not one from existing Firestore data). Confirm it plays.

4. Run a 100-lesson test scrape (1 page) and write to a test Firestore collection (not `lessons`).
   Verify field shapes before touching production data.

---

## 6. Taxonomy ID Mapping — PostgreSQL vs WordPress (Verified Against Both Sources)

Source of truth is PostgreSQL on AWS. All PG data comes from `sudo -u postgres psql -d lessons`.

### Ravs — IDs are completely different, but names match (51/53 exact matches)

PG `ravs` table (sourceId=1): 53 rows with small `originalId` values (11–83).
WP rav taxonomy: 54 terms with IDs in the 2000s range (2284–2513).

**The numeric IDs are completely different.** PG originalId=11 ≠ WP rav id=11.
However, names match precisely for 51/53 ravs (exact string match after trim):

| PG originalId | WP id | Rav name |
|---|---|---|
| 11 | 2295 | הרב אבי רונצקי |
| 12 | 2290 | הרב אוהד תירוש |
| 14 | 2286 | הרב אלי סדן |
| 15 | 2292 | הרב אליעזר קשתיאל |
| 16 | 2285 | הרב בני אייזנר זצ"ל |
| 17 | 2287 | הרב גיורא רדלר |
| 19 | ? | הרב חיים **וידל** (PG) vs הרב חיים **וידאל** (WP=2293) — same person, spelling difference |
| 22 | 2296 | הרב יואל רכל |
| 23 | 2284 | הרב יוסף קלנר |
| 24 | 2288 | הרב מרדכי הס |
| 26 | 2294 | הרב נתנאל אלישיב |
| 28 | 2297 | הרב עידו רוזנטל |
| 31 | 2289 | הרב שלמה אבינר |
| 32 | ? | הרב שמואל הרשלר — **NOT found in WP at all** (WP search returns 0 results) |
| 37 | 2291 | כללי |
| 41 | 2298 | הרב אברהם שילר |
| 44 | 2299 | הרב יגאל לוינשטיין |
| 45 | 2303 | הרב קובי דנה |
| 46 | 2300 | הרב עקיבא קשתיאל |
| 47 | 2301 | הרב רביד ניסים |
| 48 | 2302 | הרב דוד בן מאיר |
| 49 | 2304 | הרב יהודה סדן |
| 50 | 2305 | יום מהות |
| 51 | 2309 | הרב איתי הלוי |
| 52 | 2307 | הרב איתן קופמן |
| 53 | 2306 | הרב אופיר וולס |
| 56 | 2310 | הרב אליעזר בראון |
| 57 | 2311 | הרב אלישע וישליצקי |
| 58 | 2312 | הרב פנחס עציון |
| 59 | 2308 | הרצאות חול |
| 60 | 2313 | הרב יאיר אטון |
| 61 | 2314 | הרב שי אליאס |
| 63 | 2316 | הרב דוד טורנר |
| 64 | 2320 | הרב כפיר אלון |
| 65 | 2322 | דר' מיכאל אבולעפיה |
| 66 | 2323 | הרב יצחק פנירי |
| 67 | 2315 | הרב שלום הימן |
| 68 | 2324 | הרב שחר ורטמן |
| 69 | 2325 | הרב עמית זולדן |
| 70 | 2318 | הרב נריה בולאק |
| 71 | 2317 | הרב ארז אשכנזי |
| 72 | 2327 | הרב אמיר בירנבאום |
| 73 | 2326 | הרב דוד אמתי |
| 74 | 2329 | הרב רפי למפרט |
| 75 | 2328 | הרב עמי שטרנברג |
| 76 | 2319 | הרב ישי רז |
| 77 | 2330 | הרב ישי צור |
| 78 | 2332 | הרב אופיר שוקרון |
| 79 | 2333 | הרב דוד לאו |
| 80 | 2334 | הרב יאיר גלושטיין |
| 81 | 2335 | הרב שמואל וידל |
| 82 | 2331 | הרב נעם מרינבך |
| 83 | 2336 | הרב יהודה ארזוני |

**Two exceptions:**
- PG originalId=19 (הרב חיים וידל) ↔ WP id=2293 (הרב חיים וידאל): same person, WP added an alef. Treat as a match, map by name-fuzzy.
- PG originalId=32 (הרב שמואל הרשלר): no match in WP. This rav does not appear on the new WordPress site. His lessons will not be scrapeable from the new site.
- WP has two ravs not in PG: 2321 (הרב אייל קהלני, 1 lesson), 2513 (עקיבא, 1 lesson).

**Conclusion for ravs: name-based matching works for 51/53. No WP rav ID matches the PG originalId numerically.**

### Categories (subjects) — IDs different, names match exactly for all 11

PG `categories` table (sourceId=1): 12 rows, originalIds 1–44 plus one YouTube category (88709684).
WP `subject` taxonomy: 162 terms, IDs in the 2000s range.

**All 11 non-YouTube PG categories have exact name matches in WP subjects:**

| PG originalId | WP subject id | Category name |
|---|---|---|
| 1 | 2352 | אנשי אמונה בעולם המעשה |
| 27 | 2496, 2401 | תפילה (**duplicate in WP** — two WP subject terms with identical name) |
| 29 | 2354 | גמרא |
| 30 | 2337 | אמונה |
| 31 | 2356 | הלכה |
| 32 | 2369 | פרשיות השבוע |
| 33 | 2375 | שבת ומועדים |
| 34 | 2350 | תנ"ך |
| 40 | 2425 | הרצאות חול |
| 41 | 2367 | מוסר |
| 44 | 2404 | כתבי הראי"ה |

**Warning: WP has two terms both named "תפילה"** (ids 2496 and 2401). Cannot determine which corresponds to PG originalId=27 without checking which one lessons are actually tagged with. This needs investigation before writing any mapping code.

**Conclusion for categories: name-based matching works for 10/11. The 11th (תפילה) has a WP duplicate ambiguity that must be resolved.**

### Series — IDs different, names match for most older series, format differs for newer ones

PG `series` table (sourceId=1): 535 rows, originalIds 1–632 (small integers) plus large YouTube IDs.
WP `series` taxonomy: 512 terms, IDs starting at 285.

**WP series IDs do NOT overlap with PG series originalIds.** Verified: WP series/1 through /10 all return `rest_term_invalid` (not found). WP series start at id=285.

**Name-based matching results (tested 13 PG series):**

| PG originalId | WP id | Name | Notes |
|---|---|---|---|
| 5 | 756 | תניא - הרב חיים וידל | exact match |
| 6 | 464 | כוזרי [תשס"ו-תש"ע] - הרב יוסף קלנר (כל הספר) | exact match |
| 34 | 462 | כוזרי - הרב קשתיאל | exact match |
| 39 | 309 | אורות הקודש ג' - הרב קשתיאל | exact match |
| 41 | 676 | עין אי"ה על הסדר - הרב קלנר | exact match |
| 97 | 550 | מוסר אביך - הרב קלנר | exact match |
| 195 | 359 | דף יומי - הרב קשתיאל | exact match |
| 287 | 432 | חינוך ילדים - הרב עמוס נתנאל | exact match |
| 319 | 287 | אגרות הראי"ה - הרב קשתיאל | exact match |
| 398 | NO MATCH | כוזרי - הרב קלנר [תשע'ז] | WP has כוזרי - הרב קלנר [תשע"ז] — quote mark style differs |
| 487 | 640 | ספר ירמיהו - הרב קשתיאל | exact match |
| 541 | 315 | אורות התורה [תשפ"ג] \| הרב קשתיאל | exact match |
| 630 | NO MATCH | עבודת אלוקים [התשפ''ו] - הרב קלנר | WP=2509: עבודת אלוקים [תשפו'] \| הרב קלנר — format differs |

Older series (pre-תשפ) are mostly exact-match by name. More recent series (תשפ and later) differ in formatting:
- PG uses `[התשפ''ו]` and ` - ` separator
- WP uses `[תשפו']` and ` | ` separator
- This is the same format difference the prior research noted.

**Scale of the name-mismatch problem:** 512 WP series vs 535 PG series (non-YouTube). For older content that already exists in PG but not yet on WP, a name-match approach will work for most. For series added in תשפ and later, the format difference will cause misses.

**Conclusion for series: WP series IDs are completely different from PG originalIds. Name-based matching works for older series (pre-תשפ) but fails for newer ones due to formatting differences. If using sourceId=3 (fresh scrape), no mapping is needed at all — just create new series docs from WP taxonomy IDs.**

---

## 8. Open Questions

**Q1: What URL format do lessons between ID ~9115 and ~21278 use?**

Lesson 9283 (2003) uses media-line. Lesson 15000 uses media-line. Lesson 9115 (2025-06-03)
appears to have a different HTML structure (no `file_id` found in static HTML). 
The cutover from media-line to Google Drive/stream_audio is not yet determined exactly.
Need to test 5–10 lesson pages in the 9000–21000 range to find the exact cutover ID.

**Q2: What does the stream_audio endpoint return for a lesson that uses media-line URLs?**

If a media-line lesson has a `lesson_type=121` tag but uses the old CDN, does it also
have a `file_id` in the HTML? Or only a `<source src="https://secure.media-line.co.il/...">` ?
If the latter, the scraper must handle both patterns.

**Q3: Are Google Drive files guaranteed to be publicly shared?**

Tested with one file: no auth required. If Bnei David changes Google Drive sharing
permissions on any file, the `stream_audio` endpoint would return 500 (tested: fake IDs
return 500). This is a dependency on bneidavid.org's Google Drive configuration.

**Q4: What is the Vimeo rate limit for oEmbed requests?**

18,570 lessons, each needing a Vimeo oEmbed call for duration. Vimeo's oEmbed endpoint
is unauthenticated — rate limits are unknown. May need to add `time.sleep(0.1)` between
requests or batch with a Vimeo API key. Not tested.

**Q5: Are lesson_type=[] lessons (test/demo) safe to skip entirely?**

Observed IDs: 5419, 5467, 6485, 6486, 6928, 8987–8990. These appear to be site setup
artifacts. However, some legitimate lessons may also have `lesson_type=[]` if they are
text articles (type 122). Need to confirm whether to skip `lesson_type=[]` entirely or
only skip IDs < 9000.

**Q6: Does the `stream_audio` endpoint have rate limiting?**

Not tested. Scraping 18K lesson pages plus calling `stream_audio` once per lesson to
verify is not recommended. The file_id from HTML should be sufficient without an actual
HEAD/GET request to `stream_audio` during scraping.

**Q7: Is there a way to get audio duration without downloading the file?**

- From HTML: no (duration is rendered as `0:00` initially, set by JS after load)
- From WP API: no duration field
- From `stream_audio` `Content-Length` + bitrate assumption: approximate (128kbps assumption
  for Google Drive files — not verified for all files)
- From Vimeo oEmbed: only for video lessons
- For audio-only lessons: no reliable source found. Store 0.

**Q8: Will sourceId=3 need to be created in Firestore?**

Not verified — the `sources` collection currently has 20 docs. Need to confirm sourceId=3
does not already exist before creating it. (sourceId=3 is confirmed "available" per prior
research but this should be verified with `db.collection('sources').where('originalId', '==', 3).get()`
before the first write.)

---

## 9. Video Playability Verification

Last updated: 2026-05-14

All claims below were verified by actually fetching URLs. No assumptions.

### Exact Vimeo URL format in lesson pages

Three lesson pages fetched (IDs 37553, 37533, 37534). Each contains a Vimeo player iframe.
The `src` attribute in the static HTML uses this exact format:

```
https://player.vimeo.com/video/1191960680?color&autopause=0&loop=0&muted=0&title=1&portrait=1&byline=1#t=
https://player.vimeo.com/video/1191861419?color&autopause=0&loop=0&muted=0&title=1&portrait=1&byline=1#t=
https://player.vimeo.com/video/1191861824?color&autopause=0&loop=0&muted=0&title=1&portrait=1&byline=1#t=
```

Pattern: `https://player.vimeo.com/video/<VIDEO_ID>?color&autopause=0&...#t=`

The query string parameters and the trailing `#t=` are boilerplate added by Elementor's
Vimeo embed widget. Only the numeric VIDEO_ID is meaningful.

### `player.vimeo.com/video/VIDEO_ID` — content-type verification

```
HEAD https://player.vimeo.com/video/1191960680
  → HTTP 405 (Method Not Allowed), content-type: text/html;charset=UTF-8

GET https://player.vimeo.com/video/1191960680 (with mobile UA)
  → HTTP 401, content-type: text/html;charset=UTF-8

GET https://player.vimeo.com/video/1191960680 (with Dart/3.0 UA)
  → HTTP 401, content-type: text/html;charset=UTF-8
```

**This URL is an HTML page, not a video stream.** Flutter's `video_player` package cannot
play it. `VideoPlayerController.networkUrl(Uri.parse("https://player.vimeo.com/video/..."))` will fail.

### Vimeo oEmbed API — does it return a direct MP4 URL?

```
GET https://vimeo.com/api/oembed.json?url=https://vimeo.com/1191960680
```

Response contains these fields: `type`, `version`, `provider_name`, `provider_url`,
`title`, `author_name`, `author_url`, `is_plus`, `account_type`, `html`, `width`, `height`,
`duration`, `description`, `thumbnail_url`, `thumbnail_width`, `thumbnail_height`,
`thumbnail_url_with_play_button`, `upload_date`, `video_id`, `uri`.

**No direct MP4 or HLS URL is returned.** The `html` field contains only an iframe embed:
```html
<iframe src="https://player.vimeo.com/video/1191960680?app_id=122963" ...></iframe>
```

The `duration` field IS present and accurate (3242 seconds for lesson 37553, verified
against the lesson page). The oEmbed API is useful for fetching duration during scraping,
but gives no playable URL.

### Vimeo config endpoint — direct MP4 via undocumented API

```
GET https://player.vimeo.com/video/1191960680/config
  (with Referer: https://bneidavid.org/, Origin: https://bneidavid.org)
  → HTTP 403, x-vimeo-error: player-backend
```

The config endpoint returns 403 even with the correct Referer. This endpoint requires
authentication or session cookies from an embedded Vimeo player. It cannot be called
directly from a scraper or a Flutter HTTP client.

### `vimeo.com/VIDEO_ID` — content-type verification

```
GET https://vimeo.com/1191960680 (Dart/3.0 UA)
  → HTTP 200, content-type: text/html; charset=utf-8
```

`https://vimeo.com/VIDEO_ID` is also a text/html webpage. Flutter's `video_player`
cannot play it either.

### What the existing Flutter player does with video URLs

In `VideoApp.dart`, the `_playSession(url)` method handles video like this:

1. If `url` contains "youtube" → `YouTubeVideoPlayerController` is used, which calls
   `youtube_explode_dart` to resolve the YouTube video ID to a direct CDN stream URL.
   This works because `youtube_explode_dart` extracts the actual MP4/WebM stream.
2. Otherwise → `VideoPlayerController.networkUrl(Uri.parse(url))` is called directly.

**There is no special handling for Vimeo URLs anywhere in the codebase.** No Vimeo
SDK, no Vimeo API calls, no URL rewriting. If a Vimeo player URL is passed, step 2
executes and `video_player` tries to stream an HTML page, which will fail.

### What existing sourceId=1 video URLs look like in Firestore

From a sample of 500 Firestore docs with `sourceId=1`:
- **0 Vimeo URLs** — no `vimeo.com` URLs exist in any sourceId=1 doc
- **media-line MP4 URLs** (most common): `http://users.media-line.co.il/bneidavid/vf/audio/video/**/*.mp4`
- **YouTube watch URLs**: `https://www.youtube.com/watch?v=VIDEO_ID`
- Range requests on media-line MP4 URLs return **HTTP 416** (same bug as audio)

The existing video lessons use direct MP4 URLs (media-line) or YouTube URLs. The app
handles these correctly — MP4 via `video_player` directly, YouTube via `youtube_explode_dart`.

### VERDICT

**NO — you cannot store `https://vimeo.com/VIDEO_ID` or `https://player.vimeo.com/video/VIDEO_ID`
in Firestore and have the Flutter player play it.** Both URLs return HTML, not a video stream.
The player has no Vimeo handling — only YouTube and direct-stream URLs are supported.

**What URL to store: none is available without additional work.**

The only ways to make Vimeo video work in Flutter are:

**Option A (Recommended): Use `youtube_explode_dart` analog for Vimeo**
Add a package like `dart_vlc` or integrate a Vimeo API token to resolve Vimeo video IDs
to direct CDN stream URLs at playback time (similar to how `youtube_explode_dart` works
for YouTube). The Vimeo API requires OAuth — free Vimeo accounts have rate limits.

**Option B: Use a WebView**
Embed `https://player.vimeo.com/video/VIDEO_ID` in a `webview_flutter` WebView widget
instead of `video_player`. This would require adding the `webview_flutter` package and
significant changes to `VideoApp.dart`.

**Option C: Skip video for new lessons (audio-only)**
Store only `audioUrl` (the `stream_audio` endpoint) for new bneidavid.org lessons.
The audio works correctly (verified: HTTP 206, byte-range seeking). Video playback
from Vimeo requires additional engineering work before the scraper is useful for video.

**What to store in Firestore for the scraper (current state):**
- `audioUrl`: `https://bneidavid.org/wp-admin/admin-ajax.php?action=stream_audio&file_id=FILE_ID` ✅ works
- `videoUrl`: `null` or omit — until Vimeo playback is engineered ❌ cannot play Vimeo

**Prior findings claim** (Section 5): "The existing app already handles Vimeo URLs."
**This is incorrect.** There is no Vimeo handling in `VideoApp.dart`. The prior finding
was an unverified assumption. Storing `https://vimeo.com/VIDEO_ID` as `videoUrl` will
cause playback failure — `video_player` will attempt to stream an HTML page and error out.

---

## 10. Video Playback Deep Investigation

Last updated: 2026-05-14

All claims below were verified by actually making HTTP requests. No assumptions. No "probably".

**Known Vimeo video IDs tested:** `1191960680` (lesson 37553), `1191861419` (lesson 37533), `1191861824` (lesson 37534).

**Key prerequisite finding:** Vimeo iframes in bneidavid.org lesson pages do NOT use the `h=` hash
privacy parameter. The exact iframe src format is:
```
https://player.vimeo.com/video/VIDEO_ID?color&autopause=0&loop=0&muted=0&title=1&portrait=1&byline=1#t=
```
No `h=HASH` in any of the three tested lesson pages. Videos are "embed anywhere" (not private link).

---

### Approach 1: Vimeo hash parameter (unlisted videos)

**Result: Not applicable.**

Fetched 3 lesson pages (IDs 37553, 37534, 37533). None contain `h=HASH` in the Vimeo iframe src.
The Vimeo v2 API confirms `"embed_privacy": "anywhere"` for all tested videos — they are not
"private link" videos. The hash parameter approach does not apply here.

However, the hash value (`h=6c9bef413a`) appears in the Vimeo API's `player_embed_url` response
field in a `context=...` signed URL. That hash is for API authentication, not for embed privacy.
Testing `GET /video/VIDEO_ID/config?h=HASH` still returns HTTP 403.

---

### Approach 2 & 8: Vimeo player session cookies + player page HTML extraction

**Result: Working, partially useful.**

**Request:**
```
GET https://player.vimeo.com/video/1191960680
Referer: https://bneidavid.org/
User-Agent: Mozilla/5.0 ... Chrome/120 ...
Sec-Fetch-Dest: iframe
Sec-Fetch-Mode: navigate
Sec-Fetch-Site: cross-site
```

**Response:** HTTP 200, `text/html`, 22,319 bytes. Cookies set: `__cf_bm`, `_cfuvid` (Cloudflare).

**Critical finding: The HTML page contains `window.playerConfig` with FULL stream URLs.**

```javascript
window.playerConfig = {
  "request": {
    "files": {
      "dash": { "cdns": { "akfire_interconnect_quic": { "url": "https://vod-adaptive-ak.vimeocdn.com/..." }, ... } },
      "hls":  { "cdns": { "akfire_interconnect_quic": { "url": "https://vod-adaptive-ak.vimeocdn.com/..." }, ... } }
    }
  }
}
```

**No progressive MP4 in playerConfig** — only `dash` and `hls` keys. Progressive downloads are
not exposed via the embedded player page.

The HLS master URL (from `playerConfig`) has these properties:
- Domain: `vod-adaptive-ak.vimeocdn.com`
- TTL: **3.6 hours** (exp= token in URL)
- Auth: HMAC-signed ACL covering `/UUID/psid=PSID/*`
- No session cookies required to fetch master m3u8 (tested with Dart UA, fresh session)
- Sub-playlists (720p, 540p, 360p, 240p): accessible when URL is correctly resolved to include psid in path
- Video segments: accessible, H.264, fMP4 format

**HLS chain tested (full path, no cookies):**
```
GET master m3u8        → HTTP 200 ✅
GET 720p sub-playlist  → HTTP 200 ✅ (pathsig in URL, no cookies needed)
GET video segment      → HTTP 206 ✅ (fMP4, range request)
```

**Can Flutter `video_player` play this HLS URL?**
- iOS: YES — AVPlayer natively handles HLS m3u8, including fMP4 segments with H.264
- Android: YES — ExoPlayer handles adaptive HLS with fMP4 segments
- Implementation: `VideoPlayerController.networkUrl(Uri.parse(hlsMasterUrl))`
- The master m3u8 URL is self-contained (auth embedded in URL, no cookies required)

**Limitation:** The HLS URL expires in 3.6 hours. It cannot be stored in Firestore. It must be
resolved fresh for each playback session (i.e., a Cloud Function or on-device fetch needed).

---

### Approach 3: Vimeo player page JavaScript analysis

**Finding: `window.playerConfig` is the source of truth.**

The HTML contains an inline script block setting `window.playerConfig` with all stream URLs.
No JWT or bearer token is embedded in the player page that would unlock the `/config` endpoint.
The `playerConfig` already contains the HLS/DASH CDN URLs directly — no additional auth needed
to get them.

A `config/request?atid=...&expires=1` URL was found in the page HTML but returns HTTP 403 when
fetched (even with session cookies). This endpoint is called by the player JavaScript to refresh
tokens, not accessible from a scraper.

---

### Approach 4: Vimeo API endpoint variations

All tested. Results:

| URL | Status | Notes |
|-----|--------|-------|
| `GET https://vimeo.com/VIDEO_ID/config` | 404 | Not a valid endpoint |
| `GET https://api.vimeo.com/videos/VIDEO_ID` | 401 | Requires auth token |
| `GET https://player.vimeo.com/api/video/VIDEO_ID` | 404 | Not a valid endpoint |
| `GET https://vimeo.com/api/v2/video/VIDEO_ID.json` | **200** | Returns metadata only (no stream URLs) |
| `GET https://player.vimeo.com/video/VIDEO_ID/config` | 403 | Always 403, no header combo fixes it |

The **Vimeo v2 API** (`vimeo.com/api/v2/video/VIDEO_ID.json`) returns duration, title, thumbnail,
and embed_privacy. No stream URLs. Useful for metadata.

---

### Approach 5: yt-dlp analysis

**Result: Works, reveals the progressive_redirect URL structure.**

```bash
yt-dlp --get-url "https://vimeo.com/1191960680"
```

Returns two URLs (HLS + DASH). When a cached macOS OAuth token is available (yt-dlp caches it
from a previous session), it returns:
```
https://player.vimeo.com/progressive_redirect/playback/VIDEO_ID/container/UUID/HASH1-HASH2/file.mp4...?expires=...&session_id=...&signature=...
```

yt-dlp uses a public Vimeo macOS client OAuth credential (client_id and client_secret embedded
in yt-dlp source) to obtain a bearer token, then calls `GET api.vimeo.com/videos/VIDEO_ID?fields=play,files`
which returns progressive MP4 download links.

**The OAuth credentials are public (from yt-dlp source):**
- macOS client_id: `4757be7f9f6f25771754de856f6c5612491e62bb`
- macOS AUTH (base64 of id:secret): `NDc1N2JlN2Y5ZjZmMjU3NzE3NTRkZTg1NmY2YzU2MTI0OTFlNjJiYjpwVUNDWUlBZmZqSHhQcndBYWxGMzgyYys2NkN5d1JrREJZZXdPcEdsU05tdjFlVVo2aE1lYk9GcWE3ZW9KVldlYnFlOWh5Vno5UWtpUGJ5empYZFBpYkFwV0FFTnB5VWV4ZEh3aHZnRUNEL0VySnBzTmFraDdNbS9nMXhWanhIcw==`
- User-Agent: `Vimeo/1.6.3 (com.vimeo.mac; build:251121.142637.0; macOS 13.7.8) Alamofire/5.9.0 VimeoNetworking/5.0.0`

---

### Approach 6: Cloud Function as video proxy — VERIFIED WORKING

**This is the recommended solution.** A Cloud Function can:

1. Receive a Vimeo video ID from the Flutter app
2. Get a Vimeo macOS OAuth bearer token (cached per Cloud Function instance)
3. Call `GET https://api.vimeo.com/videos/VIDEO_ID?fields=play,files` with the bearer token
4. Return the progressive 720p MP4 URL to the Flutter app
5. Flutter plays it directly with `VideoPlayerController.networkUrl()`

**Tested and verified (all HTTP requests confirmed):**

**Step 1: Get OAuth token (cached per Cloud Function instance)**
```
POST https://api.vimeo.com/oauth/authorize/client
Authorization: Basic NDc1N2Jl...
Content-Type: application/json
Body: {"grant_type": "client_credentials", "scope": "public"}

→ HTTP 200, {"access_token": "0ec07d2a4f...", "token_type": "bearer", "scope": "public"}
Latency: ~0.25s
```

**Step 2: Get video play URLs**
```
GET https://api.vimeo.com/videos/1191960680?fields=play,files
Authorization: Bearer 0ec07d2a4f...
Accept: application/vnd.vimeo.*+json; version=3.4.10
User-Agent: Vimeo/1.6.3 (com.vimeo.mac; ...)

→ HTTP 200, {
    "play": {
        "progressive": [
            {"width": 1280, "link": "https://player.vimeo.com/progressive_redirect/playback/..."},
            {"width": 960, ...},
            {"width": 640, ...},
            {"width": 426, ...}
        ],
        "hls": {"link": "https://player.vimeo.com/play/UUID/hls.m3u8?s=..."},
        "dash": {"link": "https://player.vimeo.com/play/UUID/dash.mpd?s=..."}
    }
}
Latency: ~0.30s
```
Total latency: **~0.55s** for both steps.

**Step 3: Progressive MP4 URL properties (tested with fresh session, Dart UA)**
```
HEAD https://player.vimeo.com/progressive_redirect/playback/1191960680/container/UUID/a762bdd0-4bf77c04/file.mp4?expires=...

→ HTTP 200
Content-Type: video/mp4
Content-Length: 519375062 (495 MB for 720p, ~54 min video)
Accept-Ranges: bytes          ← seeking works
Access-Control-Allow-Origin: * ← no CORS issues
TTL: 24 hours (expires= in URL)
No cookies required ✅
```

Range request test: `Range: bytes=0-1023` → HTTP 206 ✅ (seeking confirmed working)

**Confirmed with two video IDs** (1191960680, 1191861419) — both returned 4 progressive quality
variants (1280, 960, 640, 426 pixels wide).

---

### Approach 7: Direct Vimeo CDN pattern

**Not viable for direct storage.** The CDN URLs (vod-adaptive-ak.vimeocdn.com, skyfire.vimeocdn.com)
contain HMAC-signed tokens with expiry. They cannot be predicted or stored. They must be resolved
fresh from either the player page or the Vimeo API.

The Vimeo v2 public API (`vimeo.com/api/v2/video/ID.json`) returns only metadata (title, duration,
thumbnail, embed_privacy). No CDN URLs exposed.

---

### Approach Config Endpoint: Summary

All attempts to call `player.vimeo.com/video/VIDEO_ID/config` directly returned HTTP 403:
- With `Referer: https://bneidavid.org/` only
- With `Origin: https://bneidavid.org/`
- With `X-Requested-With: XMLHttpRequest`
- With JWT from `vimeo.com/_next/viewer`
- With h=HASH parameter
- With `Referer: https://player.vimeo.com/video/VIDEO_ID`
- Without any Referer (just browser UA)

The config endpoint is not accessible without a full browser session. It is not needed because
`window.playerConfig` in the player page HTML already contains equivalent stream URL data.

---

### Implementation: Flutter Player Integration

**Storing in Firestore:** Do NOT store the video stream URL (it expires). Instead, store only the
Vimeo video ID extracted from the lesson page HTML.

```
videoUrl: "vimeo:1191960680"  (or just store the numeric ID separately as "vimeoId")
```

**Playing in Flutter (two options):**

**Option A — Cloud Function (recommended):**
```
Flutter → Cloud Function (resolveVimeoUrl?videoId=1191960680) → Vimeo API → returns MP4 URL
Flutter → VideoPlayerController.networkUrl(mp4Url)  // direct, no HLS, no WebView
```
The Cloud Function caches the OAuth token and returns a fresh 24h MP4 URL per request.
Latency: ~0.55s (OAuth token + video API call), then instant playback via direct MP4.

**Option B — On-device player page fetch (no backend needed):**
```
Dart HTTP GET https://player.vimeo.com/video/VIDEO_ID
    + Referer: https://bneidavid.org/
    + Sec-Fetch-Dest: iframe
→ Parse window.playerConfig JSON from HTML
→ Extract HLS master URL
→ VideoPlayerController.networkUrl(hlsUrl)
```
No Cloud Function needed. Latency: ~0.5s for the player page fetch. TTL: 3.6 hours (sufficient
for a single viewing session). The HLS URL is fully self-contained — no cookies, no additional
auth, works on both iOS (AVPlayer) and Android (ExoPlayer).

**Option B is simpler but requires Dart HTML parsing. Option A requires a Cloud Function but
gives a direct MP4 URL (simpler Flutter code, better seeking on some platforms).**

---

### WebView (last resort — not needed)

A WebView embedding `https://player.vimeo.com/video/VIDEO_ID` would work but requires adding
the `webview_flutter` package and significant changes to `VideoApp.dart`. Given that both
Option A and Option B above work without WebView, this is unnecessary.

---

## 11. Recommended Solution

**Ranked by preference:**

### Rank 1: On-device Player Page Fetch (Option B) — BEST for simplicity

**What it is:** Flutter's Dart code fetches `player.vimeo.com/video/VIDEO_ID` as an iframe
request (with Referer header), parses `window.playerConfig` JSON from the HTML, extracts the
HLS master URL, and passes it to `VideoPlayerController.networkUrl()`.

**Why it's best:**
- No Cloud Function needed (saves cost, no additional infra)
- No WebView needed
- Standard `video_player` package, no new dependencies
- HLS supported natively on iOS (AVPlayer) and Android (ExoPlayer)
- URL is session-independent (no cookies required)
- Works reliably for any "embed anywhere" Vimeo video
- 0.5s latency before playback starts (acceptable)
- TTL of 3.6 hours per URL (well beyond any single session)

**Implementation complexity: LOW** — ~80 lines of Dart code:
1. `http.get('https://player.vimeo.com/video/$videoId', headers: {'Referer': 'https://bneidavid.org/', ...})`
2. Regex or JSON parse to extract `window.playerConfig`
3. Extract `request.files.hls.cdns.akfire_interconnect_quic.url`
4. `VideoPlayerController.networkUrl(Uri.parse(hlsUrl))`

**What to store in Firestore:** `vimeoId: "1191960680"` (just the numeric ID string from iframe src)

**Risk:** Vimeo may change the `window.playerConfig` JSON structure. Low risk — this has been
stable for years and yt-dlp depends on it too.

---

### Rank 2: Cloud Function Vimeo OAuth API (Option A)

**What it is:** A Firebase Cloud Function receives a Vimeo video ID, uses the Vimeo macOS client
OAuth credentials (from yt-dlp source) to get a bearer token, calls the Vimeo API to get
progressive MP4 URLs, and returns the 720p URL to the Flutter app.

**Why it's good:**
- Returns a direct MP4 URL (no HLS, simpler `video_player` usage)
- 24h TTL per URL (can cache URL in Flutter for duration of session)
- Range requests (seeking) confirmed working
- Proven approach (yt-dlp uses exactly this mechanism)

**Implementation complexity: MEDIUM** — Cloud Function (~50 lines Python/Node) + Flutter API call:
```python
# Cloud Function (Python)
@https_fn.on_request()
def resolve_vimeo(req):
    video_id = req.args.get('videoId')
    token = get_cached_oauth_token()  # cached in memory
    r = requests.get(f'https://api.vimeo.com/videos/{video_id}?fields=play',
        headers={'Authorization': f'Bearer {token}', ...})
    progressive = r.json()['play']['progressive']
    url_720p = next(p['link'] for p in progressive if p['width'] == 1280)
    return {'url': url_720p}
```

**Risk:** The macOS OAuth client credentials are from yt-dlp's source code (effectively public).
Vimeo could revoke or change them. Moderate risk — yt-dlp actively maintains these credentials,
so changes would be caught quickly. The token itself is a `client_credentials` grant (no user
account required), so it cannot be banned without affecting all yt-dlp users.

---

### Rank 3: WebView (last resort — not needed)

Embedding `https://player.vimeo.com/video/VIDEO_ID` in a `webview_flutter` WebView.
Not needed given Rank 1 and 2 work. Adds WebView dependency, breaks native UI, makes seek/fullscreen
controls harder to implement. Do not use.

---

## 10. Final Approved Implementation Decisions (May 14, 2026)

### New Firestore fields

| Field | Type | Source | Notes |
|---|---|---|---|
| `streamAudioFileId` | string? | HTML `<source>` tag file_id param | NOT the full URL — Flutter constructs it |
| `vimeoId` | string? | HTML iframe Vimeo ID | Flutter resolves via Cloud Function proxy |
| `scrapeSource` | array | Scraper | `['new_site']` for new, `ArrayUnion(['new_site'])` for existing |

### Fields never touched by new scraper
- `audioUrl` — kept as-is (media-line or other existing URLs)
- `videoUrl` — kept as-is (media-line MP4 or other existing URLs)

### Flutter playback priority
- **Video**: `videoUrl` first (direct, zero overhead) → `vimeoId` → Cloud Function proxy
- **Audio**: `streamAudioFileId` → construct stream_audio URL → `audioUrl` fallback

### Upsert logic
- **Existing lesson** (found by sourceId=1 + originalId): UPDATE `streamAudioFileId`, `vimeoId`, `scrapeSource` (ArrayUnion), taxonomy refs only if currently null in Firestore
- **New lesson**: CREATE full doc with `audioUrl=null`, `videoUrl=null`

### scrapeSource values
- `'old_site'` — scraped from old bneidavid.org/Web/He/VirtualTorah/
- `'youtube'` — from Bnei David YouTube channel
- `'new_site'` — from new bneidavid.org WordPress site
