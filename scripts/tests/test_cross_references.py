"""
Tests: cross-reference consistency between lesson documents and their
referenced entities (ravs, categories, series, sources).

A lesson's ravId should point to a rav that:
  1. Actually exists as a Firestore document
  2. Belongs to the same source as the lesson

These catch subtle bugs where references point to real but wrong documents.
"""
import pytest
import random


@pytest.fixture(scope="module")
def firestore_rav_docs(fs):
    """Map of Firestore rav doc ID → {originalId, sourceId} for all ravs."""
    result = {}
    for doc in fs.db.collection("ravs").stream():
        data = doc.to_dict()
        result[doc.id] = {
            "originalId": data.get("originalId"),
            "sourceId": data.get("sourceId"),
        }
    return result


@pytest.fixture(scope="module")
def firestore_category_docs(fs):
    result = {}
    for doc in fs.db.collection("categories").stream():
        data = doc.to_dict()
        result[doc.id] = {
            "originalId": data.get("originalId"),
            "sourceId": data.get("sourceId"),
        }
    return result


@pytest.fixture(scope="module")
def firestore_series_docs(fs):
    result = {}
    for doc in fs.db.collection("series").stream():
        data = doc.to_dict()
        result[doc.id] = {
            "originalId": data.get("originalId"),
            "sourceId": data.get("sourceId"),
        }
    return result


# ─── ravId points to an existing rav ─────────────────────────────────────────

def test_rav_id_in_lessons_points_to_existing_rav(fs, firestore_rav_docs):
    """
    Sample 200 lessons with ravId set.
    Each ravId should point to an actual rav document.
    """
    docs = list(
        fs.db.collection("lessons")
        .where("ravId", "!=", None)
        .limit(200)
        .stream()
    )
    if not docs:
        pytest.skip("No lessons with ravId in Firestore")

    dangling = [
        {"lesson": doc.id, "ravId": doc.to_dict().get("ravId")}
        for doc in docs
        if doc.to_dict().get("ravId") not in firestore_rav_docs
    ]
    assert not dangling, (
        f"{len(dangling)}/200 lessons have ravId pointing to non-existent rav: "
        f"{dangling[:5]}"
    )


def test_rav_source_matches_lesson_source(fs, firestore_rav_docs):
    """
    A lesson's sourceId should match the sourceId of its rav.
    Mismatches mean a lesson is attributed to a rav from a different yeshiva.
    """
    docs = list(
        fs.db.collection("lessons")
        .where("ravId", "!=", None)
        .limit(200)
        .stream()
    )
    if not docs:
        pytest.skip("No lessons with ravId in Firestore")

    mismatches = []
    for doc in docs:
        data = doc.to_dict()
        rav_id = data.get("ravId")
        lesson_source = data.get("sourceId")
        rav_info = firestore_rav_docs.get(rav_id, {})
        rav_source = rav_info.get("sourceId")

        if rav_source and lesson_source and rav_source != lesson_source:
            mismatches.append({
                "lesson": doc.id,
                "lessonSource": lesson_source,
                "ravSource": rav_source,
                "ravId": rav_id,
            })

    assert not mismatches, (
        f"{len(mismatches)}/200 lessons have ravId from a different source:\n"
        + "\n".join(
            f"  lesson={m['lesson']} lessonSource={m['lessonSource']} "
            f"ravSource={m['ravSource']}"
            for m in mismatches[:5]
        )
    )


# ─── categoryId points to an existing category ───────────────────────────────

def test_category_id_in_lessons_points_to_existing_category(fs, firestore_category_docs):
    """
    Sample 200 lessons with categoryId set.
    Each categoryId should point to an actual category document.
    """
    docs = list(
        fs.db.collection("lessons")
        .where("categoryId", "!=", None)
        .limit(200)
        .stream()
    )
    if not docs:
        pytest.skip("No lessons with categoryId in Firestore")

    dangling = [
        {"lesson": doc.id, "categoryId": doc.to_dict().get("categoryId")}
        for doc in docs
        if doc.to_dict().get("categoryId") not in firestore_category_docs
    ]
    assert not dangling, (
        f"{len(dangling)}/200 lessons have categoryId pointing to non-existent category: "
        f"{dangling[:5]}"
    )


def test_category_source_matches_lesson_source(fs, firestore_category_docs):
    """A lesson's category should belong to the same source as the lesson."""
    docs = list(
        fs.db.collection("lessons")
        .where("categoryId", "!=", None)
        .limit(200)
        .stream()
    )
    if not docs:
        pytest.skip("No lessons with categoryId in Firestore")

    mismatches = []
    for doc in docs:
        data = doc.to_dict()
        cat_id = data.get("categoryId")
        lesson_source = data.get("sourceId")
        cat_info = firestore_category_docs.get(cat_id, {})
        cat_source = cat_info.get("sourceId")

        if cat_source and lesson_source and cat_source != lesson_source:
            mismatches.append({
                "lesson": doc.id,
                "lessonSource": lesson_source,
                "catSource": cat_source,
            })

    assert not mismatches, (
        f"{len(mismatches)}/200 lessons have category from a different source: "
        f"{mismatches[:5]}"
    )


# ─── seriesId coverage ────────────────────────────────────────────────────────

def test_series_id_set_correctly_in_firestore(pg, fs, all_firestore_series):
    """
    Sample 100 lessons that have seriesId in PostgreSQL.
    Firestore should have seriesId set and pointing to the correct document.
    """
    rows = pg.query(
        """
        SELECT l.id AS lesson_id, s."originalId" AS series_orig_id
        FROM lessons l
        JOIN series s ON l."seriesId" = s.id
        WHERE l."seriesId" IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 100
        """
    )
    if not rows:
        pytest.skip("No lessons with seriesId in PostgreSQL")

    missing_doc = []
    series_id_null = []
    wrong_series = []

    for row in rows:
        lesson_id = str(row["lesson_id"])
        expected_orig = int(row["series_orig_id"])
        expected_fs_id = all_firestore_series.get(expected_orig, {}).get("doc_id")

        if expected_fs_id is None:
            continue

        doc = fs.get_lesson(lesson_id)
        if not doc.exists:
            missing_doc.append(lesson_id)
            continue

        actual = doc.to_dict().get("seriesId")
        if actual is None:
            series_id_null.append(lesson_id)
        elif actual != expected_fs_id:
            wrong_series.append(lesson_id)

    assert not missing_doc, f"{len(missing_doc)} sampled lessons missing from Firestore"
    assert len(series_id_null) < 5, (
        f"{len(series_id_null)}/100 lessons have seriesId in PG but null in Firestore"
    )
    assert not wrong_series, f"{len(wrong_series)} lessons have wrong seriesId"


def test_series_id_in_lessons_points_to_existing_series(fs, firestore_series_docs):
    """All seriesId values in lesson documents point to existing series docs."""
    docs = list(
        fs.db.collection("lessons")
        .where("seriesId", "!=", None)
        .limit(200)
        .stream()
    )
    if not docs:
        pytest.skip("No lessons with seriesId in Firestore")

    dangling = [
        doc.id for doc in docs
        if doc.to_dict().get("seriesId") not in firestore_series_docs
    ]
    assert not dangling, (
        f"{len(dangling)}/200 lessons have seriesId pointing to non-existent series"
    )
