"""
Unit tests for the bnei_david taxonomy mapping helper functions.

No network calls, no Firestore, no LLM calls — pure logic tests.

Run from the repo root:
    pytest scripts/tests/test_bnei_david_taxonomy_mapping.py -v
"""

import sys
import os

import pytest

# ── Make the scripts package importable ──────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_bnei_david_taxonomy_mapping import build_mapping, match_ravs, match_series


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_WP_RAVS = [
    {"id": 2290, "name": "הרב אוהד תירוש", "count": 10},
    {"id": 2293, "name": "הרב חיים וידאל", "count": 5},
    {"id": 2299, "name": "הרב פלוני האלמוני", "count": 2},
]

SAMPLE_FS_RAVS = [
    {"doc_id": "rav_abc123", "name": "הרב אוהד תירוש", "original_id": 12},
    {"doc_id": "rav_xyz789", "name": "הרב חיים וידל", "original_id": 19},
]

# Pre-computed match results (simulating what match_ravs() returns)
PRECOMPUTED_RAV_MATCHES = [
    {"wp_id": 2290, "firestore_doc_id": "rav_abc123", "confidence": "exact", "note": ""},
    {"wp_id": 2293, "firestore_doc_id": "rav_xyz789", "confidence": "fuzzy",
     "note": "Name differs (edit distance 1): הרב חיים וידאל vs הרב חיים וידל"},
    {"wp_id": 2299, "firestore_doc_id": None, "confidence": "no_match",
     "note": "No Firestore entry found with similar name"},
]


# ── Test 1: exact match found ─────────────────────────────────────────────────

def test_exact_match_found():
    """
    When the WP name and Firestore name are identical (after normalisation),
    match_ravs should return confidence='exact'.

    build_mapping should then produce status='confirmed' with all Firestore fields
    populated.
    """
    matches = match_ravs(SAMPLE_WP_RAVS, SAMPLE_FS_RAVS)
    exact_match = next(m for m in matches if m["wp_id"] == 2290)

    assert exact_match["confidence"] == "exact"
    assert exact_match["firestore_doc_id"] == "rav_abc123"

    # Also verify build_mapping produces the right output
    mapping = build_mapping(
        wp_items=SAMPLE_WP_RAVS,
        fs_items=SAMPLE_FS_RAVS,
        llm_matches=matches,
    )
    entry = next(e for e in mapping if e["wp_id"] == 2290)
    assert entry["status"] == "confirmed"
    assert entry["firestore_doc_id"] == "rav_abc123"
    assert entry["firestore_name"] == "הרב אוהד תירוש"
    assert entry["firestore_original_id"] == 12


# ── Test 2: fuzzy match detected ──────────────────────────────────────────────

def test_fuzzy_match_detected():
    """
    וידל vs וידאל differ by one character (alef). match_ravs should return
    confidence='fuzzy' because the edit distance is ≤ 2.

    The raw WP and Firestore names must actually differ (not identical).
    """
    matches = match_ravs(SAMPLE_WP_RAVS, SAMPLE_FS_RAVS)
    fuzzy_match = next(m for m in matches if m["wp_id"] == 2293)

    # Confirm names differ
    wp_name = next(r["name"] for r in SAMPLE_WP_RAVS if r["id"] == 2293)
    fs_name = next(r["name"] for r in SAMPLE_FS_RAVS if r["doc_id"] == fuzzy_match["firestore_doc_id"])
    assert wp_name != fs_name, "Test setup: WP and FS names should differ (וידאל vs וידל)"

    assert fuzzy_match["confidence"] == "fuzzy"
    assert fuzzy_match["firestore_doc_id"] == "rav_xyz789"

    # build_mapping should give needs_review for fuzzy
    mapping = build_mapping(
        wp_items=SAMPLE_WP_RAVS,
        fs_items=SAMPLE_FS_RAVS,
        llm_matches=matches,
    )
    entry = next(e for e in mapping if e["wp_id"] == 2293)
    assert entry["status"] == "needs_review"
    assert entry["firestore_doc_id"] == "rav_xyz789"
    assert entry["firestore_original_id"] == 19


# ── Test 3: mapping file has all required fields ───────────────────────────────

def test_mapping_file_has_required_fields():
    """
    Every entry in the mapping must have all required top-level keys:
    wp_id, wp_name, firestore_doc_id, firestore_name, firestore_original_id,
    confidence, status.
    """
    mapping = build_mapping(
        wp_items=SAMPLE_WP_RAVS,
        fs_items=SAMPLE_FS_RAVS,
        llm_matches=PRECOMPUTED_RAV_MATCHES,
    )

    required_keys = {
        "wp_id",
        "wp_name",
        "firestore_doc_id",
        "firestore_name",
        "firestore_original_id",
        "confidence",
        "status",
    }

    for entry in mapping:
        missing = required_keys - set(entry.keys())
        assert not missing, (
            f"Entry for wp_id={entry.get('wp_id')} is missing fields: {missing}"
        )


