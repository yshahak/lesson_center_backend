"""
Tests: are ravId / categoryId / seriesId set correctly in Firestore lessons?

For every lesson where PostgreSQL has these fields non-null, the corresponding
Firestore document should have the matching Firestore doc ID set.
"""
import pytest
import random


def _sample_pg_lessons_with_rav(pg, n=100):
    return pg.query(
        f"""
        SELECT l.id AS lesson_id, r."originalId" AS rav_orig_id
        FROM lessons l
        JOIN ravs r ON l."ravId" = r.id
        WHERE l."ravId" IS NOT NULL
        ORDER BY RANDOM()
        LIMIT {n}
        """
    )


def _sample_pg_lessons_with_category(pg, n=100):
    return pg.query(
        f"""
        SELECT l.id AS lesson_id, c."originalId" AS cat_orig_id
        FROM lessons l
        JOIN categories c ON l."categoryId" = c.id
        WHERE l."categoryId" IS NOT NULL
        ORDER BY RANDOM()
        LIMIT {n}
        """
    )


# ─── ravId correctness ────────────────────────────────────────────────────────

def test_rav_id_set_correctly_in_firestore(pg, fs, all_firestore_ravs):
    """
    Sample 100 lessons that have ravId in PostgreSQL.
    For each: Firestore doc should exist AND ravId should match.
    """
    rows = _sample_pg_lessons_with_rav(pg)
    if not rows:
        pytest.skip("No lessons with ravId in PostgreSQL")

    missing_doc = []
    wrong_rav = []
    rav_id_null = []

    for row in rows:
        lesson_id = str(row["lesson_id"])
        expected_rav_orig = int(row["rav_orig_id"])
        expected_fs_rav_id = all_firestore_ravs.get(expected_rav_orig, {}).get("doc_id")

        if expected_fs_rav_id is None:
            continue  # rav not in Firestore — separate test catches this

        doc = fs.get_lesson(lesson_id)
        if not doc.exists:
            missing_doc.append(lesson_id)
            continue

        actual_rav_id = doc.to_dict().get("ravId")
        if actual_rav_id is None:
            rav_id_null.append(lesson_id)
        elif actual_rav_id != expected_fs_rav_id:
            wrong_rav.append({
                "lesson": lesson_id,
                "expected": expected_fs_rav_id,
                "actual": actual_rav_id,
            })

    assert not missing_doc, (
        f"{len(missing_doc)}/100 sampled lessons with ravId don't exist in Firestore"
    )
    assert not rav_id_null, (
        f"{len(rav_id_null)}/100 lessons have ravId in PostgreSQL but null in Firestore — "
        f"ravId fix incomplete. Sample: {rav_id_null[:5]}"
    )
    assert not wrong_rav, (
        f"{len(wrong_rav)}/100 lessons have wrong ravId in Firestore. "
        f"Sample: {wrong_rav[:3]}"
    )


# ─── categoryId correctness ───────────────────────────────────────────────────

def test_category_id_set_correctly_in_firestore(pg, fs, all_firestore_categories):
    """
    Sample 100 lessons with categoryId in PostgreSQL.
    Firestore should have categoryId set and matching.
    """
    rows = _sample_pg_lessons_with_category(pg)
    if not rows:
        pytest.skip("No lessons with categoryId in PostgreSQL")

    missing_doc = []
    cat_id_null = []
    wrong_cat = []

    for row in rows:
        lesson_id = str(row["lesson_id"])
        expected_cat_orig = int(row["cat_orig_id"])
        expected_fs_cat_id = all_firestore_categories.get(expected_cat_orig, {}).get("doc_id")

        if expected_fs_cat_id is None:
            continue

        doc = fs.get_lesson(lesson_id)
        if not doc.exists:
            missing_doc.append(lesson_id)
            continue

        actual_cat_id = doc.to_dict().get("categoryId")
        if actual_cat_id is None:
            cat_id_null.append(lesson_id)
        elif actual_cat_id != expected_fs_cat_id:
            wrong_cat.append(lesson_id)

    assert not missing_doc, f"{len(missing_doc)} lessons with category missing from Firestore"
    assert len(cat_id_null) < 5, (
        f"{len(cat_id_null)}/100 lessons have categoryId in PG but null in Firestore. "
        f"Sample: {cat_id_null[:5]}"
    )
    assert not wrong_cat, f"{len(wrong_cat)} lessons have wrong categoryId in Firestore"


# ─── Every rav in Firestore has a matching PostgreSQL rav ────────────────────

def test_all_firestore_ravs_exist_in_postgres(pg, all_firestore_ravs):
    """Every rav in Firestore should exist in PostgreSQL."""
    fs_original_ids = set(all_firestore_ravs.keys())

    pg_rows = pg.query('SELECT "originalId" FROM ravs')
    pg_original_ids = {int(r["originalId"]) for r in pg_rows}

    orphaned = fs_original_ids - pg_original_ids
    assert not orphaned, (
        f"{len(orphaned)} ravs in Firestore don't exist in PostgreSQL "
        f"(orphaned): {list(orphaned)[:10]}"
    )


# ─── Ravs with queryable lessons are not being counted wrong ─────────────────

def test_ravs_with_high_totalcount_have_queryable_lessons(pg, fs, all_firestore_ravs):
    """
    Pick the 10 ravs with the highest totalCount in Firestore.
    Each should have at least totalCount * 0.5 queryable lessons
    (accounts for data gap but ensures the top ravs actually work).
    """
    top_ravs = sorted(
        all_firestore_ravs.items(),
        key=lambda kv: kv[1]["totalCount"],
        reverse=True,
    )[:10]

    failures = []
    for orig_id, info in top_ravs:
        if info["totalCount"] == 0:
            continue
        actual = fs.count_lessons_for("ravId", info["doc_id"])
        ratio = actual / info["totalCount"]
        if ratio < 0.5:
            failures.append({
                "rav": info["name"],
                "originalId": orig_id,
                "totalCount": info["totalCount"],
                "actual": actual,
                "ratio": f"{ratio:.1%}",
            })

    assert not failures, (
        f"Top ravs by totalCount have <50% queryable lessons:\n"
        + "\n".join(
            f"  {f['rav']}: totalCount={f['totalCount']} actual={f['actual']} ({f['ratio']})"
            for f in failures
        )
    )
