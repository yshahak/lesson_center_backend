#!/usr/bin/env python3
"""
Generate taxonomy mapping files (ravs + series) that map WordPress IDs from
the new bneidavid.org site to existing Firestore docs for sourceId=1.

Output files (for human review — not used automatically):
    data/bnei_david_ravs_mapping.json
    data/bnei_david_series_mapping.json

Usage:
    python scripts/generate_bnei_david_taxonomy_mapping.py

Prerequisites:
    - Firebase ADC: gcloud auth application-default login
    - pip install firebase-admin requests
"""

import json
import os
import re
import sys
import time
import unicodedata

import requests
import firebase_admin
from firebase_admin import firestore

# ── Constants ─────────────────────────────────────────────────────────────────

PROJECT_ID = "tora-or"
SOURCE_ID = 1

WP_BASE = "https://bneidavid.org/wp-json/wp/v2"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

RAVS_OUTPUT = os.path.join(OUTPUT_DIR, "bnei_david_ravs_mapping.json")
SERIES_OUTPUT = os.path.join(OUTPUT_DIR, "bnei_david_series_mapping.json")


# ── Firestore initialisation ──────────────────────────────────────────────────

def get_firestore_client():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
    return firestore.client()


# ── WordPress pagination ──────────────────────────────────────────────────────

def fetch_wp_taxonomy(taxonomy: str) -> list[dict]:
    """
    Paginate through all terms for a WP REST taxonomy endpoint.
    Returns list of {"id": int, "name": str, "count": int}.
    """
    results = []
    page = 1
    session = requests.Session()
    session.headers.update({"User-Agent": "lesson-center-mapper/1.0"})

    while True:
        url = f"{WP_BASE}/{taxonomy}"
        params = {"per_page": 100, "page": page}
        resp = session.get(url, params=params, timeout=30)

        if resp.status_code == 400:
            # WP returns 400 when page exceeds total pages
            break
        resp.raise_for_status()

        data = resp.json()
        if not data:
            break

        for item in data:
            results.append({
                "id": item["id"],
                "name": item["name"],
                "count": item.get("count", 0),
            })

        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        print(f"  [{taxonomy}] page {page}/{total_pages} — {len(data)} terms", flush=True)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.15)  # be polite

    return results


# ── Firestore loaders ─────────────────────────────────────────────────────────

def load_firestore_ravs(db) -> list[dict]:
    """Load all ravs for sourceId=1 from Firestore."""
    docs = list(
        db.collection("ravs")
        .where("sourceId", "==", SOURCE_ID)
        .stream()
    )
    result = []
    for doc in docs:
        d = doc.to_dict()
        result.append({
            "doc_id": doc.id,
            "name": d.get("rav", ""),
            "original_id": d.get("originalId"),
        })
    return result


def load_firestore_series(db) -> list[dict]:
    """Load all series for sourceId=1 from Firestore."""
    docs = list(
        db.collection("series")
        .where("sourceId", "==", SOURCE_ID)
        .stream()
    )
    result = []
    for doc in docs:
        d = doc.to_dict()
        result.append({
            "doc_id": doc.id,
            "name": d.get("serie", ""),
            "original_id": d.get("originalId"),
        })
    return result


# ── Name normalisation and matching ──────────────────────────────────────────

