"""Phase 2b: Generate embeddings.

Uses fastembed with BAAI/bge-small-en-v1.5 (384-dim, 67MB, MIT license).
Embeddings enable semantic search, clustering, and thread detection.

    python -m agent.embed                # embed items missing vectors
    python -m agent.embed --dry-run      # test embedding without DB
    python -m agent.embed --limit 50     # only process 50 items
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from .config import EMBED_MODEL, EMBED_DIM

if TYPE_CHECKING:
    from fastembed import TextEmbedding

# Lazy-loaded model (67MB download on first use)
_model: TextEmbedding | None = None


def get_model() -> TextEmbedding:
    """Lazy-load the embedding model."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=EMBED_MODEL)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts.
    
    Returns list of 384-dim vectors.
    """
    model = get_model()
    # fastembed returns a generator, convert to list
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]


def embed_one(text: str) -> list[float]:
    """Generate embedding for a single text."""
    return embed_texts([text])[0]


def prepare_text(title: str, article_text: str | None, feed_summary: str | None) -> str:
    """Combine title + content for embedding.
    
    Priority: title + article_text, fallback to title + feed_summary.
    Truncate to ~8000 chars (model context limit is ~512 tokens).
    """
    content = article_text or feed_summary or ""
    # Title is most important, weight it by including twice
    combined = f"{title}\n\n{title}\n\n{content}"
    return combined[:8000]


def get_unembedded_items(conn, limit: int | None = None) -> list[dict]:
    """Get items that have text but no embedding yet."""
    with conn.cursor() as cur:
        query = """
            SELECT r.id, r.url_canonical, r.title, r.article_text, r.feed_summary
            FROM raw_items r
            LEFT JOIN news_memory m ON r.id = m.id
            WHERE m.id IS NULL
              AND r.rules_pass IS TRUE
              AND (r.article_text IS NOT NULL OR r.feed_summary IS NOT NULL)
            ORDER BY r.published_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        return cur.fetchall()


def insert_embeddings(conn, items: list[dict], embeddings: list[list[float]]) -> int:
    """Insert items with embeddings into news_memory.
    
    This is a minimal insert - score, entities, topics filled by later phases.
    """
    inserted = 0
    with conn.cursor() as cur:
        for item, embedding in zip(items, embeddings):
            # Verify embedding dimension
            if len(embedding) != EMBED_DIM:
                continue
            
            cur.execute(
                """
                INSERT INTO news_memory 
                    (id, headline, one_liner, source_url, source_name, 
                     published_at, embedding)
                SELECT 
                    r.id, r.title, COALESCE(LEFT(r.feed_summary, 200), ''),
                    r.url_canonical, s.name, r.published_at, %s::vector
                FROM raw_items r
                JOIN sources s ON r.source_id = s.id
                WHERE r.id = %s
                ON CONFLICT (id) DO NOTHING
                """,
                (embedding, item["id"]),
            )
            inserted += cur.rowcount
    return inserted


BATCH_SIZE = 50  # Process in batches to avoid connection timeout


def run(dry_run: bool = False, limit: int | None = None) -> int:
    """Main entry point."""
    if dry_run:
        print(f"\n{'=' * 60}")
        print("  DRY RUN - testing embedding model")
        print(f"{'=' * 60}\n")

        sample_texts = [
            "OpenAI announces GPT-5 with improved reasoning capabilities",
            "MIT researchers develop new quantum computing architecture",
            "Google DeepMind achieves breakthrough in protein folding",
        ]

        print(f"  Model: {EMBED_MODEL}")
        print(f"  Dimension: {EMBED_DIM}\n")
        print("  Loading model (first run downloads 67MB)...")
        
        embeddings = embed_texts(sample_texts)
        
        for text, emb in zip(sample_texts, embeddings):
            print(f"  ✓ [{len(emb)}d] {text[:50]}...")
            print(f"            first 5 dims: {emb[:5]}\n")

        # Test similarity (should be high for similar topics)
        from math import sqrt
        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sqrt(sum(x * x for x in a))
            norm_b = sqrt(sum(x * x for x in b))
            return dot / (norm_a * norm_b)

        sim_01 = cosine(embeddings[0], embeddings[1])
        sim_02 = cosine(embeddings[0], embeddings[2])
        print(f"  Cosine similarity (0,1): {sim_01:.3f}")
        print(f"  Cosine similarity (0,2): {sim_02:.3f}")
        
        return 0

    from . import db

    # Get items with fresh connection
    with db.connect() as conn:
        items = get_unembedded_items(conn, limit)
    
    if not items:
        print("embed: no items need embedding")
        return 0

    print(f"embed: processing {len(items)} items in batches of {BATCH_SIZE}...")
    
    # Pre-load model before batching
    get_model()
    
    total_inserted = 0
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
        
        # Prepare texts for embedding
        texts = [
            prepare_text(item["title"], item["article_text"], item["feed_summary"])
            for item in batch
        ]

        # Embed (CPU-bound, no DB connection needed)
        embeddings = embed_texts(texts)

        # Insert with fresh connection per batch
        with db.connect() as conn:
            inserted = insert_embeddings(conn, batch, embeddings)
            total_inserted += inserted
        
        print(f"  batch {batch_num}/{total_batches}: {inserted} embedded")

    print(f"embed: {total_inserted} items embedded and inserted into news_memory")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate embeddings for news items.")
    ap.add_argument("--dry-run", action="store_true", help="test embedding without DB")
    ap.add_argument("--limit", type=int, help="only process N items")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
