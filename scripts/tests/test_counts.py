"""
Tests: are totalCount values in Firestore accurate?

totalCount in each rav/category/series document should match the actual
number of lessons queryable in Firestore for that entity.
"""
import pytest


def test_rav_totalcounts_match_queryable(fs, all_firestore_ravs):
    """
    For every rav with totalCount > 0, the actual queryable lesson count
    should equal totalCount. Tolerance of ±5 to allow for in-flight scraper
    updates between the last audit run and now.
    """
    mismatches = []
    for orig_id, info in all_firestore_ravs.items():
        if info["totalCount"] == 0:
            continue
        actual = fs.count_lessons_for("ravId", info["doc_id"])
        if abs(actual - info["totalCount"]) > 5:
            mismatches.append({
                "rav": info["name"],
                "originalId": orig_id,
                "totalCount": info["totalCount"],
                "actual": actual,
                "diff": info["totalCount"] - actual,
            })

    # Sort by largest discrepancy
    mismatches.sort(key=lambda m: abs(m["diff"]), reverse=True)

    assert not mismatches, (
        f"{len(mismatches)} ravs have totalCount != actual queryable count:\n"
        + "\n".join(
            f"  [{m['originalId']}] {m['rav']}: "
            f"totalCount={m['totalCount']} actual={m['actual']} diff={m['diff']}"
            for m in mismatches[:20]
        )
    )


def test_category_totalcounts_match_queryable(fs, all_firestore_categories):
    """Same check for categories."""
    mismatches = []
    for orig_id, info in all_firestore_categories.items():
        if info["totalCount"] == 0:
            continue
        actual = fs.count_lessons_for("categoryId", info["doc_id"])
        if actual != info["totalCount"]:
            mismatches.append({
                "name": info["name"],
                "originalId": orig_id,
                "totalCount": info["totalCount"],
                "actual": actual,
            })

    mismatches.sort(key=lambda m: abs(m["totalCount"] - m["actual"]), reverse=True)
    assert not mismatches, (
        f"{len(mismatches)} categories have wrong totalCount. "
        f"Top mismatches: {mismatches[:5]}"
    )


def test_no_zero_totalcount_with_queryable_lessons(fs, all_firestore_ravs, all_firestore_categories):
    """
    No rav or category should have totalCount=0 but actually have queryable lessons.
    (That would mean lessons exist but aren't being shown.)
    """
    hidden = []
    for orig_id, info in all_firestore_ravs.items():
        if info["totalCount"] == 0:
            actual = fs.count_lessons_for("ravId", info["doc_id"])
            if actual > 0:
                hidden.append(f"rav [{orig_id}] {info['name']}: {actual} lessons hidden")

    for orig_id, info in all_firestore_categories.items():
        if info["totalCount"] == 0:
            actual = fs.count_lessons_for("categoryId", info["doc_id"])
            if actual > 0:
                hidden.append(f"category [{orig_id}] {info['name']}: {actual} lessons hidden")

    assert not hidden, (
        f"{len(hidden)} entities have totalCount=0 but queryable lessons exist "
        f"(they're invisible to users):\n" + "\n".join(hidden[:10])
    )


def test_postgres_rav_count_matches_firestore_total(pg, fs, all_firestore_ravs):
    """
    The SUM of all rav totalCounts in Firestore should approximately equal
    the count of lessons with ravId in PostgreSQL.
    Tolerance: 5% (accounts for lessons not yet migrated).
    """
    pg_count = pg.scalar(
        'SELECT COUNT(*) FROM lessons WHERE "ravId" IS NOT NULL'
    )
    fs_total = sum(info["totalCount"] for info in all_firestore_ravs.values())

    if pg_count == 0:
        pytest.skip("No lessons with ravId in PostgreSQL")

    ratio = fs_total / pg_count
    assert 0.90 <= ratio <= 1.10, (
        f"Sum of Firestore rav totalCounts ({fs_total:,}) differs from "
        f"PostgreSQL lessons with ravId ({pg_count:,}) by more than 10%. "
        f"Ratio: {ratio:.2f}. The totalCounts may be stale."
    )
