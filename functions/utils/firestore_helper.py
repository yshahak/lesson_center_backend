#!/usr/bin/env python3
"""
Firestore Helper for Firebase Cloud Functions
Handles all Firestore operations and maintains compatibility with original SQL interface
"""

import firebase_admin
from firebase_admin import credentials, firestore
import sys
import hashlib
import datetime
import re
from pyluach.dates import HebrewDate
import isodate
import logging

logger = logging.getLogger(__name__)

class FirestoreConnection:
    """Replaces PostgreSQL connection with Firestore client"""
    
    def __init__(self, project_id="tora-or", collection_prefix=""):
        """Initialize Firebase Admin SDK"""
        try:
            # Try to get existing app first
            try:
                self.app = firebase_admin.get_app()
            except ValueError:
                # App doesn't exist, create it
                self.app = firebase_admin.initialize_app(options={'projectId': project_id})
        except Exception as e:
            logger.error(f"Error initializing Firebase: {e}")
            sys.exit(1)
        
        self.db = firestore.client()
        self.collection_prefix = collection_prefix
        self._cache = {
            'lessons': {},
            'series': {},
            'categories': {},
            'ravs': {},
            'sources': {}
        }
        
    def cursor(self):
        """Returns a Firestore cursor object that mimics PostgreSQL cursor"""
        return FirestoreCursor(self.db, self._cache, self.collection_prefix)
    
    def commit(self):
        """Firestore auto-commits, so this is a no-op for compatibility"""
        pass
    
    def close(self):
        """Cleanup if needed"""
        pass

