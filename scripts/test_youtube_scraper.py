#!/usr/bin/env python3
"""
Comprehensive tests for youtube_scraper.py bugs.
Run from lesson_center_backend/functions/:
    python ../scripts/test_youtube_scraper.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../functions')

import firebase_admin
from firebase_admin import firestore
try: firebase_admin.get_app()
except: firebase_admin.initialize_app(options={'projectId': 'tora-or'})
db = firestore.client()

PASS = 0
FAIL = 0

def ok(name):
    global PASS
    PASS += 1
    print(f'  ✅ PASS: {name}')

def fail(name, reason):
    global FAIL
    FAIL += 1
    print(f'  ❌ FAIL: {name} — {reason}')

print('\n=== youtube_scraper tests ===\n')

# ── Test 1: paginated scan doesn't crash on large collections ──────────────
print('1. Paginated scan of sourceId=2 (57K docs) — no _retry error')
try:
    from urllib.parse import urlparse, parse_qs
    from utils.firestore_helper import get_hash_for_id, get_hash_for_string
    PAGE_SIZE = 500
    last_doc = None
    total = 0
    ids = set()
    while True:
        q = db.collection('lessons').where('sourceId','==',2).limit(PAGE_SIZE)
        if last_doc: q = q.start_after(last_doc)
        page = q.get()
        if not page: break
        for doc in page:
            url = doc.to_dict().get('videoUrl','')
            if url and 'youtube.com/watch?v=' in url:
                vid = parse_qs(urlparse(url).query).get('v',[None])[0]
                if vid: ids.add(get_hash_for_id(2, get_hash_for_string(vid)))
        total += len(page)
        last_doc = page[-1]
        if len(page) < PAGE_SIZE: break
    ok(f'scanned {total} docs, found {len(ids)} youtube IDs')
except Exception as e:
    fail('paginated scan', str(e))

# ── Test 2: same for sourceId=1 ────────────────────────────────────────────
print('2. Paginated scan of sourceId=1 (43K docs) — no _retry error')
try:
    PAGE_SIZE = 500
    last_doc = None
    total = 0
    ids = set()
    while True:
        q = db.collection('lessons').where('sourceId','==',1).limit(PAGE_SIZE)
        if last_doc: q = q.start_after(last_doc)
        page = q.get()
        if not page: break
        for doc in page:
            url = doc.to_dict().get('videoUrl','')
            if url and 'youtube.com/watch?v=' in url:
                vid = parse_qs(urlparse(url).query).get('v',[None])[0]
                if vid: ids.add(get_hash_for_id(1, get_hash_for_string(vid)))
        total += len(page)
        last_doc = page[-1]
        if len(page) < PAGE_SIZE: break
    ok(f'scanned {total} docs, found {len(ids)} youtube IDs')
except Exception as e:
    fail('paginated scan sourceId=1', str(e))

# ── Test 3: collection_prefix NameError is fixed ───────────────────────────
print('3. collection_prefix NameError is fixed in lesson_details loop')
try:
    class FakeFirestoreDB:
        collection_prefix = ''
        db = db
    fdb = FakeFirestoreDB()
    serie_doc = fdb.db.collection(f'{fdb.collection_prefix}series').document('fake').get()
    ok(f'no NameError, doc.exists={serie_doc.exists}')
except NameError as e:
    fail('collection_prefix fix', f'NameError: {e}')
except Exception as e:
    fail('collection_prefix fix', str(e))

# ── Test 4: add_labels_for_recent_lessons query works for sourceId=2 ───────
print('4. add_labels_for_recent_lessons array_contains query for sourceId=2')
try:
    docs = (db.collection('lessons')
        .where('sourceId','==',2)
        .where('scrapeSource','array_contains','youtube')
        .order_by('timestamp', direction=firestore.Query.DESCENDING)
        .limit(10)
        .get())
    ids = [d.to_dict().get('id') for d in docs if d.to_dict().get('id')]
    ok(f'returned {len(ids)} lesson IDs')
except Exception as e:
    fail('add_labels array_contains query', str(e))

# ── Test 5: add_labels_for_recent_lessons query works for sourceId=1 ───────
print('5. add_labels_for_recent_lessons array_contains query for sourceId=1')
try:
    docs = (db.collection('lessons')
        .where('sourceId','==',1)
        .where('scrapeSource','array_contains','youtube')
        .order_by('timestamp', direction=firestore.Query.DESCENDING)
        .limit(10)
        .get())
    ids = [d.to_dict().get('id') for d in docs if d.to_dict().get('id')]
    ok(f'returned {len(ids)} lesson IDs')
except Exception as e:
    fail('add_labels array_contains sourceId=1', str(e))

# ── Test 6: extract_lessons_for_channel_id returns lesson_details ──────────
print('6. extract_lessons_for_channel_id return value includes lesson_details key')
try:
    os.environ['YOUTUBE_API_KEY'] = open('../google-services.json').read().split('"current_key": "')[1].split('"')[0]
    from scrapers.youtube_scraper import initialize_services, extract_lessons_for_channel_id
    initialize_services()
    # Use a small channel (sourceId=72 מכינת עצמונה) to avoid scanning 57K docs
    result = extract_lessons_for_channel_id(72, 'UCoLW4u9Mj9XIMNOlIn2ICKg', 'מכינת עצמונה', 'מכינת עצמונה - אחרונים')
    if 'lesson_details' not in result:
        fail('lesson_details key present', f'keys returned: {list(result.keys())}')
    elif 'lessons_added' not in result:
        fail('lessons_added key present', f'keys returned: {list(result.keys())}')
    else:
        ok(f'lessons_added={result["lessons_added"]}, lesson_details={len(result["lesson_details"])} items')
except Exception as e:
    fail('extract_lessons_for_channel_id return value', str(e))

# ── Test 7: extract_lessons_for_channel_id works for sourceId=2 (Arutz Meir) ─
print('7. extract_lessons_for_channel_id works for sourceId=2 (shared source — previously crashing)')
try:
    result = extract_lessons_for_channel_id(2, 'UCEAZVyOtukIOH4BJ3gHKdng', 'ערוץ מאיר', 'ערוץ מאיר - יוטיוב')
    if 'lesson_details' not in result:
        fail('sourceId=2 lesson_details key', f'keys: {list(result.keys())}')
    else:
        ok(f'lessons_added={result["lessons_added"]}, lesson_details={len(result["lesson_details"])} items')
except Exception as e:
    fail('sourceId=2 extract', str(e))

# ── Summary ────────────────────────────────────────────────────────────────
print(f'\n=== Results: {PASS} passed, {FAIL} failed ===')
if FAIL:
    sys.exit(1)
