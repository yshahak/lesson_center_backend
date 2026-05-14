# Script Reference

All scripts run from the `lesson_center_backend/` directory.
All require Firebase credentials: `gcloud auth application-default login`

---

## ⚠️ CORRECT ORDER OF OPERATIONS

Run these in order. Each step depends on the previous one being complete.

```
1. sync_lessons_from_postgres.py    # Get all PostgreSQL lessons into Firestore
2. fix_lesson_references.py         # Set ravId/categoryId/seriesId on all lessons
3. audit_data_gaps.py               # Verify counts are accurate
4. pytest scripts/tests/            # All 16 green = ready for production
```

**Why this order matters**: `fix_lesson_references.py` only updates *existing* Firestore
documents. If a lesson doesn't exist yet, the fix silently skips it. Always migrate first.

---

## Data Migration Scripts

### `scripts/sync_lessons_from_postgres.py` ← START HERE
**Purpose**: Sync ALL PostgreSQL lessons to Firestore. This is the primary migration
script. Safe to re-run — uses `set(merge=True)` so existing docs are not overwritten.
Also resolves ravId/categoryId/seriesId to Firestore doc IDs during upload.

**When to use**: First time setup, or whenever new lessons have been added to
PostgreSQL that aren't in Firestore yet.

```bash
# Full sync (all 107K lessons, ~18 min):
python scripts/sync_lessons_from_postgres.py

# Incremental sync (only new lessons since date, faster):
python scripts/sync_lessons_from_postgres.py --since 2025-12-30

# Dry run first to check counts:
python scripts/sync_lessons_from_postgres.py --dry-run

# Resume after interruption:
python scripts/sync_lessons_from_postgres.py --start 50000
```

---

### `scripts/upload_to_firestore_batch.py`
**Purpose**: Upload lessons from a JSON file to Firestore in batches.
**When to use**: When you need to sync new/missing lessons from PostgreSQL to Firestore.
**Input**: A JSON file in `firestore_data/` format.
**Usage**:
```bash
python scripts/upload_to_firestore_batch.py
```

---

### `scripts/fix_lesson_references.py`
**Purpose**: Fix `ravId`, `categoryId`, `seriesId` fields in Firestore lesson documents.
After batch migration, these fields are null. This script maps PostgreSQL integer IDs
to the correct Firestore document IDs.

**⚠️ Known bug (fixed May 2026)**: Never convert lesson IDs through `float()` —
18-digit integers lose precision. Always use `row["id"].strip()` directly.

**Input required**: A CSV export from PostgreSQL (see instructions inside the script).

**The correct SQL export** (run on AWS server via SSH):
```bash
ssh -i ~/.ssh/id_rsa_mac_m1 bitnami@3.70.156.78
sudo -u postgres psql -d lessons -c "COPY (
  SELECT l.id AS original_id, r.\"originalId\" AS rav_original_id
  FROM lessons l
  JOIN ravs r ON l.\"ravId\" = r.id
  WHERE l.\"ravId\" IS NOT NULL
) TO '/tmp/lesson_refs_rav.csv' WITH CSV HEADER;"
exit
scp -i ~/.ssh/id_rsa_mac_m1 bitnami@3.70.156.78:/tmp/lesson_refs_rav.csv data/lesson_refs_rav.csv
```

**Usage**:
```bash
python scripts/fix_lesson_references.py --input data/lesson_refs_rav.csv --field rav --dry-run
python scripts/fix_lesson_references.py --input data/lesson_refs_rav.csv --field rav
# If interrupted, resume with: --start N (skip first N rows)
```

---

### `scripts/populate_total_counts.py`
**Purpose**: Pre-calculate lesson counts per source/rav/category/series to avoid
expensive Firestore quota usage on startup.
**When to use**: After any batch migration or reference field fix.
```bash
python scripts/populate_total_counts.py
```

---

## Cleanup Scripts

### `scripts/cleanup_duplicate_labels.py`
**Purpose**: Remove duplicate label documents from Firestore. Multiple migration runs
create many docs with the same label name but empty `lessonIds`. Keeps the doc with
the most lesson IDs.
**When to use**: If label counts show 0 after migration.
```bash
python scripts/cleanup_duplicate_labels.py --dry-run
python scripts/cleanup_duplicate_labels.py
```

---

### `scripts/cleanup_old_format_lessons.py`
**Purpose**: Delete old-format Firestore lesson documents (doc ID = small integer `originalId`).
The 2024 migration stored lesson docs with `originalId` as the key and PostgreSQL bigint FKs
for ravId/categoryId/seriesId — making them invisible to rav/category/series queries.
New-format docs (from `sync_lessons_from_postgres.py`) use the bigint `id` as the key
with correct Firestore string doc IDs for references.
Safe to run — all old-format docs have new-format counterparts.
```bash
python scripts/cleanup_old_format_lessons.py --dry-run
python scripts/cleanup_old_format_lessons.py
```

