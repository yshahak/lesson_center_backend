#!/usr/bin/env python3
"""
Remove duplicate label documents from the Firestore labels collection.

Multiple migration runs created many label documents with the same label name
but empty lessonIds arrays. This script keeps only the document with the most
lesson IDs for each label name, and deletes all the empty duplicates.

Usage:
    python scripts/cleanup_duplicate_labels.py
    python scripts/cleanup_duplicate_labels.py --dry-run   # Preview only
"""

import argparse
from collections import defaultdict

import firebase_admin
from firebase_admin import firestore

PROJECT_ID = "tora-or"


def init_firebase():
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def cleanup_labels(dry_run=False):
    init_firebase()
    db = firestore.client()

    print("Loading all label documents from Firestore...")
    all_docs = list(db.collection("labels").stream())
    print(f"Found {len(all_docs)} total label documents")

    # Group documents by label name
    by_label = defaultdict(list)
    for doc in all_docs:
        data = doc.to_dict()
        name = data.get("label", "")
        count = len(data.get("lessonIds", []))
        by_label[name].append({"ref": doc.reference, "id": doc.id, "count": count, "data": data})

    duplicated_labels = {name: docs for name, docs in by_label.items() if len(docs) > 1}
    print(f"Labels with duplicates: {len(duplicated_labels)}")
    print(f"Labels without duplicates: {len(by_label) - len(duplicated_labels)}")

    docs_to_delete = []
    docs_to_keep = []

    for name, docs in duplicated_labels.items():
        # Keep the document with the most lesson IDs
        docs_sorted = sorted(docs, key=lambda d: d["count"], reverse=True)
        keep = docs_sorted[0]
        delete = docs_sorted[1:]

        docs_to_keep.append(keep)
        docs_to_delete.extend(delete)

        if dry_run:
            print(
                f"\n  Label: \"{name}\"\n"
                f"    Keep:   {keep['id']} ({keep['count']} lesson IDs)\n"
                + "".join(
                    f"    Delete: {d['id']} ({d['count']} lesson IDs)\n"
                    for d in delete
                )
            )

    print(f"\nDocuments to keep:   {len(docs_to_keep)}")
    print(f"Documents to delete: {len(docs_to_delete)}")

    if not docs_to_delete:
        print("Nothing to delete — labels collection is already clean.")
        return

    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return

    # Delete in batches
    batch = db.batch()
    batch_count = 0
    deleted = 0

    for doc_info in docs_to_delete:
        batch.delete(doc_info["ref"])
        batch_count += 1
        deleted += 1

        if batch_count >= 400:
            batch.commit()
            print(f"  Deleted {deleted} documents so far...")
            batch = db.batch()
            batch_count = 0

    if batch_count > 0:
        batch.commit()

    print(f"\nDone. Deleted {deleted} duplicate label documents.")
    print(f"Remaining: {len(by_label)} unique labels (one document each)")


def main():
    parser = argparse.ArgumentParser(description="Remove duplicate Firestore label documents")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    args = parser.parse_args()
    cleanup_labels(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