# ── Test 4: confirmed entries never have null firestore_doc_id ────────────────

def test_confirmed_entries_have_firestore_doc_id():
    """
    Any entry with status='confirmed' must have a non-null firestore_doc_id.
    An entry with status='confirmed' and firestore_doc_id=None is a data bug.

    We test this by crafting matches where one 'exact' references a nonexistent doc —
    build_mapping must demote it to no_match rather than produce a confirmed+null entry.
    """
    bad_matches = [
        # This references a doc_id that does NOT exist in SAMPLE_FS_RAVS
        {"wp_id": 2290, "firestore_doc_id": "does_not_exist", "confidence": "exact", "note": ""},
        {"wp_id": 2293, "firestore_doc_id": "rav_xyz789",    "confidence": "fuzzy", "note": ""},
        {"wp_id": 2299, "firestore_doc_id": None,             "confidence": "no_match", "note": ""},
    ]

    mapping = build_mapping(
        wp_items=SAMPLE_WP_RAVS,
        fs_items=SAMPLE_FS_RAVS,
        llm_matches=bad_matches,
    )

    confirmed_entries = [e for e in mapping if e["status"] == "confirmed"]

    for entry in confirmed_entries:
        assert entry["firestore_doc_id"] is not None, (
            f"Confirmed entry wp_id={entry['wp_id']} has null firestore_doc_id"
        )


# ── Test 5: no_match entries always have null Firestore fields ────────────────

def test_no_match_entries_have_null_firestore():
    """
    Any entry with confidence='no_match' must have firestore_doc_id=None,
    firestore_name=None, and firestore_original_id=None.
    """
    mapping = build_mapping(
        wp_items=SAMPLE_WP_RAVS,
        fs_items=SAMPLE_FS_RAVS,
        llm_matches=PRECOMPUTED_RAV_MATCHES,
    )

    no_match_entries = [e for e in mapping if e["confidence"] == "no_match"]

    assert no_match_entries, "Expected at least one no_match entry in the test data"

    for entry in no_match_entries:
        assert entry["firestore_doc_id"] is None, (
            f"no_match entry wp_id={entry['wp_id']} has non-null firestore_doc_id"
        )
        assert entry["firestore_name"] is None, (
            f"no_match entry wp_id={entry['wp_id']} has non-null firestore_name"
        )
        assert entry["firestore_original_id"] is None, (
            f"no_match entry wp_id={entry['wp_id']} has non-null firestore_original_id"
        )


# ── Bonus: series format normalisation ───────────────────────────────────────

def test_series_format_normalisation_matches():
    """
    The known format difference documented in BNEI_DAVID_PHASE2_FINDINGS.md:
    Old PG:  עבודת אלוקים [התשפ''ו] - הרב קלנר
    New WP:  עבודת אלוקים [תשפו'] | הרב קלנר
    Should resolve to a fuzzy match (same series, different formatting).
    """
    wp_series = [
        {"id": 2509, "name": "עבודת אלוקים [תשפו'] | הרב קלנר", "count": 10},
    ]
    fs_series = [
        {"doc_id": "series_pg630", "name": "עבודת אלוקים [התשפ''ו] - הרב קלנר", "original_id": 630},
    ]

    matches = match_series(wp_series, fs_series)
    assert len(matches) == 1
    m = matches[0]
    assert m["firestore_doc_id"] == "series_pg630", (
        f"Expected fuzzy series match but got: {m}"
    )
    assert m["confidence"] in ("exact", "fuzzy"), (
        f"Expected exact or fuzzy but got: {m['confidence']}"
    )


def test_bad_firestore_doc_id_treated_as_no_match():
    """
    If a match references a firestore_doc_id that doesn't exist in the FS list,
    build_mapping should treat it as no_match (null everything).
    """
    matches_with_hallucination = [
        {"wp_id": 2290, "firestore_doc_id": "does_not_exist_xyz", "confidence": "exact", "note": ""},
        {"wp_id": 2293, "firestore_doc_id": "rav_xyz789",         "confidence": "fuzzy", "note": ""},
        {"wp_id": 2299, "firestore_doc_id": None,                  "confidence": "no_match", "note": ""},
    ]

    mapping = build_mapping(
        wp_items=SAMPLE_WP_RAVS,
        fs_items=SAMPLE_FS_RAVS,
        llm_matches=matches_with_hallucination,
    )

    hallucinated_entry = next(e for e in mapping if e["wp_id"] == 2290)
    assert hallucinated_entry["firestore_doc_id"] is None
    assert hallucinated_entry["confidence"] == "no_match"
    assert hallucinated_entry["status"] == "needs_review"
