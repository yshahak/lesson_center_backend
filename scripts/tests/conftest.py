"""
Shared fixtures for PostgreSQL ↔ Firestore integration tests.

PostgreSQL is the source of truth. Firestore is the migration target.
These tests validate that what's in Firestore matches what's in PostgreSQL.

Running:
    cd lesson_center_backend
    pip install pytest psycopg2-binary firebase-admin
    pytest scripts/tests/ -v

PostgreSQL is accessed via SSH (bitnami@3.70.156.78) using sudo -u postgres,
so no password is required.
"""
import csv
import io
import os
import shlex
import subprocess
import time

import firebase_admin
import pytest
from firebase_admin import firestore

PROJECT_ID = "tora-or"
SSH_KEY = os.path.expanduser("~/.ssh/id_rsa_mac_m1")
SSH_HOST = "bitnami@3.70.156.78"
DB_NAME = "lessons"


# ─── PostgreSQL helper ────────────────────────────────────────────────────────

class PostgresSSH:
    """Run SQL queries on the remote PostgreSQL via SSH."""

    def query(self, sql, timeout=60):
        # COPY...TO STDOUT works on PostgreSQL 11+ (--csv flag requires PG 12+)
        copy_sql = f"COPY ({sql}) TO STDOUT WITH CSV HEADER"
        cmd = f"sudo -u postgres psql -d {DB_NAME} -c {shlex.quote(copy_sql)}"
        result = subprocess.run(
            ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=accept-new",
             SSH_HOST, cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"PostgreSQL query failed:\n{result.stderr}")
        return list(csv.DictReader(io.StringIO(result.stdout)))

    def scalar(self, sql):
        """Return a single value from a COUNT or similar query."""
        rows = self.query(sql)
        if rows:
            return int(list(rows[0].values())[0])
        return 0


# ─── Firestore helper ─────────────────────────────────────────────────────────

class FirestoreClient:
    def __init__(self):
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
        self.db = firestore.client()

    def get_lesson(self, lesson_id: str):
        return self.db.collection("lessons").document(str(lesson_id)).get()

    def count_lessons_for(self, field: str, doc_id: str) -> int:
        result = (
            self.db.collection("lessons")
            .where(field, "==", doc_id)
            .count()
            .get()
        )
        if result and result[0]:
            return int(result[0][0].value)
        return 0

    def get_rav_doc_id(self, rav_original_id: int) -> str | None:
        docs = list(
            self.db.collection("ravs")
            .where("originalId", "==", rav_original_id)
            .limit(1)
            .stream()
        )
        return docs[0].id if docs else None


# ─── pytest fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def pg():
    return PostgresSSH()


@pytest.fixture(scope="session")
def fs():
    return FirestoreClient()


@pytest.fixture(scope="session")
def all_firestore_ravs(fs):
    """Dict of originalId → (firestoreDocId, totalCount) for all ravs."""
    result = {}
    for doc in fs.db.collection("ravs").stream():
        data = doc.to_dict()
        orig = data.get("originalId")
        if orig is not None:
            result[int(orig)] = {
                "doc_id": doc.id,
                "totalCount": data.get("totalCount", 0) or 0,
                "name": data.get("rav", ""),
            }
    return result


@pytest.fixture(scope="session")
def all_firestore_categories(fs):
    result = {}
    for doc in fs.db.collection("categories").stream():
        data = doc.to_dict()
        orig = data.get("originalId")
        if orig is not None:
            result[int(orig)] = {
                "doc_id": doc.id,
                "totalCount": data.get("totalCount", 0) or 0,
                "name": data.get("category", ""),
            }
    return result


@pytest.fixture(scope="session")
def all_firestore_series(fs):
    result = {}
    for doc in fs.db.collection("series").stream():
        data = doc.to_dict()
        orig = data.get("originalId")
        if orig is not None:
            result[int(orig)] = {
                "doc_id": doc.id,
                "totalCount": data.get("totalCount", 0) or 0,
                "name": data.get("serie", ""),
            }
    return result


@pytest.fixture(scope="session")
def all_firestore_sources(fs):
    result = {}
    for doc in fs.db.collection("sources").stream():
        data = doc.to_dict()
        orig = data.get("originalId")
        if orig is not None:
            result[int(orig)] = {
                "doc_id": doc.id,
                "totalCount": data.get("totalCount", 0) or 0,
                "label": data.get("label", ""),
            }
    return result