class FirestoreCursor:
    """Mimics PostgreSQL cursor interface for Firestore operations"""
    
    def __init__(self, db, cache, collection_prefix=""):
        self.db = db
        self.cache = cache
        self.collection_prefix = collection_prefix
        self.last_results = []
        
    def execute(self, query, params=None):
        """Execute Firestore equivalent of SQL queries"""
        query = query.strip()
        
        if query.startswith('select "originalId" from lessons'):
            # Get existing lesson originalIds for a source
            source_id = params[0] if params else None
            self._get_existing_lesson_ids(source_id)
            
        elif query.startswith('select "originalId",id from series'):
            # Get series mapping for a source
            source_id = self._extract_source_id_from_query(query, params)
            self._get_series_mapping(source_id)
            
        elif query.startswith('select "originalId",id from categories'):
            # Get categories mapping for a source
            source_id = self._extract_source_id_from_query(query, params)
            self._get_categories_mapping(source_id)
            
        elif query.startswith('select "originalId",id from ravs'):
            # Get ravs mapping for a source
            source_id = self._extract_source_id_from_query(query, params)
            self._get_ravs_mapping(source_id)
            
        elif query.startswith('select id from lessons') or query.startswith('SELECT id from lessons'):
            # Get existing lesson IDs
            logger.debug(f"Processing lessons query: {query}")
            if 'AND "categoryId"' in query or 'AND categoryId' in query:
                # Query with both sourceId and categoryId
                logger.debug(f"Using source+category query with params: {params}")
                source_id = params[0] if params and len(params) > 0 else None
                category_id = params[1] if params and len(params) > 1 else None
                self._get_existing_lesson_ids_by_source_and_category(source_id, category_id)
            else:
                # Query with just sourceId
                logger.debug(f"Using source-only query with params: {params}")
                source_id = params[0] if params else None
                self._get_existing_lesson_full_ids(source_id)
            
        elif query.startswith('select id from series'):
            # Get existing series IDs
            source_id = params[0] if params else None
            self._get_existing_series_ids(source_id)
            
        elif query.startswith('select id from categories'):
            # Get existing category IDs
            source_id = params[0] if params else None
            self._get_existing_category_ids(source_id)
            
        elif query.startswith('DELETE FROM labels'):
            # Clear labels for a source
            source_id = params[0] if params else None
            self._clear_labels(source_id)
            
        elif query.startswith('INSERT INTO categories'):
            # Insert category
            self._insert_category(params)
            
        elif query.startswith('INSERT INTO series'):
            # Insert series
            self._insert_series(params)
            
        elif query.startswith('INSERT INTO ravs'):
            # Insert rav
            self._insert_rav(params)
            
        elif query.startswith('INSERT INTO sources'):
            # Insert source
            self._insert_source(params)
            
        elif query.startswith('INSERT INTO labels'):
            # Insert label
            self._insert_label(params)
            
        else:
            logger.warning(f"Unhandled query: {query[:50]}...")
    
    def fetchall(self):
        """Return last query results"""
        return self.last_results
    
    def close(self):
        """Cleanup if needed"""
        pass
    
    def _extract_source_id_from_query(self, query, params):
        """Extract source ID from WHERE clause"""
        if params and len(params) > 0:
            return params[0]
        if '"sourceId" = 1' in query:
            return 1
        return None
    
    def _get_existing_lesson_ids(self, source_id):
        """Get existing lesson originalIds for duplicate checking"""
        try:
            lessons_ref = self.db.collection(f'{self.collection_prefix}lessons')
            if source_id:
                query = lessons_ref.where('sourceId', '==', source_id)
            else:
                query = lessons_ref
            
            docs = query.select(['originalId']).get()
            self.last_results = [(doc.to_dict().get('originalId'),) for doc in docs]
            
        except Exception as e:
            logger.error(f"Error fetching lesson IDs: {e}")
            self.last_results = []
    
    def _get_existing_lesson_full_ids(self, source_id):
        """Get existing lesson full IDs"""
        try:
            lessons_ref = self.db.collection(f'{self.collection_prefix}lessons')
            if source_id:
                query = lessons_ref.where('sourceId', '==', source_id)
            else:
                query = lessons_ref
            
            docs = query.select(['id']).get()
            self.last_results = [(doc.to_dict().get('id'),) for doc in docs]
            
        except Exception as e:
            logger.error(f"Error fetching lesson full IDs: {e}")
            self.last_results = []
    
    def _get_existing_lesson_ids_by_source_and_category(self, source_id, category_id):
        """Get existing lesson IDs for a source and category"""
        try:
            lessons_ref = self.db.collection(f'{self.collection_prefix}lessons')
            if source_id and category_id:
                query = lessons_ref.where('sourceId', '==', source_id).where('categoryId', '==', category_id)
                docs = query.select(['id']).get()
                self.last_results = [(doc.to_dict().get('id'),) for doc in docs]
                logger.info(f"Found {len(self.last_results)} lessons for source {source_id} and category {category_id}")
            else:
                self.last_results = []
        except Exception as e:
            logger.error(f"Error fetching lesson IDs by source and category: {e}")
            self.last_results = []
    
    def _get_series_mapping(self, source_id):
        """Get originalId to id mapping for series"""
        try:
            series_ref = self.db.collection(f'{self.collection_prefix}series')
            if source_id:
                query = series_ref.where('sourceId', '==', source_id)
            else:
                query = series_ref
            
            docs = query.select(['originalId', 'id']).get()
            self.last_results = [(doc.to_dict().get('originalId'), doc.to_dict().get('id')) for doc in docs]
            
        except Exception as e:
            logger.error(f"Error fetching series mapping: {e}")
            self.last_results = []
    
    def _get_categories_mapping(self, source_id):
        """Get originalId to id mapping for categories"""
        try:
            categories_ref = self.db.collection(f'{self.collection_prefix}categories')
            if source_id:
                query = categories_ref.where('sourceId', '==', source_id)
            else:
                query = categories_ref
            
            docs = query.select(['originalId', 'id']).get()
            self.last_results = [(doc.to_dict().get('originalId'), doc.to_dict().get('id')) for doc in docs]
            
        except Exception as e:
            logger.error(f"Error fetching categories mapping: {e}")
            self.last_results = []
    
    def _get_ravs_mapping(self, source_id):
        """Get originalId to id mapping for ravs"""
        try:
            ravs_ref = self.db.collection(f'{self.collection_prefix}ravs')
            if source_id:
                query = ravs_ref.where('sourceId', '==', source_id)
            else:
                query = ravs_ref
            
            docs = query.select(['originalId', 'id']).get()
            self.last_results = [(doc.to_dict().get('originalId'), doc.to_dict().get('id')) for doc in docs]
            
        except Exception as e:
            logger.error(f"Error fetching ravs mapping: {e}")
            self.last_results = []
    
    def _get_existing_series_ids(self, source_id):
        """Get existing series IDs"""
        try:
            series_ref = self.db.collection(f'{self.collection_prefix}series')
            if source_id:
                query = series_ref.where('sourceId', '==', source_id)
            else:
                query = series_ref
            
            docs = query.select(['id']).get()
            self.last_results = [(doc.to_dict().get('id'),) for doc in docs]
            
        except Exception as e:
            logger.error(f"Error fetching series IDs: {e}")
            self.last_results = []
    
    def _get_existing_category_ids(self, source_id):
        """Get existing category IDs"""
        try:
            categories_ref = self.db.collection(f'{self.collection_prefix}categories')
            if source_id:
                query = categories_ref.where('sourceId', '==', source_id)
            else:
                query = categories_ref
            
            docs = query.select(['id']).get()
            self.last_results = [(doc.to_dict().get('id'),) for doc in docs]
            
        except Exception as e:
            logger.error(f"Error fetching category IDs: {e}")
            self.last_results = []
    
    def _clear_labels(self, source_id):
        """Clear labels for a source"""
        try:
            labels_ref = self.db.collection(f'{self.collection_prefix}labels')
            query = labels_ref.where('sourceId', '==', source_id)
            docs = query.get()
            
            batch = self.db.batch()
            for doc in docs:
                batch.delete(doc.reference)
            
            if len(docs) > 0:
                batch.commit()
                logger.info(f"Cleared {len(docs)} labels for source {source_id}")
                
        except Exception as e:
            logger.error(f"Error clearing labels: {e}")
    
    def _insert_category(self, params):
        """Insert category into Firestore"""
        try:
            category_id, original_id, source_id, category = params
            doc_ref = self.db.collection(f'{self.collection_prefix}categories').document(str(category_id))
            
            doc_ref.set({
                'id': category_id,
                'originalId': original_id,
                'sourceId': source_id,
                'category': category,
                'createdAt': firestore.SERVER_TIMESTAMP,
                'updatedAt': firestore.SERVER_TIMESTAMP
            }, merge=True)
            
        except Exception as e:
            logger.error(f"Error inserting category: {e}")
    
    def _insert_series(self, params):
        """Insert series into Firestore"""
        try:
            series_id, original_id, source_id, series_name = params
            doc_ref = self.db.collection(f'{self.collection_prefix}series').document(str(series_id))
            
            doc_ref.set({
                'id': series_id,
                'originalId': original_id,
                'sourceId': source_id,
                'series': series_name,
                'createdAt': firestore.SERVER_TIMESTAMP,
                'updatedAt': firestore.SERVER_TIMESTAMP
            }, merge=True)
            
        except Exception as e:
            logger.error(f"Error inserting series: {e}")
    
    def _insert_rav(self, params):
        """Insert rav into Firestore"""
        try:
            rav_id, original_id, source_id, total_count, rav_name = params
            doc_ref = self.db.collection(f'{self.collection_prefix}ravs').document(str(rav_id))
            
            doc_ref.set({
                'id': rav_id,
                'originalId': original_id,
                'sourceId': source_id,
                'totalCount': total_count,
                'rav': rav_name,
                'createdAt': firestore.SERVER_TIMESTAMP,
                'updatedAt': firestore.SERVER_TIMESTAMP
            }, merge=True)
            
        except Exception as e:
            logger.error(f"Error inserting rav: {e}")
    
    def _insert_source(self, params):
        """Insert source into Firestore"""
        try:
            source_id, source_name = params
            doc_ref = self.db.collection(f'{self.collection_prefix}sources').document(str(source_id))
            
            doc_ref.set({
                'id': source_id,
                'source': source_name,
                'createdAt': firestore.SERVER_TIMESTAMP,
                'updatedAt': firestore.SERVER_TIMESTAMP
            }, merge=True)
            
        except Exception as e:
            logger.error(f"Error inserting source: {e}")
    
    def _insert_label(self, params):
        """Insert label into Firestore with aggregated lessonIds array"""
        try:
            label, source_id, lesson_id = params
            # Create document ID based on label name only (not lesson ID)
            # This ensures one document per label name
            label_id = get_hash_for_string(f"{source_id}_{label}")
            doc_ref = self.db.collection(f'{self.collection_prefix}labels').document(str(label_id))

            # Use ArrayUnion to append lesson ID without reading document first
            # This creates aggregated labels: one doc per label name with array of lesson IDs
            doc_ref.set({
                'label': label,
                'sourceId': source_id,
                'lessonIds': firestore.ArrayUnion([str(lesson_id)]),  # Plural with array!
                'updatedAt': firestore.SERVER_TIMESTAMP
            }, merge=True)

            # Set createdAt only on first creation (merge=True preserves existing createdAt)
            doc_ref.set({
                'createdAt': firestore.SERVER_TIMESTAMP
            }, merge=True)

        except Exception as e:
            logger.error(f"Error inserting label: {e}")

