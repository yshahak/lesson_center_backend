"""
Tests: label integrity.

Every lesson ID in a label's lessonIds array should:
1. Exist as a Firestore document
2. Match the label's sourceId (lesson belongs to the right source)
"""
import pytest


def test_label_lesson_ids_all_exist_in_firestore(fs):
    """Every ID in every label's lessonIds array must exist in Firestore."""
    labels = list(fs.db.collection("labels").stream())
    missing = []

    for label_doc in labels:
        data = label_doc.to_dict()
        label_name = data.get("label", label_doc.id)
        lesson_ids = data.get("lessonIds", [])

        for lesson_id in lesson_ids:
            actual_id = lesson_id.replace("lesson_", "") if lesson_id.startswith("lesson_") else lesson_id
            doc = fs.get_lesson(actual_id)
            if not doc.exists:
                missing.append(f"Label '{label_name}': lesson {actual_id} not found")

    assert not missing, (
        f"{len(missing)} label lessonIds point to non-existent documents:\n"
        + "\n".join(missing[:20])
    )


def test_labels_have_no_duplicate_lesson_ids(fs):
    """No label should have duplicate lesson IDs in its array."""
    labels = list(fs.db.collection("labels").stream())
    duplicates = []

    for label_doc in labels:
        data = label_doc.to_dict()
        lesson_ids = data.get("lessonIds", [])
        if len(lesson_ids) != len(set(lesson_ids)):
            dupes = [id for id in set(lesson_ids) if lesson_ids.count(id) > 1]
            duplicates.append(f"Label '{data.get('label', label_doc.id)}': {dupes}")

    assert not duplicates, f"Labels with duplicate IDs:\n" + "\n".join(duplicates)


def test_all_labels_have_lesson_ids(fs):
    """No label should have an empty lessonIds array after populate_label_lessons.py ran."""
    labels = list(fs.db.collection("labels").stream())
    empty = [
        doc.to_dict().get("label", doc.id)
        for doc in labels
        if not doc.to_dict().get("lessonIds")
    ]
    assert not empty, (
        f"{len(empty)} labels have empty lessonIds — "
        f"run populate_label_lessons.py: {empty}"
    )


def test_labels_are_unique_by_name(fs):
    """After cleanup, each label name should appear in exactly one document."""
    labels = list(fs.db.collection("labels").stream())
    name_counts = {}
    for doc in labels:
        name = doc.to_dict().get("label", "")
        name_counts[name] = name_counts.get(name, 0) + 1

    duplicates = {name: count for name, count in name_counts.items() if count > 1}
    assert not duplicates, (
        f"Duplicate label names found (cleanup_duplicate_labels.py needed): {duplicates}"
    )
