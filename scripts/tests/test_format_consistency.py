"""
Tests: Firestore document format consistency.

All lesson documents should use the new format:
- Document ID = PostgreSQL bigint `lessons.id` (18-digit number)
- ravId/categoryId/seriesId = Firestore string doc IDs, NOT PostgreSQL bigint FKs

Old-format docs (doc ID = small integer originalId) are stale duplicates
that are invisible to rav/category/series queries.

Run cleanup_old_format_lessons.py first if these fail.
"""
import pytest


OLD_FORMAT_THRESHOLD = 10 ** 15


@pytest.fixture(scope="module")
def lesson_sample_200(fs):
    """200 lessons sampled via source query (avoids label-specific bias)."""
    docs = list(fs.db.collection("lessons").limit(200).stream())
    return [(doc.id, doc.to_dict()) for doc in docs]


# ─── Format consistency ───────────────────────────────────────────────────────

def test_no_old_format_lesson_documents(fs):
    """
    No lesson document should have a small-integer doc ID (old format).
    All docs should use the bigint lessons.id as their Firestore doc ID.
    If this fails: run scripts/cleanup_old_format_lessons.py
    """
    old_format = []
    for doc in fs.db.collection("lessons").limit(5000).stream():
        try:
            if int(doc.id) < OLD_FORMAT_THRESHOLD:
                old_format.append(doc.id)
        except (ValueError, TypeError):
            pass

    assert not old_format, (
        f"{len(old_format)} old-format lesson docs found. "
        f"Run: python scripts/cleanup_old_format_lessons.py\n"
        f"Sample IDs: {old_format[:10]}"
    )


def test_reference_fields_are_strings_not_integers(lesson_sample_200):
    """
    ravId, categoryId, seriesId should be strings (Firestore doc IDs)
    when set — never integers (which would be PostgreSQL bigint FKs).
    Integer reference fields are from old-format docs and break app queries.
    """
    int_refs = []
    for doc_id, data in lesson_sample_200:
        for field in ("ravId", "categoryId", "seriesId"):
            val = data.get(field)
            if val is not None and isinstance(val, int):
                int_refs.append({
                    "lesson": doc_id,
                    "field": field,
                    "value": val,
                })

    assert not int_refs, (
        f"{len(int_refs)} lessons have integer reference fields (PostgreSQL bigint FKs). "
        f"These are old-format docs. Run cleanup_old_format_lessons.py.\n"
        f"Sample: {int_refs[:5]}"
    )


def test_all_lesson_doc_ids_are_large_integers(lesson_sample_200):
    """
    All lesson document IDs should be large integers (>= 10^15).
    Small-integer doc IDs indicate old-format migration artifacts.
    """
    small_ids = [
        doc_id for doc_id, _ in lesson_sample_200
        if int(doc_id) < OLD_FORMAT_THRESHOLD
    ]
    assert not small_ids, (
        f"{len(small_ids)}/200 sampled lessons have small-integer doc IDs: {small_ids[:10]}"
    )


# ─── Source totalCount accuracy ───────────────────────────────────────────────

def test_source_totalcounts_match_queryable_with_tolerance(fs):
    """
    Source totalCounts should match actual lesson counts within 5%.
    (Sources update less frequently than ravs/categories/series.)
    """
    mismatches = []
    for doc in fs.db.collection("sources").stream():
        data = doc.to_dict()
        orig_id = data.get("originalId")
        total_count = data.get("totalCount", 0) or 0
        if total_count == 0:
            continue

        actual = fs.count_lessons_for("sourceId", orig_id)
        diff = abs(total_count - actual)
        if diff > max(total_count * 0.05, 5):  # 5% or 5 lessons tolerance
            mismatches.append({
                "source": data.get("label", "?"),
                "totalCount": total_count,
                "actual": actual,
                "diff": diff,
            })

    mismatches.sort(key=lambda m: m["diff"], reverse=True)
    assert not mismatches, (
        f"{len(mismatches)} sources have totalCount off by >5%:\n"
        + "\n".join(
            f"  {m['source']}: stored={m['totalCount']} actual={m['actual']}"
            for m in mismatches[:10]
        )
    )


# ─── Reference field type consistency across ALL lessons ─────────────────────

def test_rav_id_field_type_consistency(fs):
    """
    Across a large sample, no lesson should have ravId as an integer.
    """
    # Query lessons that have a ravId set
    docs = list(
        fs.db.collection("lessons")
        .where("ravId", "!=", None)
        .limit(500)
        .stream()
    )

    int_rav_ids = [
        {"lesson": doc.id, "ravId": doc.to_dict().get("ravId")}
        for doc in docs
        if isinstance(doc.to_dict().get("ravId"), int)
    ]

    assert not int_rav_ids, (
        f"{len(int_rav_ids)}/500 lessons have integer ravId (should be string): "
        f"{int_rav_ids[:5]}"
    )


def test_category_id_field_type_consistency(fs):
    """All categoryId values should be strings, not integers."""
    docs = list(
        fs.db.collection("lessons")
        .where("categoryId", "!=", None)
        .limit(500)
        .stream()
    )

    int_cat_ids = [
        doc.id for doc in docs
        if isinstance(doc.to_dict().get("categoryId"), int)
    ]

    assert not int_cat_ids, (
        f"{len(int_cat_ids)}/500 lessons have integer categoryId: {int_cat_ids[:5]}"
    )
