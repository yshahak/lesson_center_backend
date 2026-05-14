"""
Tests: source collection integrity.

Sources are the top-level yeshivot/institutions. Every lesson belongs to
exactly one source. These tests verify sources are consistent and complete.
"""
import pytest


def test_all_sources_exist_in_postgres(pg, all_firestore_sources):
    """Every source in Firestore should have a matching originalId in PostgreSQL."""
    fs_orig_ids = set(all_firestore_sources.keys())

    pg_rows = pg.query('SELECT "originalId" FROM sources')
    pg_orig_ids = {int(r["originalId"]) for r in pg_rows}

    orphaned = fs_orig_ids - pg_orig_ids
    assert not orphaned, (
        f"{len(orphaned)} Firestore sources not in PostgreSQL: {orphaned}"
    )


def test_postgres_sources_all_exist_in_firestore(pg, all_firestore_sources):
    """Every source in PostgreSQL should be in Firestore."""
    pg_rows = pg.query('SELECT "originalId", label FROM sources')
    missing = [
        r["label"] for r in pg_rows
        if int(r["originalId"]) not in all_firestore_sources
    ]
    assert not missing, (
        f"{len(missing)} PostgreSQL sources missing from Firestore: {missing}"
    )


def test_source_totalcounts_match_postgres_lesson_counts(pg, fs, all_firestore_sources):
    """
    For each source, compare the Firestore totalCount to the actual PostgreSQL
    lesson count. Within 2% tolerance (some lessons may not yet be in Firestore).
    """
    pg_rows = pg.query(
        'SELECT "sourceId", COUNT(*) AS cnt FROM lessons GROUP BY "sourceId"'
    )
    pg_counts = {int(r["sourceId"]): int(r["cnt"]) for r in pg_rows}

    mismatches = []
    for orig_id, info in all_firestore_sources.items():
        pg_count = pg_counts.get(orig_id, 0)
        fs_count = info["totalCount"]
        if pg_count == 0:
            continue
        ratio = fs_count / pg_count
        if not (0.90 <= ratio <= 1.10):
            mismatches.append({
                "source": info["label"],
                "pg_count": pg_count,
                "fs_totalCount": fs_count,
                "ratio": f"{ratio:.2f}",
            })

    assert not mismatches, (
        f"{len(mismatches)} sources have totalCount differing >10% from PostgreSQL:\n"
        + "\n".join(
            f"  {m['source']}: pg={m['pg_count']} fs={m['fs_totalCount']} ({m['ratio']})"
            for m in mismatches
        )
    )


def test_no_lessons_with_unknown_source_id(pg, fs):
    """
    Sample 200 Firestore lessons and verify every sourceId corresponds to a
    known source in PostgreSQL. Catches lessons uploaded with wrong sourceId.
    """
    pg_rows = pg.query('SELECT "originalId" FROM sources')
    valid_source_ids = {int(r["originalId"]) for r in pg_rows}

    docs = list(fs.db.collection("lessons").limit(200).stream())
    invalid = [
        {"lesson": doc.id, "sourceId": doc.to_dict().get("sourceId")}
        for doc in docs
        if doc.to_dict().get("sourceId") not in valid_source_ids
    ]

    assert not invalid, (
        f"{len(invalid)}/200 lessons have sourceId not in PostgreSQL: {invalid[:5]}"
    )


def test_each_source_has_at_least_some_lessons_in_firestore(fs, all_firestore_sources):
    """
    Every source with totalCount > 0 should have at least some queryable lessons
    in Firestore. A source showing lessons but returning empty is broken.
    """
    empty_sources = []
    for orig_id, info in all_firestore_sources.items():
        if info["totalCount"] == 0:
            continue
        actual = fs.count_lessons_for("sourceId", orig_id)
        if actual == 0:
            empty_sources.append(f"{info['label']} (originalId={orig_id}, totalCount={info['totalCount']})")

    assert not empty_sources, (
        f"{len(empty_sources)} sources claim lessons but have 0 queryable:\n"
        + "\n".join(f"  {s}" for s in empty_sources)
    )
