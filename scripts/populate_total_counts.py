#!/usr/bin/env python3
"""
Populate totalCount fields in Firestore collections

This script calculates the actual lesson counts for sources, categories, series, and ravs,
then updates their Firestore documents. Run this once, and the Flutter app can just read
the pre-calculated values without hitting quota limits.
"""

import firebase_admin
from firebase_admin import firestore
import sys

def initialize_firebase():
    try:
        try:
            app = firebase_admin.get_app()
        except ValueError:
            app = firebase_admin.initialize_app(options={'projectId': 'tora-or'})
        return firestore.client()
    except Exception as e:
        print(f"❌ Error initializing Firebase: {e}")
        return None

def populate_source_counts(db, dry_run=True):
    """Calculate and update totalCount for all sources"""
    print("\n📊 SOURCES - Calculating lesson counts...")
    print("=" * 70)

    sources_ref = db.collection('sources')
    sources = sources_ref.stream()

    updates = []

    for source_doc in sources:
        source_data = source_doc.to_dict()
        source_id = source_data.get('originalId')
        source_label = source_data.get('label', 'Unknown')

        # Count lessons for this source
        try:
            count_query = db.collection('lessons').where('sourceId', '==', source_id).count()
            count_result = count_query.get()
            count = count_result[0][0].value if count_result else 0

            print(f"  {source_label} (ID {source_id}): {count:,} lessons")

            updates.append({
                'doc_id': source_doc.id,
                'label': source_label,
                'count': count
            })

        except Exception as e:
            print(f"  ❌ Error counting for {source_label}: {e}")

    print(f"\n✅ Calculated counts for {len(updates)} sources")

    if not dry_run:
        print("💾 Updating Firestore...")
        batch = db.batch()
        for update in updates:
            doc_ref = sources_ref.document(update['doc_id'])
            batch.update(doc_ref, {'totalCount': update['count']})
        batch.commit()
        print("✅ Sources updated in Firestore")

    return updates

def populate_category_counts(db, dry_run=True):
    """Calculate and update totalCount for all categories"""
    print("\n📊 CATEGORIES - Calculating lesson counts...")
    print("=" * 70)

    categories_ref = db.collection('categories')
    categories = categories_ref.stream()

    updates = []
    count_processed = 0

    for category_doc in categories:
        count_processed += 1
        if count_processed % 100 == 0:
            print(f"  Processed {count_processed} categories...")

        category_data = category_doc.to_dict()
        category_id = category_doc.id  # Use Firestore doc ID
        category_name = category_data.get('category', 'Unknown')

        # Count lessons for this category
        try:
            count_query = db.collection('lessons').where('categoryId', '==', category_id).count()
            count_result = count_query.get()
            count = count_result[0][0].value if count_result else 0

            if count > 0:  # Only print non-zero counts
                print(f"  {category_name}: {count:,} lessons")

            updates.append({
                'doc_id': category_doc.id,
                'name': category_name,
                'count': count
            })

        except Exception as e:
            print(f"  ❌ Error counting for {category_name}: {e}")

    print(f"\n✅ Calculated counts for {len(updates)} categories")

    if not dry_run:
        print("💾 Updating Firestore in batches...")
        batch_size = 500
        for i in range(0, len(updates), batch_size):
            batch = db.batch()
            batch_updates = updates[i:i+batch_size]
            for update in batch_updates:
                doc_ref = categories_ref.document(update['doc_id'])
                batch.update(doc_ref, {'totalCount': update['count']})
            batch.commit()
            print(f"  Updated batch {i//batch_size + 1} ({len(batch_updates)} categories)")
        print("✅ Categories updated in Firestore")

    return updates

