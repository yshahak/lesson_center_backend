# Firebase Cloud Functions - Lesson Center

This directory contains Firebase Cloud Functions that replace the previous PostgreSQL-based scraping pipeline with direct Firestore operations.

## 📁 Structure

```
functions/
├── main.py                     # Main Cloud Functions entry points
├── requirements.txt            # Python dependencies
├── scrapers/                   # Individual scraper modules
│   ├── youtube_scraper.py      # ✅ YouTube scraping (Phase 1)
│   ├── bnei_david_scraper.py   # 🚧 TODO: Convert to Firestore
│   └── arutz_meir_scraper.py   # 🚧 TODO: Convert to Firestore
└── utils/
    └── firestore_helper.py     # Firestore operations & SQL compatibility
```

## 🚀 Phase 1 Implementation (Current)

- ✅ **YouTube Scraper**: Fully converted to Firestore
- ✅ **Firestore Helper**: SQL-compatible interface for Firestore
- ✅ **Cloud Functions**: HTTP and scheduled trigger support
- ⚠️ **Limited Testing**: Processing 1 channel with 50 videos max

## 🎯 Cloud Functions

### `scrape_lessons_http`
HTTP-triggered function for manual scraping
```bash
curl -X POST https://your-region-your-project.cloudfunctions.net/scrape_lessons_http \
  -H "Content-Type: application/json" \
  -d '{"scraper": "youtube"}'
```

### `scrape_lessons_scheduled`
Scheduled function (triggered by Cloud Scheduler)
- Runs daily at midnight
- Processes all configured scrapers

## 🔧 Local Development

### Prerequisites
```bash
pip install -r requirements.txt
```

### Environment Variables
- Ensure your `GOOGLE_APPLICATION_CREDENTIALS` points to a valid service account
- Or authenticate via `gcloud auth application-default login`

### Test Locally
```bash
cd functions
python main.py
```

## 🚀 Deployment

### Deploy Functions
```bash
# From project root
gcloud functions deploy scrape_lessons_http \
  --runtime python39 \
  --trigger-http \
  --source functions/ \
  --entry-point scrape_lessons_http

gcloud functions deploy scrape_lessons_scheduled \
  --runtime python39 \
  --trigger-topic lesson-scraping-schedule \
  --source functions/ \
  --entry-point scrape_lessons_scheduled
```

### Set up Cloud Scheduler
```bash
gcloud scheduler jobs create pubsub lesson-scraper-daily \
  --schedule="0 0 * * *" \
  --topic=lesson-scraping-schedule \
  --message-body='{"scraper": "all"}'
```

## 📊 Phase 2 TODOs

1. **Convert Remaining Scrapers**:
   - `bnei_david_scraper.py` - Convert from PostgreSQL to Firestore
   - `arutz_meir_scraper.py` - Convert from PostgreSQL to Firestore

2. **Enhance YouTube Scraper**:
   - Remove 50-video limit
   - Process all configured channels
   - Add better error handling and retries

3. **Optimization**:
   - Implement batch writes for better performance
   - Add caching for metadata lookups
   - Add monitoring and alerting

4. **Remove Legacy**:
   - Remove PostgreSQL dependencies
   - Clean up `python/` directory
   - Remove `postgres_to_sql_converter.py`

## 🔍 Monitoring

- View logs: `gcloud functions logs read scrape_lessons_http`
- Monitor in Firebase Console
- Check Firestore for new documents

## 🚦 Current Status

**Phase 1: ✅ COMPLETE**
- YouTube scraper working with Firestore
- Infrastructure ready for deployment
- Ready for testing with limited scope

**Next: Convert remaining scrapers (Bnei David, Arutz Meir)** 