#!/usr/bin/env python3
"""
Embed lessons into Firestore using Vertex AI.

Each lesson gets an `embedding` field built from:
  title | rav name | series name | category name

Usage:
  python scripts/embed_lessons.py --limit 2500                         # embed next 2500 unembedded
  python scripts/embed_lessons.py --source-id 1 --force                # re-embed source 1
  python scripts/embed_lessons.py --source-id 2 --force --has-taxonomy # only lessons with ravId set
  python scripts/embed_lessons.py                                       # full run (165K docs)
  python scripts/embed_lessons.py --dry-run --limit 10                  # preview embedding text

Requires:
  gcloud auth application-default login
  pip install google-cloud-aiplatform>=1.38.0 firebase-admin google-cloud-firestore>=2.19.0
"""

import argparse
import re
import sys
import time

import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore_v1.vector import Vector

NIKUD_RE = re.compile(r'[ְ-ׇ]')
PROJECT_ID = 'tora-or'
REGION = 'us-central1'
EMBEDDING_MODEL = 'text-multilingual-embedding-002'

EMBED_BATCH_SIZE = 50
WRITE_BATCH_SIZE = 400


def normalize(text: str) -> str:
    return NIKUD_RE.sub('', text or '').strip()


def build_embedding_text(data: dict, ravs: dict, series: dict, categories: dict) -> str:
    """Concatenate title + rav + series + category for richer semantic search."""
    parts = []

    if title := normalize(data.get('title') or ''):
        parts.append(title)

    if rav_id := data.get('ravId'):
        if rav := ravs.get(rav_id):
            if name := normalize(rav.get('rav') or ''):
                parts.append(name)

    if series_id := data.get('seriesId'):
        if s := series.get(series_id):
            if name := normalize(s.get('serie') or ''):
                parts.append(name)

    if cat_id := data.get('categoryId'):
        if c := categories.get(cat_id):
            if name := normalize(c.get('category') or ''):
                parts.append(name)

    return ' | '.join(parts)


def embed_texts(model, texts: list[str]) -> list[list[float]]:
    return [r.values for r in model.get_embeddings(texts)]


def run(source_id: int | None, limit: int | None, dry_run: bool, force: bool, has_taxonomy: bool = False):
    import vertexai
    from vertexai.language_models import TextEmbeddingModel

    print(f"Initializing Firebase (project={PROJECT_ID})...")
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={'projectId': PROJECT_ID})
    db = firestore.client()

    print("Loading lookup maps (ravs, series, categories)...")
    ravs = {d.id: d.to_dict() for d in db.collection('ravs').stream()}
    series = {d.id: d.to_dict() for d in db.collection('series').stream()}
    categories = {d.id: d.to_dict() for d in db.collection('categories').stream()}
    print(f"  {len(ravs)} ravs, {len(series)} series, {len(categories)} categories")

    print(f"Initializing Vertex AI ({REGION})...")
    vertexai.init(project=PROJECT_ID, location=REGION)
    model = TextEmbeddingModel.from_pretrained(EMBEDDING_MODEL)

    query = db.collection('lessons')
    if source_id is not None:
        query = query.where('sourceId', '==', source_id)
        print(f"Filtering: sourceId={source_id}")
    if limit:
        query = query.limit(limit)
        print(f"Limit: {limit}")

    # Stream in pages to avoid Firestore query timeouts on large collections
    print("Streaming lessons from Firestore (paginated)...")
    PAGE_SIZE = 5000
    docs = []
    last_doc = None
    while True:
        page_query = query.limit(PAGE_SIZE) if not limit else query
        if last_doc:
            page_query = page_query.start_after(last_doc)
        page = list(page_query.stream())
        docs.extend(page)
        print(f"  fetched {len(docs)} so far...")
        if len(page) < PAGE_SIZE or (limit and len(docs) >= limit):
            break
        last_doc = page[-1]
    if limit:
        docs = docs[:limit]
    print(f"Found {len(docs)} lessons")

    if force:
        to_process = docs
        print(f"Force mode: re-embedding all {len(to_process)} docs")
    else:
        to_process = [d for d in docs if 'embedding' not in (d.to_dict() or {})]
        skipped = len(docs) - len(to_process)
        if skipped:
            print(f"Skipping {skipped} already-embedded docs (use --force to re-embed)")
        print(f"Embedding {len(to_process)} docs")

    if has_taxonomy:
        # Filter in-memory: only lessons with ravId set.
        # These are the only ones whose embedding text improves vs title-only.
        before = len(to_process)
        to_process = [d for d in to_process if (d.to_dict() or {}).get('ravId')]
        print(f"--has-taxonomy: filtered {before - len(to_process)} all-null lessons → {len(to_process)} to embed")

    if dry_run:
        print("\n[DRY RUN] Embedding text samples:")
        for doc in to_process[:10]:
            text = build_embedding_text(doc.to_dict() or {}, ravs, series, categories)
            print(f"  [{doc.id}] {text[:100]}")
        if len(to_process) > 10:
            print(f"  ... and {len(to_process) - 10} more")
        return

    embedded = 0
    errors = 0
    empty_skipped = 0
    start = time.time()
    write_batch = db.batch()
    write_count = 0

    for i in range(0, len(to_process), EMBED_BATCH_SIZE):
        chunk = to_process[i:i + EMBED_BATCH_SIZE]

        # Build rich embedding texts; skip docs with nothing to embed
        valid = []
        for doc in chunk:
            text = build_embedding_text(doc.to_dict() or {}, ravs, series, categories)
            if text:
                valid.append((doc, text))
            else:
                empty_skipped += 1

        if not valid:
            continue

        docs_to_write, texts = zip(*valid)

        try:
            vectors = embed_texts(model, list(texts))
        except Exception as e:
            print(f"  ⚠ Embedding error at batch {i}: {e}", file=sys.stderr)
            errors += len(valid)
            time.sleep(2)
            continue

        for doc, vec in zip(docs_to_write, vectors):
            write_batch.update(doc.reference, {'embedding': Vector(vec)})
            write_count += 1
            embedded += 1

            if write_count >= WRITE_BATCH_SIZE:
                write_batch.commit()
                write_count = 0
                write_batch = db.batch()

        elapsed = time.time() - start
        rate = embedded / elapsed if elapsed > 0 else 0
        eta = (len(to_process) - embedded) / rate if rate > 0 else 0
        print(f"  Progress: {embedded}/{len(to_process)} ({rate:.0f}/s, ETA {eta:.0f}s)")

    if write_count > 0:
        write_batch.commit()

    elapsed = time.time() - start
    print(f"\n✅ Done: {embedded} embedded, {empty_skipped} empty-skipped, {errors} errors, {elapsed:.0f}s")


def main():
    parser = argparse.ArgumentParser(description='Embed lessons into Firestore')
    parser.add_argument('--source-id', type=int)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--force', action='store_true', help='Re-embed already-embedded docs')
    parser.add_argument('--has-taxonomy', action='store_true', help='Only lessons with ravId set (skips all-null taxonomy lessons)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    run(source_id=args.source_id, limit=args.limit, dry_run=args.dry_run, force=args.force, has_taxonomy=args.has_taxonomy)


if __name__ == '__main__':
    main()