---

### `scripts/cleanup_duplicate_docs.py`
**Purpose**: Remove duplicate documents from any collection (ravs, sources, categories,
series). Groups by `originalId`, keeps the doc with the highest `totalCount`.
**When to use**: If a collection has more docs than expected unique entities.
```bash
python scripts/cleanup_duplicate_docs.py --collection ravs --dry-run
python scripts/cleanup_duplicate_docs.py --collection sources
python scripts/cleanup_duplicate_docs.py --collection categories
python scripts/cleanup_duplicate_docs.py --collection series
```

---

### `scripts/populate_label_lessons.py`
**Purpose**: Fill empty label `lessonIds` arrays with recent lessons from Firestore.
Matches each label to a source by name or `sourceId`, queries most recent lessons.
**When to use**: After labels collection is cleaned up and lessonIds are still empty.
```bash
python scripts/populate_label_lessons.py --dry-run
python scripts/populate_label_lessons.py --lessons-per-label 10
```

---

## Audit / Diagnostic Scripts

### `scripts/audit_data_gaps.py`
**Purpose**: Compare `totalCount` metadata vs actual queryable lesson count for every
rav, category, and series. Uses Firestore `count()` aggregation (cheap, no doc reads).
Outputs a CSV report showing every entity with its real vs claimed count.
**When to use**: After any data fix, to verify counts are accurate.
**Cost**: ~$0.21 for a full run (3500 aggregation queries).
```bash
python scripts/audit_data_gaps.py --output data/gaps_report.csv
python scripts/audit_data_gaps.py --collection ravs --min-gap 100
```

---

## Integration Tests

### `scripts/tests/`
**Purpose**: Validate Firestore data against PostgreSQL (source of truth).
**Run**:
```bash
pip install pytest psycopg2-binary  # first time only
python -m pytest scripts/tests/ -v --tb=short
```

**What each test file checks**:

| File | What it validates |
|---|---|
| `test_lesson_sync.py` | Lessons in PostgreSQL exist in Firestore; most recent are synced; rav 4014 regression |
| `test_references.py` | ravId/categoryId/seriesId in Firestore matches PostgreSQL; no orphaned Firestore ravs |
| `test_counts.py` | totalCount in Firestore equals actual queryable count; no hidden lessons |
| `test_labels.py` | Label lessonIds all exist; no duplicates; no empty labels |
| `test_data_quality.py` | Required fields; valid timestamps/durations; media URLs present; source integrity; migration staleness detector |
| `test_cross_references.py` | ravId/categoryId/seriesId point to existing docs; source matches rav/category source |
| `test_format_consistency.py` | No old-format docs; reference fields are strings not integers; source totalCounts |
| `test_sources_integrity.py` | All sources exist in both PG and Firestore; source lesson counts match |
| `test_app_queries.py` | Exact app queries work: source/rav/category/label + pagination cursor |

**Target**: all 16 tests green = Firestore is ready for production switch.

**As of May 13, 2026**: 10/16 pass. Failures are due to:
- ravId fix float precision bug (see fix_lesson_references.py notes)
- ~7.5% of lessons not yet synced to Firestore (migration is stale)

---

## Typical Workflow After Returning to This Project

1. **Check what's broken**: `python -m pytest scripts/tests/ -v --tb=line`
2. **If ravId tests fail**: re-export CSV from PostgreSQL and re-run `fix_lesson_references.py`
3. **If lesson sync tests fail**: run batch migration for new lessons
4. **After any fix**: re-run `audit_data_gaps.py` and update totalCounts
5. **When all 16 tests pass**: proceed to Phase C (switch production app to Firestore)

---

## PostgreSQL Notes (AWS Server)

- SSH: `ssh -i ~/.ssh/id_rsa_mac_m1 bitnami@3.70.156.78`
- Connect: `sudo -u postgres psql -d lessons` (no password)
- Column names are case-sensitive: `"ravId"`, `"originalId"`, `"sourceId"` (with quotes)
- `lessons.id` = bigint hash (18 digits) = Firestore document ID
- `lessons."originalId"` = small integer (separate field, NOT the Firestore doc ID)
- `ravs.id` = bigint hash. `ravs."originalId"` = small integer used in Firestore
- `psql --csv` requires PG12+. Server is PG11. Use `COPY (...) TO STDOUT WITH CSV HEADER`
