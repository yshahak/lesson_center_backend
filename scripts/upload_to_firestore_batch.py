#!/usr/bin/env python3
"""
Efficient Batch Firestore Upload Script
Uploads documents in small batches with rate limiting
"""

import json
import os
import sys
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import time
from google.cloud.exceptions import GoogleCloudError

class BatchFirestoreUploader:
    def __init__(self, project_id="tora-or"):
        """Initialize Firebase Admin SDK"""
        try:
            firebase_admin.initialize_app(options={'projectId': project_id})
        except Exception as e:
            print(f"Error initializing Firebase: {e}")
            sys.exit(1)
        
        self.db = firestore.client()
        self.batch_size = 100  # Smaller batches for better reliability
        self.delay_between_batches = 1.0  # Seconds to wait between batches
        
    def upload_collection_batch(self, collection_name, data_file, start_index=0, max_documents=None):
        """Upload a collection in batches with rate limiting"""
        print(f"\n📁 Uploading {collection_name} (starting from index {start_index})...")
        
        if not os.path.exists(data_file):
            print(f"❌ File not found: {data_file}")
            return 0
        
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not data:
                print(f"⚠️  No data found in {data_file}")
                return 0
            
            # Convert to list for indexing
            items = list(data.items())
            total_docs = len(items)
            
            # Apply limits
            if start_index >= total_docs:
                print(f"❌ Start index {start_index} is beyond total documents {total_docs}")
                return 0
                
            items = items[start_index:]
            if max_documents:
                items = items[:max_documents]
            
            docs_to_upload = len(items)
            print(f"📊 Will upload {docs_to_upload:,} documents (from {start_index} to {start_index + docs_to_upload - 1})")
            
            collection_ref = self.db.collection(collection_name)
            uploaded = 0
            errors = 0
            
            for i in range(0, len(items), self.batch_size):
                batch_items = items[i:i + self.batch_size]
                
                try:
                    # Use batch write
                    batch = self.db.batch()
                    
                    for doc_id, doc_data in batch_items:
                        # Use originalId as document ID for consistency
                        original_id = doc_data.get('originalId', doc_id)
                        doc_ref = collection_ref.document(str(original_id))
                        batch.set(doc_ref, doc_data, merge=True)  # merge=True prevents overwriting
                    
                    batch.commit()
                    uploaded += len(batch_items)
                    
                    progress = (uploaded / docs_to_upload) * 100
                    current_index = start_index + uploaded
                    print(f"  ✅ Uploaded batch {i//self.batch_size + 1} | {uploaded:,}/{docs_to_upload:,} ({progress:.1f}%) | Index: {current_index}")
                    
                    # Rate limiting
                    if i < len(items) - self.batch_size:
                        time.sleep(self.delay_between_batches)
                
                except GoogleCloudError as e:
                    if "429" in str(e) or "quota" in str(e).lower():
                        print(f"  ⚠️  Quota exceeded! Stopping upload.")
                        print(f"  📊 Uploaded {uploaded:,} documents before hitting quota limit")
                        errors += len(batch_items)
                        break  # Exit the batch loop immediately
                    else:
                        print(f"  ❌ Error uploading batch {i//self.batch_size + 1}: {e}")
                        errors += len(batch_items)
                
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower():
                        print(f"  ⚠️  Quota exceeded! Stopping upload.")
                        print(f"  📊 Uploaded {uploaded:,} documents before hitting quota limit")
                        errors += len(batch_items)
                        break  # Exit the batch loop immediately
                    else:
                        print(f"  ❌ Error uploading batch {i//self.batch_size + 1}: {e}")
                        errors += len(batch_items)
            
            print(f"✅ Upload complete: {uploaded:,} documents, {errors} errors")
            return uploaded
            
        except Exception as e:
            print(f"❌ Error processing {collection_name}: {e}")
            return 0

def main():
    """Main function - uploads lessons in continuous batches until quota limit"""
    
    # CONFIGURATION - Change these as needed
    LESSONS_ONLY = True  # Set to False to upload all collections
    LESSONS_START_INDEX = 98600  # Where to start lessons upload (FINAL BATCH - only 1,188 lessons left!)
    
    if LESSONS_ONLY:
        print("🚀 Continuous Lessons Uploader")
        print("=" * 50)
        print("📋 Strategy: Upload lessons in 5000-doc batches until quota limit")
    else:
        print("🚀 Continuous All Collections Uploader")
        print("=" * 50)
        print("📋 Strategy: Upload all collections until quota limit")
    
    uploader = BatchFirestoreUploader()
    
    if LESSONS_ONLY:
        # LESSONS-ONLY MODE
        upload_lessons_continuously(uploader, LESSONS_START_INDEX)
    else:
        # ALL COLLECTIONS MODE
        upload_all_collections_continuously(uploader, LESSONS_START_INDEX)

