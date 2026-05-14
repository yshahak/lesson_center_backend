# Bnei David Scraper — Research Findings

Last updated: May 13, 2026

---

## Context

The old `bnei_david_grabber.py` is completely obsolete. The original site
(`https://www.bneidavid.org/Web/He/VirtualTorah/`) no longer exists. The new site
is a WordPress installation at `https://bneidavid.org/` with a clean REST API.
No Selenium/PhantomJS needed — pure HTTP requests.

---

## New Site Structure

### REST API
Base: `https://bneidavid.org/wp-json/wp/v2/`

**Lessons endpoint:**
```
GET /wp-json/wp/v2/lessons?per_page=100&orderby=date&order=desc&after=ISO_DATE
```

Response fields per lesson:
```json
{
  "id": 37553,
  "date": "2026-05-13T15:55:27",
  "title": { "rendered": "סיום המאמר | עבודת אלוקים [22]" },
  "link": "https://bneidavid.org/lessons/slug/",
  "subject": [2473],
  "series": [2509],
  "lesson_type": [120, 121],
  "rav": [2284]
}
```

Pagination: `X-WP-TotalPages` header tells total pages.

**Taxonomy endpoints:**
```
GET /wp-json/wp/v2/rav/{id}       → { id, name, slug, count }
GET /wp-json/wp/v2/series/{id}    → { id, name, slug, count }
GET /wp-json/wp/v2/subject/{id}   → { id, name, slug, count }
```

**Lesson type IDs:**
- 120 = video
- 121 = audio
- 122 = text (article)

**Total lessons on site:** ~30,000 (11.7k video + 18.1k audio + 240 text)

---

## Lesson ID Situation — SAME IDs ✅

**WordPress lesson IDs are identical to old site lesson IDs.**

Verified: lesson 21259 on WordPress = November 2017 lesson that the old scraper
would have scraped. IDs were preserved during WordPress migration.

**Dedup strategy for lessons:** simple — skip any WordPress lesson ID that already
exists as `originalId` in Firestore for sourceId=1.

Find the max originalId already in Firestore for sourceId=1, then only fetch
WordPress lessons with `id > max_existing_id`.

---

## Taxonomy ID Situation — DIFFERENT IDs ❌

WordPress taxonomy IDs (rav, series, subject) are completely different from
what the old site used.

**Ravs:**
| PostgreSQL originalId | Firestore name | WordPress ID |
|---|---|---|
| 11 | הרב אבי רונצקי | 2295 |
| 12 | הרב אוהד תירוש | 2290 |
| 23 | הרב יוסף קלנר | 2284 |

**Verified:** Hebrew names match exactly between PostgreSQL and WordPress API.
Use name-based matching for ravs.

**Series:**
PostgreSQL has small int originalIds (1, 5, 6, 7...). WordPress has IDs like 2509.
**Names differ in formatting:**
- WordPress: `עבודת אלוקים [תשפו'] | הרב קלנר`
- PostgreSQL: `עבודת אלוקים [התשפ''ו] - הרב קלנר`

Year format differs (`[תשפו']` vs `[התשפ''ו]`) and separator differs (`|` vs `-`).
**Recommendation:** Just create new series Firestore docs for WordPress series IDs.
This is fine UX-wise — year-specific series are genuinely different.

**Categories/Subjects:**
Old scraper used a hardcoded map:
```python
subjectsIdMap = {
    'ללא': 1, 'גמרא': 29, 'אמונה': 30, 'הלכה': 31,
    'הרצאות חול': 40, 'כתבי הראי"ה': 44, 'מוסר': 41,
    'פרשיות השבוע': 32, 'שבת ומועדים': 33, 'תנ"ך': 34, 'תפילה': 27,
}
```
WordPress category names are likely exact matches (broad topics).
Use name-based matching for categories.

---

## Media URLs — The Hard Part

Media is hosted on **Google Drive**, not on media-line.co.il (old CDN is gone).

