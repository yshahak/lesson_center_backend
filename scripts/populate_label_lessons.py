#!/usr/bin/env python3
"""
Populate empty label documents with recent lesson IDs from Firestore.

The "אחרונים" labels (e.g. "ישיבת הר עציון - אחרונים") are meant to show the
10 most recent lessons for each yeshiva/source. They are normally populated by
the Cloud Functions scrapers. Since scrapers aren't deployed, these labels have
empty lessonIds arrays.

This script matches each empty label to a source by name, queries the most
recent lessons for that source from Firestore, and updates the label.

Usage:
    python scripts/populate_label_lessons.py
    python scripts/populate_label_lessons.py --dry-run
    python scripts/populate_label_lessons.py --lessons-per-label 20
"""

import argparse
import re

import firebase_admin
from firebase_admin import firestore

PROJECT_ID = "tora-or"
DEFAULT_LESSONS_PER_LABEL = 10


def init_firebase():
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def normalize(text):
    """Strip common suffixes for fuzzy name matching."""
    text = text.strip()
    for suffix in [" - אחרונים", " - יוטיוב", " - ערוץ יוטיוב"]:
        text = text.replace(suffix, "")
    return text.strip()


def populate_labels(dry_run=False, lessons_per_label=DEFAULT_LESSONS_PER_LABEL):
    init_firebase()
    db = firestore.client()

    # Load all label documents
    print("Loading labels...")
    labels = [(doc.id, doc.reference, doc.to_dict()) for doc in db.collection("labels").stream()]
    empty_labels = [(lid, ref, data) for lid, ref, data in labels
                    if not data.get("lessonIds")]
    print(f"Total labels: {len(labels)}, empty: {len(empty_labels)}")

    if not empty_labels:
        print("All labels already have lesson IDs — nothing to do.")
        return

    # Load all sources to build name → sourceId map
    print("Loading sources...")
    sources = {doc.to_dict().get("label", ""): doc.to_dict().get("originalId")
               for doc in db.collection("sources").stream()
               if doc.to_dict().get("originalId") is not None}
    print(f"  {len(sources)} sources loaded")

    # Match each empty label to a source
    updated = 0
    skipped = 0

    for label_id, label_ref, label_data in empty_labels:
        label_name = label_data.get("label", "")
        label_source_id = label_data.get("sourceId")

        # Try exact sourceId match first
        source_id = label_source_id

        # Fall back to name matching if sourceId isn't set or doesn't work
        if source_id is None:
            normalized = normalize(label_name)
            source_id = next(
                (sid for src_name, sid in sources.items()
                 if normalize(src_name) == normalized),
                None,
            )

        if source_id is None:
            print(f"  ⚠️  Could not match label '{label_name}' to a source — skipping")
            skipped += 1
            continue

        # Get the most recent lessons for this source
        lesson_docs = (
            db.collection("lessons")
            .where("sourceId", "==", source_id)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(lessons_per_label)
            .stream()
        )
        lesson_ids = [doc.id for doc in lesson_docs]

        if not lesson_ids:
            print(f"  ⚠️  No lessons found for source {source_id} (label '{label_name}')")
            skipped += 1
            continue

        print(f"  {'[DRY RUN] ' if dry_run else ''}'{label_name}' → {len(lesson_ids)} lessons from source {source_id}")

        if not dry_run:
            label_ref.update({
                "lessonIds": lesson_ids,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            })
        updated += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")


def main():
    parser = argparse.ArgumentParser(description="Populate empty Firestore label documents")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lessons-per-label", type=int, default=DEFAULT_LESSONS_PER_LABEL)
    args = parser.parse_args()
    populate_labels(dry_run=args.dry_run, lessons_per_label=args.lessons_per_label)


if __name__ == "__main__":
    main()