def upload_lessons_continuously(uploader, start_index):
    """Upload lessons continuously until quota limit or completion"""
    # Load lessons data once to check total count
    try:
        with open('firestore_data/lessons.json', 'r', encoding='utf-8') as f:
            lessons_data = json.load(f)
        total_lessons = len(lessons_data)
        print(f"📊 Total lessons in JSON: {total_lessons:,}")
    except Exception as e:
        print(f"❌ Error loading lessons data: {e}")
        return
    
    batch_size = 5000
    current_index = start_index
    total_uploaded = 0
    quota_exceeded = False
    
    print(f"\n🎯 Starting continuous upload from index {current_index:,}")
    print(f"📈 Progress: {current_index:,}/{total_lessons:,} ({current_index/total_lessons*100:.1f}%)")
    
    while current_index < total_lessons and not quota_exceeded:
        remaining_lessons = total_lessons - current_index
        docs_to_upload = min(batch_size, remaining_lessons)
        
        print(f"\n🔄 Batch {(current_index // batch_size) + 1}: Uploading {docs_to_upload:,} lessons (index {current_index:,} to {current_index + docs_to_upload - 1:,})")
        
        try:
            lessons_uploaded = uploader.upload_collection_batch(
                'lessons', 
                'firestore_data/lessons.json', 
                start_index=current_index, 
                max_documents=docs_to_upload
            )
            
            if lessons_uploaded > 0:
                total_uploaded += lessons_uploaded
                current_index += lessons_uploaded
                
                progress = (current_index / total_lessons) * 100
                print(f"✅ Batch complete! Total uploaded: {total_uploaded:,} | Progress: {current_index:,}/{total_lessons:,} ({progress:.1f}%)")
                
                if current_index >= total_lessons:
                    print(f"🎉 ALL LESSONS UPLOADED! {total_lessons:,} lessons complete!")
                    break
                    
            else:
                print(f"⚠️  No lessons uploaded in this batch - may have hit quota limit")
                quota_exceeded = True
                break  # Exit the loop immediately
                
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                print(f"⚠️  Quota limit reached: {e}")
                quota_exceeded = True
                break  # Exit the loop immediately
            else:
                print(f"❌ Error in batch upload: {e}")
                break
    
    # Final summary
    print(f"\n📊 UPLOAD SESSION COMPLETE")
    print(f"✅ Uploaded this session: {total_uploaded:,} lessons")
    print(f"📈 Total progress: {current_index:,}/{total_lessons:,} ({current_index/total_lessons*100:.1f}%)")
    print(f"📝 Next start index: {current_index:,}")
    
    if current_index >= total_lessons:
        print(f"🎉 MIGRATION COMPLETE! All {total_lessons:,} lessons uploaded to Firestore!")
    elif quota_exceeded:
        print(f"⏰ Quota limit reached. Run script again later to continue from index {current_index:,}")
    else:
        print(f"🔄 Run script again to continue from index {current_index:,}")

def upload_all_collections_continuously(uploader, lessons_start_index):
    """Upload all collections continuously until quota limit"""
    collections = [
        ('sources', 'firestore_data/sources.json'),
        ('categories', 'firestore_data/categories.json'),
        ('series', 'firestore_data/series.json'),
        ('ravs', 'firestore_data/ravs.json'),
        ('labels', 'firestore_data/labels.json')
    ]
    
    quota_exceeded = False
    
    # Upload other collections first (smaller ones)
    for collection_name, file_path in collections:
        if quota_exceeded:
            break
            
        try:
            uploaded = uploader.upload_collection_batch(collection_name, file_path)
            if uploaded > 0:
                print(f"✅ Uploaded {uploaded:,} {collection_name}")
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                print(f"⚠️  Quota limit reached while uploading {collection_name}: {e}")
                quota_exceeded = True
                break
            else:
                print(f"❌ Error uploading {collection_name}: {e}")
    
    # Then upload lessons if quota not exceeded
    if not quota_exceeded:
        print(f"\n📚 Now uploading lessons...")
        upload_lessons_continuously(uploader, lessons_start_index)
    else:
        print(f"\n⏰ Quota exceeded during collections upload. Run again later.")

if __name__ == "__main__":
    main() 