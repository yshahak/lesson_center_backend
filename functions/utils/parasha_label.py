#!/usr/bin/env python3
"""
Parasha Label Updater

Runs every Sunday to determine the upcoming Shabbat's Torah portion (parasha),
find relevant lessons in Firestore, and write/update the 'label_parasha' document.

Design decisions:
- Uses pyluach (already a dependency) to calculate the Hebrew calendar parasha.
- Searches via two Firestore range queries (lessons whose titles start with the
  bare parasha name, e.g. "נשא", or with the "פרשת נשא" prefix).
  This covers ~95% of actual lesson titles without any embedding calls.
- Ranks results: video > audio-only, then most-recent timestamp first.
- Writes to a *stable* document ID "label_parasha" so the same doc is
  overwritten each week — no duplicates accumulate.
- sourceId=0 marks it as cross-source / featured content.
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional

import firebase_admin
from firebase_admin import firestore

from pyluach import dates as heb_dates, parshios

logger = logging.getLogger(__name__)

# Stable document ID — overwritten each week, never duplicated.
LABEL_DOC_ID = "label_parasha"

# How many lesson IDs to store in the label.
MAX_LESSONS = None  # No limit — store all matching lessons

# sourceId=0 — cross-source / featured.
LABEL_SOURCE_ID = 0


def _get_db():
    """Return Firestore client, initialising Firebase app once if needed."""
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": "tora-or"})
    return firestore.client()


def get_upcoming_parasha_name() -> Optional[str]:
    """Return the Hebrew name of the parasha for the upcoming Shabbat.

    Called on Sunday — the upcoming Shabbat is 6 days away.
    Uses Israel schedule (israel=True) so combined parshiyot match what
    Israeli yeshivot actually read.

    Returns
    -------
    str or None
        Hebrew parasha name, e.g. "נשא" or "מטות, מסעי" for a double parsha.
        Returns None on a Yom Tov Shabbat that has no parasha.
    """
    today = datetime.date.today()
    # Find the next Saturday (weekday=5 in Python's Mon=0 convention).
    days_until_shabbat = (5 - today.weekday()) % 7
    if days_until_shabbat == 0:
        # Today is already Shabbat — treat as "next Shabbat" (defensive).
        days_until_shabbat = 7
    next_shabbat = today + datetime.timedelta(days=days_until_shabbat)

    greg = heb_dates.GregorianDate(next_shabbat.year, next_shabbat.month, next_shabbat.day)
    # israel=True: single-day Yom Tov, matches Israeli yeshiva schedule.
    name = parshios.getparsha_string(greg, israel=True, hebrew=True)

    logger.info(f"Upcoming Shabbat: {next_shabbat}  Parasha: {name!r}")
    return name  # None on Yom Tov Shabbat


def _search_lessons_for_parasha(db, parasha_name: str) -> list:
    """Query Firestore for lessons whose title is about *parasha_name*.

    Two range queries are issued per search term (Firestore does not support
    substring search):
      1. Titles starting with the bare name, e.g. "נשא - ..."
      2. Titles starting with "פרשת <name>", e.g. "פרשת נשא ..."

    For double parshiyot (e.g. "מטות, מסעי") we also search each half
    individually, so lessons that reference only one name are captured.

    Results are merged (deduped by doc ID), then sorted:
      - Primary:   has video (videoUrl or vimeoId) before audio-only
      - Secondary: most-recent timestamp first

    Returns
    -------
    list of dict with keys: id, title, sourceId, timestamp, has_video, has_audio
    """
    def _range_end(prefix: str) -> str:
        return prefix[:-1] + chr(ord(prefix[-1]) + 1)

    def _run_query(prefix: str) -> list:
        end = _range_end(prefix)
        try:
            return list(
                db.collection("lessons")
                .where("title", ">=", prefix)
                .where("title", "<", end)
                .stream()
            )
        except Exception as exc:
            logger.warning(f"Firestore query failed for prefix {prefix!r}: {exc}")
            return []

    # Build list of bare search terms
    if ", " in parasha_name:
        # Double parsha — search the full combined string AND each part
        search_terms = [parasha_name] + [p.strip() for p in parasha_name.split(", ")]
    else:
        search_terms = [parasha_name]

    seen_ids: set = set()
    raw_docs: list = []

    for term in search_terms:
        for doc in _run_query(term):
            if doc.id not in seen_ids:
                seen_ids.add(doc.id)
                raw_docs.append(doc)
        for doc in _run_query("פרשת " + term):
            if doc.id not in seen_ids:
                seen_ids.add(doc.id)
                raw_docs.append(doc)

    logger.info(f"Found {len(raw_docs)} candidate lessons for parasha '{parasha_name}'")

    results = []
    for doc in raw_docs:
        data = doc.to_dict()
        if not data:
            continue
        has_video = bool(data.get("videoUrl") or data.get("vimeoId"))
        has_audio = bool(data.get("audioUrl") or data.get("streamAudioFileId"))
        results.append({
            "id": doc.id,
            "title": data.get("title", ""),
            "sourceId": data.get("sourceId"),
            "timestamp": data.get("timestamp", 0) or 0,
            "has_video": has_video,
            "has_audio": has_audio,
        })

    # Video-first, then most-recent
    results.sort(key=lambda x: (0 if x["has_video"] else 1, -x["timestamp"]))
    return results


def update_parasha_label(parasha_name: Optional[str] = None) -> dict:
    """Find lessons for the upcoming parasha and write the label to Firestore.

    Parameters
    ----------
    parasha_name : str, optional
        Override the auto-detected parasha (useful for testing).

    Returns
    -------
    dict with keys:
        parasha        - Hebrew name used
        label          - full label string stored in Firestore
        lessons_found  - total candidates found
        lessons_stored - how many IDs were written to the label
        doc_id         - Firestore document ID of the label
        status         - "ok" | "no_parasha" | "no_lessons"
        top_lessons    - list of {id, title} for the stored lessons (when ok)
    """
    db = _get_db()

    # 1. Determine parasha
    if parasha_name is None:
        parasha_name = get_upcoming_parasha_name()

    if not parasha_name:
        logger.warning("No parasha this Shabbat (Yom Tov). Skipping label update.")
        return {"status": "no_parasha", "parasha": None}

    label_text = f"פרשת {parasha_name}"

    # 2. Search lessons
    lessons = _search_lessons_for_parasha(db, parasha_name)

    if not lessons:
        logger.warning(f"No lessons found for parasha '{parasha_name}'")
        return {
            "status": "no_lessons",
            "parasha": parasha_name,
            "label": label_text,
            "lessons_found": 0,
            "lessons_stored": 0,
            "doc_id": LABEL_DOC_ID,
        }

    # 3. All matching lessons — no limit
    top = lessons
    lesson_ids = [item["id"] for item in top]

    # 4. Delete any previous parasha labels (old docs with different IDs)
    labels_ref = db.collection("labels")
    for old_doc in labels_ref.stream():
        d = old_doc.to_dict()
        if old_doc.id != LABEL_DOC_ID and 'פרש' in d.get('label', ''):
            logger.info(f"Deleting old parasha label: {old_doc.id} ({d.get('label')})")
            old_doc.reference.delete()

    # 5. Write / overwrite the label document
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    label_data = {
        "label": label_text,
        "sourceId": LABEL_SOURCE_ID,
        "lessonIds": lesson_ids,
        "updatedAt": now_utc,
    }

    label_ref = db.collection("labels").document(LABEL_DOC_ID)
    existing = label_ref.get()
    if existing.exists:
        label_data["createdAt"] = existing.to_dict().get("createdAt", now_utc)
    else:
        label_data["createdAt"] = now_utc

    label_ref.set(label_data)

    logger.info(
        f"Updated label '{LABEL_DOC_ID}': '{label_text}' "
        f"with {len(lesson_ids)} lessons ({len(lessons)} candidates found)"
    )
    for i, item in enumerate(top, 1):
        logger.info(
            f"  #{i:02d} src={item['sourceId']} vid={item['has_video']} "
            f"aud={item['has_audio']} ts={item['timestamp']} "
            f"title={item['title'][:60]}"
        )

    return {
        "status": "ok",
        "parasha": parasha_name,
        "label": label_text,
        "lessons_found": len(lessons),
        "lessons_stored": len(lesson_ids),
        "doc_id": LABEL_DOC_ID,
        "top_lessons": [
            {"id": item["id"], "title": item["title"][:80]}
            for item in top
        ],
    }


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = update_parasha_label()
    print(json.dumps(result, ensure_ascii=False, indent=2))
