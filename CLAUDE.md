# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lesson Center Backend is a multi-platform lesson content management system with multiple backend implementations:

- **Primary Active**: Firebase Cloud Functions (Python) with Firestore
- **Legacy**: Dart/Aqueduct API server 
- **Legacy**: Node.js/Express API server
- **Legacy**: Python scrapers with PostgreSQL

The project is currently transitioning from PostgreSQL-based scrapers to Firebase Cloud Functions with direct Firestore operations.

## Development Commands

### Firebase Functions (Primary)
```bash
# Local development and testing
cd functions/
python main.py

# Install dependencies  
pip install -r requirements.txt

# Deploy functions
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

# View logs
gcloud functions logs read scrape_lessons_http

# Deploy from Firebase directory
cd firebase/
firebase deploy --only functions
```

### Dart/Aqueduct (Legacy)
```bash
# Run server locally
aqueduct serve

# Run from IDE
dart bin/main.dart

# Run tests
pub run test

# Generate Swagger documentation
aqueduct document client
```

### Node.js API (Legacy)
```bash
cd node/
npm start
```

## Architecture

### Firebase Functions Structure
- `functions/main.py` - Cloud Functions entry points (HTTP and scheduled triggers)
- `functions/scrapers/` - Individual scraper modules for different content sources
  - `youtube_scraper.py` - ✅ Active (Phase 1 complete)
  - `bnei_david_scraper.py` - 🚧 TODO: Convert to Firestore
  - `arutz_meir_scraper.py` - 🚧 TODO: Convert to Firestore  
- `functions/utils/firestore_helper.py` - Firestore operations with SQL-compatible interface
- `firebase/firebase.json` - Firebase configuration

### Data Models
Core entities stored in Firestore collections:
- `lessons` - Main lesson content with metadata
- `series` - Lesson series/playlists  
- `categories` - Content categorization
- `ravs` - Rabbis/teachers
- `sources` - Content sources (YouTube channels, websites)
- `labels` - Content tags/labels

### Key Implementation Details

**Firestore Helper**: `functions/utils/firestore_helper.py` provides a PostgreSQL-compatible interface for Firestore, allowing gradual migration of existing scraper code without major rewrites.

**Scraper Pattern**: Each scraper processes a specific content source and uses the firestore_helper to store normalized data in Firestore collections.

**Dual Triggers**: Cloud Functions support both HTTP (manual) and scheduled (Cloud Scheduler) triggers for flexible scraping workflows.

## Current Migration Status

**Phase 1 Complete**: YouTube scraper converted to Firestore  
**Phase 2 Pending**: Convert remaining scrapers (Bnei David, Arutz Meir) from PostgreSQL to Firestore

## Testing

```bash
# Dart tests
pub run test

# Python function testing
cd functions/
python main.py

# Firebase Functions locally
firebase functions:shell
```

## Configuration Files

- `pubspec.yaml` - Dart dependencies and project config
- `functions/requirements.txt` - Python dependencies for Firebase Functions
- `firebase/firebase.json` - Firebase project configuration
- `config.yaml` / `config.src.yaml` - Aqueduct configuration templates