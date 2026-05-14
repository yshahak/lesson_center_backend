"""
Tests: do lesson documents in Firestore match PostgreSQL?

Source of truth: PostgreSQL lessons table.
"""
import pytest


# ─── Lesson count ─────────────────────────────────────────────────────────────

def test_firestore_lesson_count_close_to_postgres(pg, fs):
    """Firestore should have at least 95% of the lessons PostgreSQL has."""
    pg_count = pg.scalar('SELECT COUNT(*) FROM lessons')
    fs_count = int(
        fs.db.collection("lessons").count().get()[0][0].value
    )
    ratio = fs_count / pg_count
    assert ratio >= 0.95, (
        f"Firestore has {fs_count:,} lessons but PostgreSQL has {pg_count:,} "
        f"({ratio:.1%} synced). More than 5% missing."
    )


# ─── Per-lesson document existence ────────────────────────────────────────────

def test_sampled_pg_lessons_exist_in_firestore(pg, fs):
    """
    Sample 200 random lessons from PostgreSQL and verify each exists in Firestore.
    Uses the lesson's bigint `id` as the Firestore document ID.
    """
    rows = pg.query(
        "SELECT id FROM lessons ORDER BY RANDOM() LIMIT 200"
    )
    missing = []
    for row in rows:
        doc = fs.get_lesson(row["id"])
        if not doc.exists:
            missing.append(row["id"])

    assert not missing, (
        f"{len(missing)}/200 sampled lessons don't exist in Firestore: "
        f"{missing[:10]}{'...' if len(missing) > 10 else ''}"
    )


def test_most_recent_pg_lessons_exist_in_firestore(pg, fs):
    """The 50 most recently added PostgreSQL lessons should all be in Firestore."""
    rows = pg.query(
        'SELECT id FROM lessons ORDER BY "insertedat" DESC LIMIT 50'
    )
    missing = []
    for row in rows:
        doc = fs.get_lesson(row["id"])
        if not doc.exists:
            missing.append(row["id"])

    assert not missing, (
        f"{len(missing)}/50 most recent lessons are missing from Firestore — "
        f"migration is behind. Missing IDs: {missing}"
    )


# ─── Specific regression: rav 4014 ───────────────────────────────────────────

def test_rav_4014_lessons_exist_and_have_correct_ravid(pg, fs, all_firestore_ravs):
    """
    Rav 4014 (הראשל\"צ הרב שלמה עמר) showed 16 in totalCount but 0 queryable.
    For each of its lessons: verify (1) it exists in Firestore, (2) ravId is correct.
    """
    rav_info = all_firestore_ravs.get(4014)
    assert rav_info is not None, "Rav originalId=4014 not found in Firestore ravs collection"

    rav_fs_doc_id = rav_info["doc_id"]

    # Get this rav's PostgreSQL id (bigint hash)
    rav_pg_rows = pg.query(
        'SELECT id FROM ravs WHERE "originalId" = 4014'
    )
    assert rav_pg_rows, "Rav originalId=4014 not found in PostgreSQL"
    rav_pg_id = rav_pg_rows[0]["id"]

    # Get all lessons assigned to this rav in PostgreSQL
    lesson_rows = pg.query(
        f'SELECT id, "originalId" FROM lessons WHERE "ravId" = {rav_pg_id}'
    )

    if not lesson_rows:
        pytest.skip("Rav 4014 has no lessons with ravId in PostgreSQL — data gap at source")

    missing_docs = []
    wrong_rav_id = []

    for row in lesson_rows:
        lesson_fs_id = str(row["id"])
        doc = fs.get_lesson(lesson_fs_id)
        if not doc.exists:
            missing_docs.append(lesson_fs_id)
        else:
            actual_rav_id = doc.to_dict().get("ravId")
            if actual_rav_id != rav_fs_doc_id:
                wrong_rav_id.append({
                    "lessonId": lesson_fs_id,
                    "expected": rav_fs_doc_id,
                    "actual": actual_rav_id,
                })

    assert not missing_docs, (
        f"{len(missing_docs)}/{len(lesson_rows)} lessons for rav 4014 "
        f"don't exist in Firestore at all: {missing_docs}"
    )
    assert not wrong_rav_id, (
        f"{len(wrong_rav_id)}/{len(lesson_rows)} lessons for rav 4014 "
        f"have wrong ravId in Firestore: {wrong_rav_id[:3]}"
    )
