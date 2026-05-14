#!/usr/bin/env python3
"""
Post-process the bnei_david taxonomy mapping files with manual corrections.

Corrects:
 - Fuzzy matches that are actually different series (different years or different ravs)
 - No-matches that exist in Firestore under a slightly different name format

Run AFTER generate_bnei_david_taxonomy_mapping.py has produced the initial files.

Usage:
    python scripts/postprocess_bnei_david_mapping.py
"""

import json
import os
import warnings
warnings.filterwarnings("ignore")

import firebase_admin
from firebase_admin import firestore

PROJECT_ID = "tora-or"
SOURCE_ID = 1
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RAVS_FILE  = os.path.join(DATA_DIR, "bnei_david_ravs_mapping.json")
SERIES_FILE = os.path.join(DATA_DIR, "bnei_david_series_mapping.json")


def get_db():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
    return firestore.client()


def load_fs_series(db):
    docs = list(db.collection("series").where("sourceId", "==", SOURCE_ID).stream())
    by_name = {}
    for doc in docs:
        d = doc.to_dict()
        name = d.get("serie", "")
        by_name[name] = {
            "doc_id": doc.id,
            "name": name,
            "original_id": d.get("originalId"),
        }
    return by_name


def load_mapping(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_mapping(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Correction helpers ────────────────────────────────────────────────────────

def make_idx(mapping):
    return {e["wp_id"]: e for e in mapping}


def set_match(idx, wp_id, fs_doc, confidence, note=""):
    e = idx.get(wp_id)
    if not e:
        print(f"  WARNING: wp_id {wp_id} not found in mapping")
        return
    e["firestore_doc_id"]      = fs_doc["doc_id"]
    e["firestore_name"]        = fs_doc["name"]
    e["firestore_original_id"] = fs_doc["original_id"]
    e["confidence"]            = confidence
    e["status"]                = "confirmed" if confidence == "exact" else "needs_review"
    if note:
        e["note"] = note
    elif "note" in e:
        del e["note"]


def set_no_match(idx, wp_id, note=""):
    e = idx.get(wp_id)
    if not e:
        print(f"  WARNING: wp_id {wp_id} not found in mapping")
        return
    e["firestore_doc_id"]      = None
    e["firestore_name"]        = None
    e["firestore_original_id"] = None
    e["confidence"]            = "no_match"
    e["status"]                = "needs_review"
    if note:
        e["note"] = note


def set_note(idx, wp_id, note):
    e = idx.get(wp_id)
    if e:
        e["note"] = note


def find(fs_by_name, name):
    """Exact FS name lookup; returns the doc dict or None."""
    return fs_by_name.get(name)


def main():
    print("Loading Firestore series...", flush=True)
    db = get_db()
    fs_by_name = load_fs_series(db)
    print(f"  {len(fs_by_name)} Firestore series loaded", flush=True)

    print("Loading mapping files...", flush=True)
    series = load_mapping(SERIES_FILE)
    idx = make_idx(series)

    # =========================================================================
    # SERIES CORRECTIONS
    # =========================================================================
    # Organised by fix type.  All wp_ids are from the actual WP taxonomy API.

    # ─── A) Previously fuzzy-matched with WRONG YEAR → demote to no_match ────

    # Different years are different series; the automated matcher picked the
    # closest-distance FS name, which happened to differ only in year.

    set_no_match(idx, 2502, "אורות התורה [תשפ\"ו] — year-specific; FS only has [תשפ\"ג] which is a different year")
    set_no_match(idx, 405,  "זרעונים [תשע\"ט] — year-specific; no FS equivalent with matching year")
    set_no_match(idx, 407,  "זרעונים [תשפ\"ד] - הרב יהודה — no FS equivalent (FS has [תשפ\"ב])")
    set_no_match(idx, 592,  "נתיב העבודה [תשע\"ח] — no FS equivalent (FS has [תשע'א])")
    set_no_match(idx, 665,  "עולת ראי\"ה [תשע\"ח] - הרב רביד — no FS equivalent (FS has [תשפ'])")
    set_no_match(idx, 747,  "שפת אמת לחודש אלול [תש\"פ] — no FS equivalent (FS has [תשפ\"א])")
    set_no_match(idx, 769,  "תרבות המערב [תשע\"ב] — no FS equivalent (FS has [תשע\"ח])")
    set_no_match(idx, 770,  "תרבות המערב [תשע\"ג] — no FS equivalent (FS has [תשע\"ח])")

    # ─── B) Fuzzy-matched with WRONG RAV → demote to no_match ────────────────

    set_no_match(idx, 384,  "הלכה - הרב ישי רז: matched to הרב שילר by mistake (different rav)")
    set_no_match(idx, 490,  "כללי - הרב פנירי: matched to הרב פנחס by mistake (different rav)")
    set_no_match(idx, 498,  "כללי - הרב שלום: matched to הרב אלי by mistake (different rav)")
    set_no_match(idx, 562,  "מידות הראי\"ה — matched to אגרות הראי\"ה by mistake (completely different book)")

    # ─── C) Fuzzy-matched with correct year but wrong FS year → fix ──────────

    # WP: אורות ישראל [תשע'ט] — FS has the same with rav name in front
    if doc := find(fs_by_name, "אורות ישראל - הרב קלנר [תשע'ט]"):
        set_match(idx, 328, doc, "fuzzy", "Same series — rav name placement differs")
    if doc := find(fs_by_name, "אורות ישראל - הרב קלנר [תשפ\"ב]"):
        set_match(idx, 330, doc, "fuzzy", "Same series — rav name placement differs")
    if doc := find(fs_by_name, "גבורות ה' - הרב אלי [תשע''ח]"):
        set_match(idx, 349, doc, "fuzzy", "Same series — year bracket position differs")
    if doc := find(fs_by_name, "מסילת ישרים תשע\"ד - הרב קשתיאל"):
        set_match(idx, 572, doc, "fuzzy", "Same series — WP uses brackets around year, FS does not")
    if doc := find(fs_by_name, "מסילת ישרים - הרב קשתיאל [תשע\"ט]"):
        set_match(idx, 574, doc, "fuzzy", "Same series — year bracket position and formatting differ")

    # ─── D) Improve notes on ambiguous entries ─────────────────────────────────

    set_note(idx, 578, "Same series — WP uses brackets around year, FS does not: [תש\"פ] vs תש\"פ")
    set_note(idx, 2517, "אורות התורה (no year) — FS has year-specific versions; needs human disambiguation")
    set_note(idx, 314, "אורות התורה [תשפ\"ג] for הרב ישי רז — FS has same year but for הרב קשתיאל (different rav)")
    set_note(idx, 391, "הקדמה לעין אי''ה - הרב קלנר (no year) — FS has year-specific versions; needs human disambiguation")

    # ─── E) No-matches that DO exist in FS under a different format ────────────

    # WP name → FS name (verified against Firestore)

    fixes = [
        # wp_id, fs_name, confidence, note
        (290,  "אור חדש למהר\"ל - הרב קשתיאל תשע'ו",       "fuzzy", "Same series — year/separator placement differs"),
        (292,  "אור לנתיבתי - הרב קשתיאל [תשע'ו]",         "fuzzy", "Same series — rav/year ordering differs"),
        (295,  "אורות - הרב קשתיאל [תשע\"ח]",              "fuzzy", "Same series — rav/year ordering differs"),
        (301,  "אורות האמונה - הרב קלנר [תשפ\"א]",         "fuzzy", "Same series — rav/year ordering differs"),
        (305,  "אורות הקודש א' - הרב קשתיאל [תשפ']",      "fuzzy", "Same series — rav/year ordering differs"),
        (307,  "אורות הקודש ב' - הרב קשתיאל",              "fuzzy", "Same series — WP has year [תשע\"ו], FS entry has no year"),
        (311,  "אורות ישראל- הרב עקיבא [תשפ\"ד]",          "fuzzy", "Same series — year bracket position differs"),
        (318,  "גבורות ה' הרב קשתיאל [תשפ\"ג]",            "fuzzy", "Same series — separator format differs"),
        (350,  "גבורות ה' הרב קשתיאל [תשפ\"ג]",            "fuzzy", "Same series — separator format differs"),
        (397,  "הרב אלי - למהלך האידיאות בישראל [תשס\"ח]", "fuzzy", "Same series — name order inverted"),
        (431,  "חומש - הרב קלנר [תשע'ט]",                  "fuzzy", "Same series — rav/year ordering differs"),
        (461,  "כוזרי | הרב אטון",                          "fuzzy", "Same series — WP has full name יאיר אטון, FS has just אטון"),
        (463,  "כוזרי - הרב קשתיאל [תש'פ]",                "fuzzy", "Same series — year bracket position differs"),
        (466,  "כוזרי - הרב קלנר [תשע''ז]",                "fuzzy", "Same series — year bracket position differs"),
        (467,  "כוזרי -הרב אוהד [תשפ\"ג]",                 "fuzzy", "Same series — year bracket position and separator differ"),
        (468,  "כוזרי הרב קלנר [תשפ\"ג]",                  "fuzzy", "Same series — year bracket position differs"),
        (509,  "למהלך האידאות - הרב קלנר [תשע\"ח]",        "fuzzy", "Same series — year bracket position differs"),
        (510,  "למהלך האידאות - הרב אליעזר קשתיאל {תשפ''ד}", "fuzzy", "Same series — year bracket style differs"),
        (511,  "למהלך האידאות - הרב עקיבא קשתיאל [תשפ''ה]", "fuzzy", "Same series — year bracket position differs"),
        (523,  "מאמר הדור - הרב קלנר [תשע\"ח]",            "fuzzy", "Same series — year bracket position differs"),
        (524,  "מאמר הדור - הרב אלי",                       "fuzzy", "Same series — WP has year [תשע'ו], FS entry has no year"),
        (525,  "מאמר הדור - הרב קלנר [תשפ\"ד]",            "fuzzy", "Same series — year bracket position differs"),
        (527,  "מאמר עבודת אלוקים - הרב קלנר [תשפ']",     "fuzzy", "Same series — year bracket position differs"),
        (537,  "מבוא למשנת הרב קוק - הרב נתנאל [תשע\"ז]", "fuzzy", "Same series — year bracket position differs"),
        (538,  "מבוא למשנת הרב קוק - הרב נתנאל [תשע\"ח]", "fuzzy", "Same series — year bracket position differs"),
        (551,  "מוסר אביך - הרב רביד [תשע\"ט]",            "fuzzy", "Same series — year bracket position differs"),
        (552,  "מוסר אביך - הרב אליעזר קשתיאל [תשפ''ד]",  "fuzzy", "Same series — year bracket position differs"),
        (561,  "מידות - הרב קשתיאל [תשפ\"ד]",             "fuzzy", "Same series — year bracket position differs"),
        (563,  "מידות הראי\"ה - הרב קשתיאל [תשע\"ט]",     "fuzzy", "Same series — year bracket position differs"),
        (569,  "מסילת ישרים - הרב עקיבא [תשפ\"ד]",        "fuzzy", "Same series — year bracket position differs"),
        (573,  "מסילת ישרים - הרב אוהד [תשע\"ט]",         "fuzzy", "Same series — year bracket position differs"),
        (575,  "מסילת ישרים - הרב קשתיאל [תשפ\"ב]",       "fuzzy", "Same series — year bracket position differs"),
        (576,  "מסכת אבות - הרב קשתיאל [תשע\"ז]",         "fuzzy", "Same series — year bracket position differs"),
        (590,  "נצח ישראל | הרב דוד בן מאיר [תשע''ז]",    "fuzzy", "Same series — separator style differs"),
        (616,  "סוגיית ארץ ישראל - הרב קלנר [תשע'ו]",     "fuzzy", "Same series — year bracket position differs"),
        (625,  "ספר איוב - הרב קשתיאל [תשע\"ח]",          "fuzzy", "Same series — year bracket position differs"),
        (626,  "דברי הימים א' - הרב קשתיאל [תשפ\"ג]",     "fuzzy", "Same series — WP says 'ספר', FS omits it"),
        (627,  "ספר דברי הימים ב' - הרב קשתיאל [תשפ\"ג]", "fuzzy", "Same series — year bracket position differs"),
        (631,  "ספר התניא - הרב קשתיאל [תשע\"ט]",          "fuzzy", "Same series — year bracket position differs"),
        (639,  "ספר יחזקאל - הרב קשתיאל [תשע'ו]",         "fuzzy", "Same series — year bracket position differs"),
        (641,  "ספר ישעיהו - הרב קשתיאל [תשע\"ח]",        "fuzzy", "Same series — year bracket position differs"),
        (647,  "ספר משלי - הרב קשתיאל [תשפ''ד]",          "fuzzy", "Same series — WP has range [תשפ''ד-תשפ\"ו], FS has single year; same series"),
        (657,  "ספר שמואל א' - הרב קשתיאל [תשע\"ג]",      "fuzzy", "Same series — year bracket position differs"),
        (659,  "ספר שמואל ב' - הרב קשתיאל [תש\"ע]",       "fuzzy", "Same series — year bracket position differs"),
        (668,  "עולת ראיה - הרב קשתיאל [תשע'ב]",          "fuzzy", "Same series — year bracket position differs"),
        (735,  "שיר השירים ע''פ הרמ''ד ואלי - הרב קשתיאל תשע'ו", "fuzzy", "Same series — separator differs"),
        (539,  "מבוא לתורה שבע\"פ - הרב קשתיאל [תשע'ט]", "fuzzy", "Same series — rav/year ordering differs"),
    ]

    for wp_id, fs_name, confidence, note in fixes:
        doc = find(fs_by_name, fs_name)
        if doc:
            set_match(idx, wp_id, doc, confidence, note)
        else:
            print(f"  WARNING: FS series not found: '{fs_name}' (for wp_id {wp_id})")

    # ─── F) Special cases ────────────────────────────────────────────────────

    # WP 531: מאמרי ראי"ה - הרב קלנר — look up the real name
    if doc := find(fs_by_name, 'מאמרי ראי"ה - הרב קלנר'):
        set_match(idx, 531, doc, "exact", "")
    else:
        # Try variant without geresh
        for name, d in fs_by_name.items():
            if "מאמרי" in name and "קלנר" in name:
                set_match(idx, 531, d, "fuzzy", f"Same series — spelling variant: {name}")
                break

    # WP 544: מגילת שיר השירים [תשע''ו] - הרב קשתיאל → FS: "שיר השירים - הרב קשתיאל [תשע''ו]"
    if doc := find(fs_by_name, "שיר השירים - הרב קשתיאל [תשע''ו]"):
        set_match(idx, 544, doc, "fuzzy", "Same series — WP says 'מגילת שיר השירים', FS says 'שיר השירים'")

    # WP 545: מגילת שיר השירים [תשפ"ד] - הרב קשתיאל → FS: "מגילת שיר השירים - הרב קשתיאל [תשפ\"ד]"
    if doc := find(fs_by_name, 'מגילת שיר השירים - הרב קשתיאל [תשפ"ד]'):
        set_match(idx, 545, doc, "fuzzy", "Same series — year bracket position differs")

    # WP 500: כללי | הרב ברינבאום → FS might have בירנבאום
    for name, d in fs_by_name.items():
        if "כללי" in name and ("בירנ" in name or "ברינ" in name):
            set_match(idx, 500, d, "fuzzy", f"Same series — name spelling: ברינבאום vs בירנבאום")
            break

    # WP 663: עולת רא''יה-הרב קלנר → check various FS forms
    for name, d in fs_by_name.items():
        if "עולת" in name and "קלנר" in name:
            set_match(idx, 663, d, "fuzzy", f"Same series — different name format: {name}")
            break

    # WP 822: ספר מלכים א' → FS: "ספר מלכים א', ב' - הרב קשתיאל"
    if doc := find(fs_by_name, "ספר מלכים א', ב' - הרב קשתיאל"):
        set_match(idx, 822, doc, "fuzzy", "WP has only 'מלכים א', FS entry covers both א' and ב'")

    # WP 2509: עבודת אלוקים [תשפו'] | הרב קלנר → FS: "עבודת אלוקים - הרב קלנר"
    if doc := find(fs_by_name, "עבודת אלוקים - הרב קלנר"):
        set_match(idx, 2509, doc, "fuzzy", "Same series — WP has year [תשפו'] and | separator, FS entry has no year")

    # WP 539: מבוא לתורה שבע"פ — look for it
    if not find(fs_by_name, "מבוא לתורה שבע\"פ - הרב קשתיאל [תשע'ט]"):
        for name, d in fs_by_name.items():
            if "מבוא לתורה" in name:
                set_match(idx, 539, d, "fuzzy", f"Same series — format differs: {name}")
                break

    # ─── G) Ensure תרבות המערב [תשע"ח] - הרב יגאל gets its own match ─────────
    if doc := find(fs_by_name, "תרבות המערב [תשע\"ח] | הרב יגאל לוינשטיין"):
        set_match(idx, 771, doc, "fuzzy", "Same series — same year, separator style differs")

    # =========================================================================
    # SAVE
    # =========================================================================

    save_mapping(series, SERIES_FILE)

    # Print summary
    exact   = sum(1 for e in series if e["confidence"] == "exact")
    fuzzy   = sum(1 for e in series if e["confidence"] == "fuzzy")
    no_match = sum(1 for e in series if e["confidence"] == "no_match")

    print(f"\n=== SERIES (after post-processing) ===")
    print(f"Total WP series: {len(series)}")
    print(f"Exact matches: {exact}")
    print(f"Fuzzy matches (needs review): {fuzzy}")
    print(f"No match (new, will create): {no_match}")
    print(f"\nUpdated: {SERIES_FILE}")


if __name__ == "__main__":
    main()
