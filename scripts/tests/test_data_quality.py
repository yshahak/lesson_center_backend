"""
Tests: Firestore lesson document data quality.

These tests sample lessons DIRECTLY from Firestore (no PostgreSQL needed)
and validate that each document has sensible, well-formed data.
They catch issues introduced by bad migrations, broken scrapers, or schema changes.
"""
import time
import pytest


# ─── Sampling fixture ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sampled_lessons(fs):
    """500 lessons sampled from Firestore for quality checks."""
    docs = (
        fs.db.collection("lessons")
        .order_by("timestamp", direction="DESCENDING")
        .limit(500)
        .stream()
    )
    return [doc.to_dict() for doc in docs]


# ─── Required fields ──────────────────────────────────────────────────────────

def test_lessons_have_required_fields(sampled_lessons):
    """
    Every lesson must have sourceId and timestamp.
    These are the minimum fields needed to display anything to the user.
    """
    missing_source = [l for l in sampled_lessons if not l.get("sourceId")]
    missing_ts = [l for l in sampled_lessons if l.get("timestamp") is None]

    assert not missing_source, (
        f"{len(missing_source)}/500 lessons are missing sourceId"
    )
    assert not missing_ts, (
        f"{len(missing_ts)}/500 lessons are missing timestamp"
    )


def test_lesson_timestamps_are_reasonable(sampled_lessons):
    """
    Timestamps should be Unix seconds in a reasonable range:
    - After 2000-01-01 (946684800)
    - Not in the distant future (year 2100 = 4102444800)
    """
    MIN_TS = 946684800   # 2000-01-01
    MAX_TS = 4102444800  # 2100-01-01

    bad = [
        {"originalId": l.get("originalId"), "timestamp": l.get("timestamp")}
        for l in sampled_lessons
        if l.get("timestamp") is not None
        and not (MIN_TS <= int(l["timestamp"]) <= MAX_TS)
    ]
    assert not bad, f"{len(bad)} lessons have unreasonable timestamps: {bad[:5]}"


def test_lesson_durations_are_reasonable(sampled_lessons):
    """
    Durations should be between 1 second and 48 hours if set.
    (Some multi-session recordings legitimately exceed 24 hours.)
    Flag anything over 48h as likely a data error (e.g. duration stored in ms).
    """
    MAX_DURATION = 172800  # 48 hours in seconds
    bad = [
        l.get("originalId")
        for l in sampled_lessons
        if l.get("duration") is not None and not (1 <= int(l["duration"]) <= MAX_DURATION)
    ]
    # Allow up to 1% — some scrapers occasionally produce garbage values
    assert len(bad) < len(sampled_lessons) * 0.01, (
        f"{len(bad)}/{len(sampled_lessons)} lessons have duration outside 1s–48h: {bad[:10]}"
    )


def test_lessons_have_at_least_one_media_url(sampled_lessons):
    """
    Every lesson should have a videoUrl OR audioUrl.
    A lesson with neither is useless to the user.
    """
    no_media = [
        l.get("originalId")
        for l in sampled_lessons
        if not l.get("videoUrl") and not l.get("audioUrl")
    ]
    # Allow up to 2% with no media (scrapers sometimes miss URLs)
    pct = len(no_media) / len(sampled_lessons)
    assert pct < 0.02, (
        f"{len(no_media)}/500 ({pct:.1%}) lessons have no videoUrl and no audioUrl. "
        f"Sample: {no_media[:10]}"
    )


def test_no_duplicate_original_ids_in_sample(sampled_lessons):
    """No two lesson documents should share the same originalId."""
    orig_ids = [l.get("originalId") for l in sampled_lessons if l.get("originalId")]
    duplicates = {x for x in orig_ids if orig_ids.count(x) > 1}
    assert not duplicates, (
        f"Duplicate originalId values found in sample: {duplicates}"
    )


# ─── Source integrity ─────────────────────────────────────────────────────────

def test_source_totalcounts_match_queryable(fs):
    """
    For every source in Firestore, totalCount should match the actual
    number of lessons with that sourceId.
    """
    mismatches = []
    for doc in fs.db.collection("sources").stream():
        data = doc.to_dict()
        orig_id = data.get("originalId")
        total_count = data.get("totalCount", 0) or 0
        if total_count == 0:
            continue

        actual = fs.count_lessons_for("sourceId", orig_id)
        if actual != total_count:
            mismatches.append({
                "source": data.get("label", "?"),
                "originalId": orig_id,
                "totalCount": total_count,
                "actual": actual,
                "diff": total_count - actual,
            })

    mismatches.sort(key=lambda m: abs(m["diff"]), reverse=True)
    assert not mismatches, (
        f"{len(mismatches)} sources have wrong totalCount:\n"
        + "\n".join(
            f"  {m['source']}: totalCount={m['totalCount']} actual={m['actual']}"
            for m in mismatches[:10]
        )
    )


def test_all_lesson_source_ids_exist_in_sources_collection(sampled_lessons, fs):
    """Every sourceId in a lesson should point to an existing source document."""
    known_sources = {
        int(doc.to_dict().get("originalId", 0))
        for doc in fs.db.collection("sources").stream()
    }

    orphaned = {
        l.get("sourceId")
        for l in sampled_lessons
        if l.get("sourceId") not in known_sources
    }
    assert not orphaned, (
        f"Lessons reference sourceIds not in Firestore sources: {orphaned}"
    )


# ─── Migration staleness ──────────────────────────────────────────────────────

def test_no_lesson_added_in_last_7_days_is_missing(pg, fs):
    """
    Any lesson added to PostgreSQL in the last 7 days should exist in Firestore.
    This test catches migration staleness early — run it weekly.
    """
    rows = pg.query(
        "SELECT id FROM lessons WHERE insertedat > NOW() - INTERVAL '7 days'"
    )
    if not rows:
        pytest.skip("No lessons added in the last 7 days in PostgreSQL")

    missing = [r["id"] for r in rows if not fs.get_lesson(r["id"]).exists]

    assert not missing, (
        f"{len(missing)}/{len(rows)} lessons added in the last 7 days are missing "
        f"from Firestore. Run sync_lessons_from_postgres.py. "
        f"Missing IDs: {missing[:10]}"
    )
