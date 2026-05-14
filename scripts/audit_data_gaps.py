#!/usr/bin/env python3
"""
Audit the gap between totalCount metadata and actual queryable lessons in Firestore.

For every rav, category, and series, this script counts how many lessons
actually have that entity's Firestore doc ID set in their reference field,
and compares it to the totalCount stored in the entity document.

Uses Firestore aggregation count() queries — cheap (no document reads).

Usage:
    python scripts/audit_data_gaps.py
    python scripts/audit_data_gaps.py --collection ravs       # just ravs
    python scripts/audit_data_gaps.py --min-gap 100           # only show gaps >= 100
    python scripts/audit_data_gaps.py --output gaps_report.csv

Cost: ~$0.06 per 1000 aggregation queries.
      533 ravs + 677 categories + 2285 series ≈ 3500 queries ≈ $0.21 total.
"""

import argparse
import csv
import io
import sys
import time

import firebase_admin
from firebase_admin import firestore

PROJECT_ID = "tora-or"
DELAY_BETWEEN_BATCHES = 0.1  # seconds — light rate limiting


def init_firebase():
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def count_lessons(db, field, doc_id):
    """Return actual count of lessons where field == doc_id using aggregation.

    The SDK (google-cloud-firestore >= 2.x) returns a QueryResultsList where
    result[0] is a list of AggregationResult objects and result[0][0].value
    holds the count (as a float).  An empty result set still returns
    [[<Aggregation value=0.0 ...>]], so IndexError should not occur in
    practice, but we guard defensively and return 0 if the structure is
    unexpected.
    """
    try:
        result = (
            db.collection("lessons")
            .where(field, "==", doc_id)
            .count()
            .get()
        )
        if result and result[0]:
            return result[0][0].value
        return 0
    except Exception as e:
        return f"ERROR: {e}"


def audit_collection(db, collection_name, lesson_field, label_field, min_gap=0):
    print(f"\nAuditing '{collection_name}' (field: {lesson_field})...")
    docs = list(db.collection(collection_name).stream())
    print(f"  {len(docs)} documents loaded")

    rows = []
    for i, doc in enumerate(docs):
        data = doc.to_dict()
        orig_id = data.get("originalId", "?")
        name = data.get(label_field, "?")
        total_count = data.get("totalCount", 0) or 0

        actual = count_lessons(db, lesson_field, doc.id)

        if isinstance(actual, str):  # error
            gap = "ERROR"
            gap_pct = "ERROR"
        else:
            gap = total_count - actual
            gap_pct = f"{(gap / total_count * 100):.0f}%" if total_count > 0 else "N/A"

        rows.append({
            "collection": collection_name,
            "originalId": orig_id,
            "name": name,
            "totalCount": total_count,
            "actualCount": actual,
            "gap": gap,
            "gap_pct": gap_pct,
        })

        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{len(docs)}")
            time.sleep(DELAY_BETWEEN_BATCHES)

    # Filter and sort
    significant = [
        r for r in rows
        if isinstance(r["gap"], int) and r["gap"] >= min_gap and r["totalCount"] > 0
    ]
    significant.sort(key=lambda r: r["gap"], reverse=True)

    zero_actual = [r for r in rows if r.get("actualCount") == 0 and r["totalCount"] > 0]
    partial = [r for r in rows if isinstance(r.get("actualCount"), int)
               and 0 < r["actualCount"] < r["totalCount"]]
    ok = [r for r in rows if r.get("actualCount") == r["totalCount"]]

    print(f"\n  Results for '{collection_name}':")
    print(f"    Total docs:          {len(rows)}")
    print(f"    Fully missing (0):   {len(zero_actual)}")
    print(f"    Partial data:        {len(partial)}")
    print(f"    Fully synced:        {len(ok)}")

    if significant:
        print(f"\n  Top 10 largest gaps:")
        for r in significant[:10]:
            print(f"    [{r['originalId']}] {r['name'][:40]:<40} "
                  f"meta={r['totalCount']} actual={r['actualCount']} "
                  f"gap={r['gap']} ({r['gap_pct']})")

    return rows


def main():
    parser = argparse.ArgumentParser(description="Audit Firestore data gaps")
    parser.add_argument(
        "--collection",
        choices=["ravs", "categories", "series", "all"],
        default="all",
    )
    parser.add_argument("--min-gap", type=int, default=0,
                        help="Only report gaps >= this value")
    parser.add_argument("--output", default=None,
                        help="Write full CSV report to this file")
    args = parser.parse_args()

    init_firebase()
    db = firestore.client()

    COLLECTIONS = {
        "ravs":       ("ravId",      "rav"),
        "categories": ("categoryId", "category"),
        "series":     ("seriesId",   "serie"),
    }

    to_audit = (
        {k: v for k, v in COLLECTIONS.items() if k == args.collection}
        if args.collection != "all"
        else COLLECTIONS
    )

    all_rows = []
    for col, (field, label) in to_audit.items():
        rows = audit_collection(db, col, field, label, min_gap=args.min_gap)
        all_rows.extend(rows)

    # Summary
    if args.collection == "all":
        total_meta = sum(r["totalCount"] for r in all_rows if isinstance(r["totalCount"], int))
        total_actual = sum(r["actualCount"] for r in all_rows if isinstance(r.get("actualCount"), int))
        print(f"\n{'='*60}")
        print(f"OVERALL SUMMARY")
        print(f"  Total lessons in metadata: {total_meta:,}")
        print(f"  Total lessons queryable:   {total_actual:,}")
        print(f"  Overall gap:               {total_meta - total_actual:,} "
              f"({(total_meta - total_actual) / total_meta * 100:.1f}% missing)"
              if total_meta > 0 else "")

    # Write CSV
    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "collection", "originalId", "name",
                "totalCount", "actualCount", "gap", "gap_pct"
            ])
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nFull report written to: {args.output}")


if __name__ == "__main__":
    main()