def populate_series_counts(db, dry_run=True):
    """Calculate and update totalCount for all series"""
    print("\n📊 SERIES - Calculating lesson counts...")
    print("=" * 70)

    series_ref = db.collection('series')
    series = series_ref.stream()

    updates = []
    count_processed = 0

    for series_doc in series:
        count_processed += 1
        if count_processed % 100 == 0:
            print(f"  Processed {count_processed} series...")

        series_data = series_doc.to_dict()
        series_id = series_doc.id  # Use Firestore doc ID
        series_name = series_data.get('serie', 'Unknown')

        # Count lessons for this series
        try:
            count_query = db.collection('lessons').where('seriesId', '==', series_id).count()
            count_result = count_query.get()
            count = count_result[0][0].value if count_result else 0

            if count > 0:  # Only print non-zero counts
                print(f"  {series_name}: {count:,} lessons")

            updates.append({
                'doc_id': series_doc.id,
                'name': series_name,
                'count': count
            })

        except Exception as e:
            print(f"  ❌ Error counting for {series_name}: {e}")

    print(f"\n✅ Calculated counts for {len(updates)} series")

    if not dry_run:
        print("💾 Updating Firestore in batches...")
        batch_size = 500
        for i in range(0, len(updates), batch_size):
            batch = db.batch()
            batch_updates = updates[i:i+batch_size]
            for update in batch_updates:
                doc_ref = series_ref.document(update['doc_id'])
                batch.update(doc_ref, {'totalCount': update['count']})
            batch.commit()
            print(f"  Updated batch {i//batch_size + 1} ({len(batch_updates)} series)")
        print("✅ Series updated in Firestore")

    return updates

def populate_rav_counts(db, dry_run=True):
    """Calculate and update totalCount for all ravs"""
    print("\n📊 RAVS - Calculating lesson counts...")
    print("=" * 70)

    ravs_ref = db.collection('ravs')
    ravs = ravs_ref.stream()

    updates = []
    count_processed = 0

    for rav_doc in ravs:
        count_processed += 1
        if count_processed % 100 == 0:
            print(f"  Processed {count_processed} ravs...")

        rav_data = rav_doc.to_dict()
        rav_id = rav_doc.id  # Use Firestore doc ID
        rav_name = rav_data.get('rav', 'Unknown')

        # Count lessons for this rav
        try:
            count_query = db.collection('lessons').where('ravId', '==', rav_id).count()
            count_result = count_query.get()
            count = count_result[0][0].value if count_result else 0

            if count > 0:  # Only print non-zero counts
                print(f"  {rav_name}: {count:,} lessons")

            updates.append({
                'doc_id': rav_doc.id,
                'name': rav_name,
                'count': count
            })

        except Exception as e:
            print(f"  ❌ Error counting for {rav_name}: {e}")

    print(f"\n✅ Calculated counts for {len(updates)} ravs")

    if not dry_run:
        print("💾 Updating Firestore in batches...")
        batch_size = 500
        for i in range(0, len(updates), batch_size):
            batch = db.batch()
            batch_updates = updates[i:i+batch_size]
            for update in batch_updates:
                doc_ref = ravs_ref.document(update['doc_id'])
                batch.update(doc_ref, {'totalCount': update['count']})
            batch.commit()
            print(f"  Updated batch {i//batch_size + 1} ({len(batch_updates)} ravs)")
        print("✅ Ravs updated in Firestore")

    return updates

def main():
    print()
    print("🔢 POPULATE TOTAL COUNTS IN FIRESTORE")
    print("Calculate lesson counts and update Firestore documents")
    print("=" * 70)
    print()

    # Check for --execute flag
    execute = '--execute' in sys.argv or '-e' in sys.argv

    # Check for --collection flag
    collection = None
    if '--sources' in sys.argv:
        collection = 'sources'
    elif '--categories' in sys.argv:
        collection = 'categories'
    elif '--series' in sys.argv:
        collection = 'series'
    elif '--ravs' in sys.argv:
        collection = 'ravs'

    if not execute:
        print("⚠️  DRY RUN MODE - No changes will be made")
        print("   To execute updates, run with --execute flag")
        print()

    # Initialize Firebase
    db = initialize_firebase()
    if not db:
        return

    # Populate counts
    try:
        if collection == 'sources' or collection is None:
            populate_source_counts(db, dry_run=not execute)

        if collection == 'categories' or collection is None:
            populate_category_counts(db, dry_run=not execute)

        if collection == 'series' or collection is None:
            populate_series_counts(db, dry_run=not execute)

        if collection == 'ravs' or collection is None:
            populate_rav_counts(db, dry_run=not execute)

        print()
        print("=" * 70)
        if execute:
            print("🎉 ALL COUNTS UPDATED IN FIRESTORE!")
            print("   Your Flutter app will now show correct totals")
        else:
            print("✅ DRY RUN COMPLETE - No changes made")
            print("   To update Firestore, run: python populate_total_counts.py --execute")
            print()
            print("   You can also update individual collections:")
            print("   python populate_total_counts.py --execute --sources")
            print("   python populate_total_counts.py --execute --categories")
            print("   python populate_total_counts.py --execute --series")
            print("   python populate_total_counts.py --execute --ravs")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()