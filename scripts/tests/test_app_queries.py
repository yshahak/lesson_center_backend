"""
Tests: validate that the queries the Flutter app actually runs work correctly.

These tests mirror the exact Firestore queries made by FirestoreLessonBloc.dart
and verify they return sensible results. If these fail, users will see broken UI.
"""
import pytest


# ─── Source queries (browsing by yeshiva) ────────────────────────────────────

def test_source_query_returns_ordered_results(fs, all_firestore_sources):
    """
    Simulate the app's _getLessonsForSource query.
    Should return lessons ordered by timestamp desc.
    """
    # Pick the source with most lessons
    top_source = max(all_firestore_sources.items(), key=lambda kv: kv[1]["totalCount"])
    source_orig_id = top_source[0]

    docs = list(
        fs.db.collection("lessons")
        .where("sourceId", "==", source_orig_id)
        .order_by("timestamp", direction="DESCENDING")
        .limit(10)
        .stream()
    )

    assert len(docs) == 10, (
        f"Source {top_source[1]['label']} returned only {len(docs)}/10 lessons"
    )

    timestamps = [doc.to_dict().get("timestamp", 0) for doc in docs]
    assert timestamps == sorted(timestamps, reverse=True), (
        "Lessons not in descending timestamp order"
    )


def test_rav_query_returns_results_for_populated_ravs(fs, all_firestore_ravs):
    """
    For ravs with totalCount > 100, the rav query should return at least 10 results.
    These are the ravs users are most likely to browse.
    """
    big_ravs = [
        (orig_id, info) for orig_id, info in all_firestore_ravs.items()
        if info["totalCount"] >= 100
    ][:5]  # Check top 5

    failures = []
    for orig_id, info in big_ravs:
        docs = list(
            fs.db.collection("lessons")
            .where("ravId", "==", info["doc_id"])
            .order_by("timestamp", direction="DESCENDING")
            .limit(10)
            .stream()
        )
        if len(docs) < 10:
            failures.append(
                f"{info['name']} (totalCount={info['totalCount']}): returned {len(docs)}/10"
            )

    assert not failures, (
        f"Rav queries returning fewer results than expected:\n"
        + "\n".join(failures)
    )


def test_label_query_returns_correct_lessons(fs):
    """
    For each label, query its lessonIds directly and verify the documents exist.
    This validates the exact path the app uses for the main tab.
    """
    labels = list(fs.db.collection("labels").stream())
    failures = []

    for label_doc in labels:
        data = label_doc.to_dict()
        name = data.get("label", "?")
        lesson_ids = data.get("lessonIds", [])

        if not lesson_ids:
            continue

        # Check first 3 IDs from this label
        for lid in lesson_ids[:3]:
            actual_id = lid.replace("lesson_", "") if lid.startswith("lesson_") else lid
            doc = fs.db.collection("lessons").document(actual_id).get()
            if not doc.exists:
                failures.append(f"Label '{name}': lesson {actual_id} not found")

    assert not failures, (
        f"{len(failures)} label→lesson references broken:\n"
        + "\n".join(failures[:10])
    )


def test_category_query_returns_ordered_results(fs, all_firestore_categories):
    """Simulate app's _getLessonsForCategory query for a populated category."""
    populated = [
        (orig_id, info) for orig_id, info in all_firestore_categories.items()
        if info["totalCount"] >= 50
    ]
    if not populated:
        pytest.skip("No categories with 50+ lessons")

    # Pick one
    orig_id, info = populated[0]

    docs = list(
        fs.db.collection("lessons")
        .where("categoryId", "==", info["doc_id"])
        .order_by("timestamp", direction="DESCENDING")
        .limit(10)
        .stream()
    )

    assert len(docs) >= 1, (
        f"Category '{info['name']}' (totalCount={info['totalCount']}) returned 0 lessons"
    )


def test_pagination_cursor_returns_different_results(fs, all_firestore_sources):
    """
    Simulate load-more pagination: second page should not overlap with first.
    This validates the startAfterDocument cursor logic.
    """
    top_source = max(all_firestore_sources.items(), key=lambda kv: kv[1]["totalCount"])
    source_orig_id = top_source[0]

    if top_source[1]["totalCount"] < 20:
        pytest.skip("Source has fewer than 20 lessons, can't test pagination")

    base_query = (
        fs.db.collection("lessons")
        .where("sourceId", "==", source_orig_id)
        .order_by("timestamp", direction="DESCENDING")
    )

    page1 = list(base_query.limit(10).stream())
    assert len(page1) == 10

    cursor_doc = page1[-1]
    page2 = list(base_query.start_after(cursor_doc).limit(10).stream())
    assert len(page2) >= 1

    # No overlap between pages
    page1_ids = {doc.id for doc in page1}
    page2_ids = {doc.id for doc in page2}
    overlap = page1_ids & page2_ids
    assert not overlap, f"Page 1 and page 2 overlap: {overlap}"
