#!/usr/bin/env python3
"""
Remove duplicate documents from any Firestore collection.

Duplicates arise when the same logical entity (same originalId) has multiple
Firestore documents — usually from re-running migration scripts without clearing
old data first.

Strategy: group by originalId, keep the document with the highest totalCount
(most recent/accurate), delete all others.

Usage:
    python scripts/cleanup_duplicate_docs.py --collection ravs
    python scripts/cleanup_duplicate_docs.py --collection sources
    python scripts/cleanup_duplicate_docs.py --collection categories
    python scripts/cleanup_duplicate_docs.py --collection series
    python scripts/cleanup_duplicate_docs.py --collection ravs --dry-run
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


def cleanup_collection(collection_name, dry_run=False):
    init_firebase()
    db = firestore.client()

    print(f"Loading all documents from '{collection_name}'...")
    all_docs = list(db.collection(collection_name).stream())
    print(f"Found {len(all_docs)} total documents")

    # Group by originalId
    by_original_id = defaultdict(list)
    for doc in all_docs:
        data = doc.to_dict()
        orig_id = data.get("originalId")
        if orig_id is None:
            print(f"  Warning: doc {doc.id} has no originalId — skipping")
            continue
        count = data.get("totalCount", 0) or 0
        by_original_id[int(orig_id)].append({
            "ref": doc.reference,
            "id": doc.id,
            "totalCount": count,
            "data": data,
        })

    duplicated = {k: v for k, v in by_original_id.items() if len(v) > 1}
    unique_count = len(by_original_id) - len(duplicated)

    print(f"Unique originalIds: {len(by_original_id)}")
    print(f"  With duplicates:  {len(duplicated)}")
    print(f"  Already unique:   {unique_count}")

    docs_to_delete = []

    for orig_id, docs in duplicated.items():
        # Keep the doc with the highest totalCount
        docs_sorted = sorted(docs, key=lambda d: d["totalCount"], reverse=True)
        keep = docs_sorted[0]
        delete = docs_sorted[1:]
        docs_to_delete.extend(delete)

        if dry_run:
            label = keep["data"].get(
                _label_field(collection_name), f"originalId={orig_id}"
            )
            print(
                f"\n  originalId={orig_id} ({label})\n"
                f"    Keep:   {keep['id']} (totalCount={keep['totalCount']})\n"
                + "".join(
                    f"    Delete: {d['id']} (totalCount={d['totalCount']})\n"
                    for d in delete
                )
            )

    print(f"\nDocuments to keep:   {len(by_original_id)}")
    print(f"Documents to delete: {len(docs_to_delete)}")

    if not docs_to_delete:
        print("Nothing to delete — collection is already clean.")
        return

    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return

    batch = db.batch()
    batch_count = 0
    deleted = 0

    for doc_info in docs_to_delete:
        batch.delete(doc_info["ref"])
        batch_count += 1
        deleted += 1
        if batch_count >= 400:
            batch.commit()
            print(f"  Deleted {deleted} so far...")
            batch = db.batch()
            batch_count = 0

    if batch_count > 0:
        batch.commit()

    print(f"\nDone. Deleted {deleted} duplicate documents from '{collection_name}'.")
    print(f"Remaining: {len(by_original_id)} unique documents.")


def _label_field(collection_name):
    return {
        "ravs": "rav",
        "sources": "label",
        "categories": "category",
        "series": "serie",
    }.get(collection_name, "label")


def main():
    parser = argparse.ArgumentParser(
        description="Remove duplicate Firestore documents grouped by originalId"
    )
    parser.add_argument(
        "--collection",
        required=True,
        choices=["ravs", "sources", "categories", "series"],
        help="Collection to deduplicate",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    args = parser.parse_args()
    cleanup_collection(args.collection, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