def add_lesson_to_db(cursor, body):
    """Add lesson to Firestore - replaces PostgreSQL version"""
    logger.info(f"Adding lesson to Firestore: {body.get('title', 'Unknown')}")
    
    try:
        lesson_id = body["id"]
        doc_ref = cursor.db.collection(f'{cursor.collection_prefix}lessons').document(str(lesson_id))
        
        # Add Firestore-specific fields
        lesson_data = body.copy()
        lesson_data['createdAt'] = firestore.SERVER_TIMESTAMP
        lesson_data['updatedAt'] = firestore.SERVER_TIMESTAMP
        
        # Use merge=True to avoid overwriting existing data
        doc_ref.set(lesson_data, merge=True)
        
    except Exception as e:
        logger.error(f"Error adding lesson to Firestore: {e}")
        raise

def clear_labels(firestore_conn, source_id):
    """Clear labels for a source - Firestore version"""
    cursor = firestore_conn.cursor()
    cursor.execute('''DELETE FROM labels WHERE "sourceId" = %s;''', (source_id,))
    firestore_conn.commit()

# Helper functions from original sql_helper.py
def get_hash_for_id(source_id: int, originalid: int) -> int:
    hash_object = hashlib.md5(('%s_%s' % (source_id, originalid,)).encode())
    return int(hash_object.hexdigest(), 16) % 10 ** 18

