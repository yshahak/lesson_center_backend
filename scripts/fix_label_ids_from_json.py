#!/usr/bin/env python3
"""
Fix label lesson IDs by mapping lesson_XXX keys to originalId values

Problem: Labels have lessonIds like ["lesson_532de705ff1c43bfbf1a"]
         But lessons are stored with originalId as document ID (numeric)

Solution: Load lessons.json, create mapping, update all labels in Firestore
"""

import json
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

def build_lesson_key_to_id_mapping(lessons_file):
    """Build mapping from lesson_XXX JSON keys to originalId values"""
    print("🔍 Building lesson key → ID mapping from JSON...")
    print("=" * 70)

    try:
        with open(lessons_file, 'r', encoding='utf-8') as f:
            lessons_data = json.load(f)

        mapping = {}
        for lesson_key, lesson_data in lessons_data.items():
            original_id = lesson_data.get('originalId')
            if original_id:
                mapping[lesson_key] = str(original_id)

        print(f"✅ Created mapping for {len(mapping):,} lessons")
        print(f"   Example: {list(mapping.items())[0]}")
        print()

        return mapping

    except Exception as e:
        print(f"❌ Error loading lessons: {e}")
        return {}

def fix_labels_in_firestore(db, mapping, dry_run=True):
    """Fix lesson IDs in all label documents"""

    if dry_run:
        print("🧪 DRY RUN MODE - No changes will be made")
    else:
        print("🚀 MIGRATION MODE - Making actual changes")

    print("=" * 70)
    print()

    labels_ref = db.collection('labels')
    labels = labels_ref.stream()

    total_labels = 0
    fixed_labels = 0
    total_ids_mapped = 0
    total_ids_unmapped = 0

    for doc in labels:
        total_labels += 1
        data = doc.to_dict()
        label_name = data.get('label', 'Unknown')
        lesson_ids = data.get('lessonIds', [])

        if not lesson_ids:
            continue

        # Map lesson_XXX keys to numeric IDs
        fixed_ids = []
        unmapped_ids = []

        for lid in lesson_ids:
            lid_str = str(lid)
            if lid_str in mapping:
                fixed_ids.append(mapping[lid_str])
                total_ids_mapped += 1
            else:
                # Check if it's already numeric (already fixed)
                if not lid_str.startswith('lesson_'):
                    fixed_ids.append(lid_str)
                else:
                    unmapped_ids.append(lid_str)
                    total_ids_unmapped += 1

        if fixed_ids != lesson_ids:
            fixed_labels += 1

            print(f"📝 {label_name}")
            print(f"   Lesson IDs: {len(lesson_ids)} → {len(fixed_ids)} mapped, {len(unmapped_ids)} unmapped")

            if unmapped_ids and len(unmapped_ids) <= 3:
                print(f"   ⚠️  Unmapped: {unmapped_ids}")

            if not dry_run and fixed_ids:
                # Update the document
                doc.reference.update({
                    'lessonIds': fixed_ids,
                    'updatedAt': firestore.SERVER_TIMESTAMP
                })

    print()
    print("=" * 70)
    if dry_run:
        print(f"📊 DRY RUN Summary:")
        print(f"  Total labels: {total_labels}")
        print(f"  Labels needing fixes: {fixed_labels}")
        print(f"  Lesson IDs that would be mapped: {total_ids_mapped:,}")
        print(f"  Lesson IDs that couldn't be mapped: {total_ids_unmapped}")
        print()
        print("✅ To perform actual migration, run with --execute flag")
    else:
        print(f"✅ MIGRATION COMPLETE!")
        print(f"  Total labels: {total_labels}")
        print(f"  Labels fixed: {fixed_labels}")
        print(f"  Lesson IDs mapped: {total_ids_mapped:,}")
        print(f"  Lesson IDs unmapped: {total_ids_unmapped}")

def verify_labels(db):
    """Verify labels have correct numeric IDs"""
    print()
    print("🔍 Verifying labels...")
    print("=" * 70)

    labels_ref = db.collection('labels')
    labels = labels_ref.limit(5).stream()

    for doc in labels:
        data = doc.to_dict()
        label_name = data.get('label', 'Unknown')
        lesson_ids = data.get('lessonIds', [])

        has_lesson_prefix = any(str(lid).startswith('lesson_') for lid in lesson_ids)

        print(f"📝 {label_name}")
        print(f"   Lesson IDs: {len(lesson_ids)}")
        if lesson_ids:
            print(f"   Sample: {lesson_ids[:3]}")
            if has_lesson_prefix:
                print(f"   ⚠️  Still has 'lesson_' prefixes!")
            else:
                print(f"   ✅ IDs look correct (numeric)")
        print()

def main():
    print()
    print("🔧 FIX LABEL LESSON IDS FROM JSON MAPPING")
    print("Map lesson_XXX keys to originalId numeric values")
    print("=" * 70)
    print()

    # Check for --execute flag
    execute = '--execute' in sys.argv or '-e' in sys.argv

    # Initialize Firebase
    db = initialize_firebase()
    if not db:
        return

    # Build mapping from lessons.json
    lessons_file = 'firestore_data/lessons.json'
    mapping = build_lesson_key_to_id_mapping(lessons_file)

    if not mapping:
        print("❌ Failed to build mapping")
        return

    # Fix labels
    if not execute:
        print("⚠️  This is a DRY RUN. No changes will be made.")
        print("   To execute the migration, run: python fix_label_ids_from_json.py --execute")
        print()

    fix_labels_in_firestore(db, mapping, dry_run=not execute)

    # Verify if actual migration was performed
    if execute:
        verify_labels(db)

if __name__ == '__main__':
    main()