def _normalise(name: str) -> str:
    """
    Normalise a Hebrew name for comparison:
    - Strip leading/trailing whitespace
    - Collapse multiple spaces
    - Unicode NFC normalisation
    - Lower-case (Hebrew has no case, but catch any Latin chars)
    - Strip Hebrew niqqud (diacritics) if present
    """
    if not name:
        return ""
    # Unicode NFC
    name = unicodedata.normalize("NFC", name)
    # Strip Hebrew niqqud (U+05B0–U+05C7)
    name = re.sub(r"[ְ-ׇ]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name.strip())
    return name.lower()


def _series_key(name: str) -> str:
    """
    Produce a comparison key for a series name that is robust to the known
    formatting differences between PostgreSQL (old format) and WordPress (new format):

    Old format:  עבודת אלוקים [התשפ''ו] - הרב קלנר
    New format:  עבודת אלוקים [תשפו'] | הרב קלנר

    Normalisation steps:
    1. Apply _normalise() (whitespace, niqqud, NFC)
    2. Strip the separators ' - ' and ' | ' → uniform ' '
    3. Strip the bracket prefix ה (e.g. [התשפ] → [תשפ])
    4. Normalise year notation: [תשפ''ו], [תשפו'], [תשפ"ו], [תשפוֹ] → [תשפו]
       i.e. strip trailing punctuation inside brackets and strip the ה prefix
    """
    name = _normalise(name)
    # Normalise separators: ' - ' or ' | ' → ' '
    name = re.sub(r"\s*[-|]\s*", " ", name)
    # Strip leading ה inside year brackets: [התשפ → [תשפ
    name = re.sub(r"\[ה(תש[א-ת]+)", r"[\1", name)
    # Strip trailing punctuation inside brackets (quotes, apostrophes, geresh):
    # [תשפ''ו] → [תשפו], [תשפו'] → [תשפו], [תשפ"ו] → [תשפו]
    name = re.sub(r"\[([^\]]*?)[\"'׳״'']+([^\]]*?)\]", lambda m: f"[{m.group(1)}{m.group(2)}]", name)
    return name.strip()


def match_ravs(
    wp_items: list[dict],
    fs_items: list[dict],
) -> list[dict]:
    """
    Match WP rav terms to Firestore rav docs by name.

    Strategy:
    1. Exact normalised name match → confidence=exact
    2. One name is a substring of the other (handles minor appended/omitted chars) → fuzzy
    3. Levenshtein distance ≤ 2 on normalised names → fuzzy
    4. No match → no_match
    """
    results = []

    for wp in wp_items:
        wp_norm = _normalise(wp["name"])
        best_match = None
        best_confidence = "no_match"
        best_note = ""

        for fs in fs_items:
            fs_norm = _normalise(fs["name"])

            if wp_norm == fs_norm:
                best_match = fs
                best_confidence = "exact"
                best_note = ""
                break  # exact wins, stop searching

            # Substring containment (handles one-char additions like alef at end)
            if wp_norm in fs_norm or fs_norm in wp_norm:
                if best_confidence != "fuzzy":  # don't downgrade
                    best_match = fs
                    best_confidence = "fuzzy"
                    best_note = f"Substring match: '{wp['name']}' vs '{fs['name']}'"
                continue

            # Levenshtein distance ≤ 2
            dist = _levenshtein(wp_norm, fs_norm)
            if dist <= 2:
                if best_confidence not in ("exact", "fuzzy"):
                    best_match = fs
                    best_confidence = "fuzzy"
                    best_note = f"Name differs (edit distance {dist}): {wp['name']} vs {fs['name']}"

        results.append({
            "wp_id": wp["id"],
            "firestore_doc_id": best_match["doc_id"] if best_match else None,
            "confidence": best_confidence,
            "note": best_note,
        })

    return results


def match_series(
    wp_items: list[dict],
    fs_items: list[dict],
) -> list[dict]:
    """
    Match WP series terms to Firestore series docs by name.

    Uses _series_key() normalisation which handles the format differences between
    old PG-style series names and new WP-style names.
    """
    # Build Firestore index by series key for fast lookup
    fs_by_key: dict[str, list[dict]] = {}
    for fs in fs_items:
        key = _series_key(fs["name"])
        fs_by_key.setdefault(key, []).append(fs)

    results = []

    for wp in wp_items:
        wp_key = _series_key(wp["name"])
        wp_norm = _normalise(wp["name"])

        best_match = None
        best_confidence = "no_match"
        best_note = ""

        # 1. Exact series-key match
        if wp_key in fs_by_key:
            candidates = fs_by_key[wp_key]
            fs = candidates[0]  # take first if multiple (edge case)
            # Check if the raw normalised names are identical too
            if _normalise(wp["name"]) == _normalise(fs["name"]):
                best_match = fs
                best_confidence = "exact"
                best_note = ""
            else:
                best_match = fs
                best_confidence = "fuzzy"
                best_note = f"Format differs after normalisation: '{wp['name']}' vs '{fs['name']}'"
        else:
            # 2. Fallback: try levenshtein on series key
            best_dist = 999
            for fs in fs_items:
                fs_key = _series_key(fs["name"])
                dist = _levenshtein(wp_key, fs_key)
                if dist < best_dist:
                    best_dist = dist
                    if dist <= 3:  # more lenient for series (longer strings)
                        best_match = fs
                        best_confidence = "fuzzy"
                        best_note = (
                            f"Close but imperfect series-key match (edit distance {dist}): "
                            f"'{wp['name']}' vs '{fs['name']}'"
                        )
                    else:
                        best_match = None
                        best_confidence = "no_match"
                        best_note = ""

        results.append({
            "wp_id": wp["id"],
            "firestore_doc_id": best_match["doc_id"] if best_match else None,
            "confidence": best_confidence,
            "note": best_note,
        })

    return results


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            ins = prev[j + 1] + 1
            delete = curr[j] + 1
            sub = prev[j] + (0 if ca == cb else 1)
            curr.append(min(ins, delete, sub))
        prev = curr
    return prev[-1]


# ── Merge into final mapping ──────────────────────────────────────────────────

def build_mapping(
    wp_items: list[dict],
    fs_items: list[dict],
    llm_matches: list[dict],
    wp_name_key: str = "name",
    fs_name_key: str = "name",
) -> list[dict]:
    """
    Merge WP term data + Firestore doc data + match results into the
    final mapping format.

    This function is also used directly by unit tests (no network calls).
    """
    # Index WP items by id
    wp_by_id = {item["id"]: item for item in wp_items}
    # Index Firestore docs by doc_id
    fs_by_doc_id = {d["doc_id"]: d for d in fs_items}
    # Index match results by wp_id
    matches_by_wp_id = {m["wp_id"]: m for m in llm_matches}

    mapping = []
    for wp_item in wp_items:
        wp_id = wp_item["id"]
        wp_name = wp_item[wp_name_key]

        match = matches_by_wp_id.get(wp_id, {})
        fs_doc_id = match.get("firestore_doc_id")
        confidence = match.get("confidence", "no_match")
        note = match.get("note", "") or ""

        # Normalise confidence
        if confidence not in ("exact", "fuzzy", "no_match"):
            confidence = "no_match"
            note = f"Unexpected confidence value: {confidence}"

        if fs_doc_id and fs_doc_id in fs_by_doc_id:
            fs_doc = fs_by_doc_id[fs_doc_id]
            fs_name = fs_doc[fs_name_key]
            fs_orig_id = fs_doc["original_id"]
            status = "confirmed" if confidence == "exact" else "needs_review"
        else:
            fs_doc_id = None
            fs_name = None
            fs_orig_id = None
            confidence = "no_match"
            status = "needs_review"
            if not note:
                note = f"No Firestore entry found with similar name"

        entry = {
            "wp_id": wp_id,
            "wp_name": wp_name,
            "firestore_doc_id": fs_doc_id,
            "firestore_name": fs_name,
            "firestore_original_id": fs_orig_id,
            "confidence": confidence,
            "status": status,
        }
        if note:
            entry["note"] = note

        mapping.append(entry)

    return mapping


# ── Summary printer ───────────────────────────────────────────────────────────

def print_summary(label: str, mapping: list[dict]) -> None:
    exact = sum(1 for e in mapping if e["confidence"] == "exact")
    fuzzy = sum(1 for e in mapping if e["confidence"] == "fuzzy")
    no_match = sum(1 for e in mapping if e["confidence"] == "no_match")
    print(f"\n=== {label} ===")
    print(f"Total WP {label.lower()}: {len(mapping)}")
    print(f"Exact matches: {exact}")
    print(f"Fuzzy matches (needs review): {fuzzy}")
    print(f"No match (new, will create): {no_match}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Initialising Firestore...", flush=True)
    db = get_firestore_client()

    # ── Ravs ──────────────────────────────────────────────────────────────────

    print("\n--- Fetching WordPress ravs ---", flush=True)
    wp_ravs = fetch_wp_taxonomy("rav")
    print(f"  Total WP ravs fetched: {len(wp_ravs)}", flush=True)

    print("\n--- Loading Firestore ravs (sourceId=1) ---", flush=True)
    fs_ravs = load_firestore_ravs(db)
    print(f"  Total Firestore ravs: {len(fs_ravs)}", flush=True)

    print("\n--- Matching ravs by name ---", flush=True)
    rav_matches = match_ravs(wp_ravs, fs_ravs)
    exact_r = sum(1 for m in rav_matches if m["confidence"] == "exact")
    fuzzy_r = sum(1 for m in rav_matches if m["confidence"] == "fuzzy")
    none_r  = sum(1 for m in rav_matches if m["confidence"] == "no_match")
    print(f"  Exact: {exact_r}, Fuzzy: {fuzzy_r}, No match: {none_r}", flush=True)

    rav_mapping = build_mapping(
        wp_items=wp_ravs,
        fs_items=fs_ravs,
        llm_matches=rav_matches,
    )

    with open(RAVS_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(rav_mapping, f, ensure_ascii=False, indent=2)
    print(f"  Written: {RAVS_OUTPUT}", flush=True)

    # ── Series ────────────────────────────────────────────────────────────────

    print("\n--- Fetching WordPress series ---", flush=True)
    wp_series = fetch_wp_taxonomy("series")
    print(f"  Total WP series fetched: {len(wp_series)}", flush=True)

    print("\n--- Loading Firestore series (sourceId=1) ---", flush=True)
    fs_series = load_firestore_series(db)
    print(f"  Total Firestore series: {len(fs_series)}", flush=True)

    print("\n--- Matching series by name ---", flush=True)
    series_matches = match_series(wp_series, fs_series)
    exact_s = sum(1 for m in series_matches if m["confidence"] == "exact")
    fuzzy_s = sum(1 for m in series_matches if m["confidence"] == "fuzzy")
    none_s  = sum(1 for m in series_matches if m["confidence"] == "no_match")
    print(f"  Exact: {exact_s}, Fuzzy: {fuzzy_s}, No match: {none_s}", flush=True)

    series_mapping = build_mapping(
        wp_items=wp_series,
        fs_items=fs_series,
        llm_matches=series_matches,
    )

    with open(SERIES_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(series_mapping, f, ensure_ascii=False, indent=2)
    print(f"  Written: {SERIES_OUTPUT}", flush=True)

    # ── Summary ───────────────────────────────────────────────────────────────

    print_summary("RAVS", rav_mapping)
    print_summary("SERIES", series_mapping)

    rel_ravs = os.path.relpath(RAVS_OUTPUT)
    rel_series = os.path.relpath(SERIES_OUTPUT)
    print(f"\nFiles written:")
    print(f"- {rel_ravs}")
    print(f"- {rel_series}")


if __name__ == "__main__":
    main()