def get_hash_for_string(originalid: str) -> int:
    hash_object = hashlib.md5(originalid.encode())
    return int(hash_object.hexdigest(), 16) % 10 ** 18

def get_timestamp():
    return int((datetime.datetime.utcnow() - datetime.datetime(1970, 1, 1)).total_seconds())

def get_heb_date(date_time_obj):
    heb = HebrewDate.from_pydate(date_time_obj)
    month = (month_dict[heb.month])
    remains = heb.year - 5700
    dosens = 10 * int(remains / 10)
    last = remains % 10
    year = u'התש%s%s' % (gimatria_map[dosens], gimatria_map[last])
    heb_date = '%s %s %s' % (day_list[heb.day], month, year)
    return heb_date

def get_duration_in_seconds(duration: str):
    if not duration:
        return 0
    try:
        correct = re.sub('[^0-9:]', "", duration)
        while len(correct.split(':')) < 3:
            correct = "00:%s" % correct
        h, m, s = correct.split(':')
        return int(datetime.timedelta(hours=int(h), minutes=int(m), seconds=int(s)).total_seconds())
    except:
        logger.warning(f'Duration issue: {duration}')
        return 0

def get_iso_duration_in_seconds(duration: str):
    if not duration:
        return 0
    try:
        return int(isodate.parse_duration(duration).total_seconds())
    except:
        logger.warning(f'ISO duration issue: {duration}')
        return 0

# Hebrew date mappings (from original sql_helper.py)
month_dict = {
    u'תשרי': 7, u'חשון': 8, u'חשוון': 8, u'כסלו': 9, u'טבת': 10, u'שבט': 11,
    u'אדר': 12, u'אדר א': 12, u'אדר ב': 13, u'ניסן': 1, u'אייר': 2, u'איר': 2,
    u'סיון': 3, u'סיוון': 3, u'תמוז': 4, u'אב': 5, u'אלול': 6,
}

gimatria_map = {
    u'': 0, u'א': 1, u'ב': 2, u'ג': 3, u'ד': 4, u'ה': 5, u'ו': 6, u'ז': 7, u'ח': 8, u'ט': 9,
    u'י': 10, u'כ': 20, u'ל': 30, u'מ': 40, u'נ': 50, u'ס': 60, u'ע': 70, u'פ': 80, u'צ': 90,
    u'ק': 100, u'ר': 200, u'ש': 300, u'ת': 400,
}

day_list = [
    u' ', u'א', u'ב', u'ג', u'ד', u'ה', u'ו', u'ז', u'ח', u'ט', u'י', u'יא', u'יב', u'יג', u'יד',
    u'טו', u'טז', u'יז', u'יח', u'יט', u'כ', u'כא', u'כב', u'כג', u'כד', u'כה', u'כו', u'כז', u'כח', u'כט', u'ל',
]

month_dict = {value: key for key, value in month_dict.items()}
gimatria_map = {value: key for key, value in gimatria_map.items()} 