The static lesson page HTML contains only a Google Drive **download** link:
```
https://drive.google.com/uc?export=download&id=FILE_ID
```

The actual audio player `src` is loaded **via JavaScript** — invisible to a plain
HTTP scraper without a browser. No media URL is in any `<script>` tag or JSON blob
in the page source.

**Options:**
1. Store the Google Drive download URL as `audioUrl` — works for downloading,
   uncertain for streaming/seeking in Flutter's audio player
2. Use Cloud Run with Playwright (headless Chromium) to execute the JS and get
   the actual player src — adds infra complexity
3. Skip website scraper; rely on Bnei David YouTube channel for new content

**Duration:** Also not available in the API or static HTML (loaded via JS).
Would need to either skip it (store 0) or use the Cloud Run/Playwright approach.

---

## Bnei David YouTube Channel

Channel ID: `UC3MjXqiy3SNNSWiixX2Mybw`
Source ID: 1 (same sourceId as the website scraper)

**This channel is NOT in our Cloud Function yet.**
It was only in the old `bnei_david_grabber.py` on the AWS server.

**Action needed:** Add to `functions/scrapers/youtube_scraper.py` channels list:
```python
{"source_id": 1, "channel_id": "UC3MjXqiy3SNNSWiixX2Mybw", "category": "בני דוד - כללי", "label": "בני דוד - ערוץ יוטיוב"},
```

This is a quick win — covers all new Bnei David YouTube content automatically.

---

## Existing Firestore Data for sourceId=1

Two types of lessons already in Firestore under sourceId=1:
1. **YouTube lessons** — `videoUrl` is youtube.com, `ravId/seriesId/categoryId` are null
2. **Old site lessons** — `audioUrl`/`videoUrl` from media-line.co.il (old CDN, likely dead), has rav/series/category populated

The old site stopped producing new content around **August 2025** (last scraped
originalId ~21302 on the old site). New WordPress content starts after that.

---

## Recommended Scraper Strategy

**Use a fresh sourceId=3 for the WordPress site. Do NOT try to merge with sourceId=1.**

Rationale:
- Old sourceId=1 web lessons have dead media URLs (media-line.co.il is gone) — they're
  unplayable anyway. Orphaning them is fine.
- Old sourceId=1 YouTube lessons are unaffected — continue as-is under sourceId=1.
- Fresh sourceId eliminates ALL ID mapping and name-matching complexity.
- ~30K lessons re-scraped fresh under sourceId=3 gives clean, playable media URLs.

**Implementation plan:**

1. **One-time full scrape** — paginate through all WordPress lesson IDs:
   ```
   GET /wp-json/wp/v2/lessons?per_page=100&page=N&orderby=id&order=asc
   ```
   Total pages: ~300 (30K lessons / 100 per page)

2. **Incremental updates** — use `after` date param:
   ```
   GET /wp-json/wp/v2/lessons?per_page=100&after=LAST_RUN_ISO_DATE&orderby=date&order=desc
   ```

3. **Dedup**: store `lastScrapedAt` in the source doc. On each run, only fetch
   lessons with `date > lastScrapedAt`. No cross-referencing needed.

4. **Taxonomy**: create fresh rav/series/category docs under sourceId=3 using
   WordPress taxonomy IDs as `originalId`. No mapping to sourceId=1 docs.

5. **Media URLs**: fetch each lesson page HTML, extract Google Drive download URL.
   Test in Flutter player before doing the full 30K scrape.

**Available sourceIds:** 1, 2, 50–74 are taken. Use **sourceId=3** for WordPress site.

---

## File References

- Old scraper (obsolete): `lesson_center_backend/python/bnei_david_grabber.py`
- New Cloud Function stub: `lesson_center_backend/functions/scrapers/bnei_david_scraper.py`
- YouTube scraper (add BD channel here): `lesson_center_backend/functions/scrapers/youtube_scraper.py`
