"""Phase 3b: Cluster same-story coverage.

Groups articles about the same event/announcement using:
- Cosine similarity >= 0.86 (from embeddings)
- At least 1 shared entity
- Within 72-hour window

The highest-scored item becomes canonical; others become "More coverage".

    python -m agent.cluster              # cluster recent items
    python -m agent.cluster --dry-run    # show clusters without DB writes
    python -m agent.cluster --limit 100  # only process 100 items
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

from .config import CLUSTER_COSINE, CLUSTER_WINDOW_HOURS


@dataclass
class Cluster:
    canonical_id: int
    canonical_score: int
    canonical_url: str
    member_ids: list[int] = field(default_factory=list)
    member_urls: list[str] = field(default_factory=list)


def get_clusterable_items(conn, limit: int | None = None) -> list[dict]:
    """Get scored items from recent window that aren't clustered yet."""
    with conn.cursor() as cur:
        query = f"""
            SELECT m.id, m.headline, m.source_url, m.score, m.entities,
                   m.embedding, m.published_at
            FROM news_memory m
            WHERE m.score IS NOT NULL
              AND m.cluster_id IS NULL
              AND m.published_at > now() - interval '{CLUSTER_WINDOW_HOURS} hours'
            ORDER BY m.score DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        return cur.fetchall()


def compute_cosine_similarity_batch(items: list[dict]) -> dict[tuple[int, int], float]:
    """Precompute cosine similarities for all item pairs in Python."""
    import numpy as np
    
    # Build embedding matrix
    ids = [item["id"] for item in items]
    embeddings = []
    for item in items:
        emb = item["embedding"]
        if emb is None:
            embeddings.append(np.zeros(384))
        elif isinstance(emb, (list, tuple)):
            embeddings.append(np.array(emb))
        else:
            # pgvector returns text like '[0.1,0.2,...]', which is valid JSON
            embeddings.append(np.array(json.loads(str(emb))))
    
    embeddings = np.array(embeddings)
    
    # Normalize for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1  # avoid division by zero
    normalized = embeddings / norms
    
    # Compute all pairwise similarities at once
    similarity_matrix = normalized @ normalized.T
    
    # Build lookup dict
    similarities = {}
    for i, id1 in enumerate(ids):
        for j, id2 in enumerate(ids):
            if i < j:
                similarities[(id1, id2)] = float(similarity_matrix[i, j])
    
    return similarities


def has_shared_entity(entities1: list[str], entities2: list[str]) -> bool:
    """Check if two items share at least one entity."""
    if not entities1 or not entities2:
        return False
    set1 = {e.lower() for e in entities1}
    set2 = {e.lower() for e in entities2}
    return bool(set1 & set2)


def find_clusters(items: list[dict], similarities: dict[tuple[int, int], float]) -> list[Cluster]:
    """Find clusters among items using precomputed similarities + shared entities."""
    if not items:
        return []
    
    # Track which items are already assigned
    assigned = set()
    clusters = []
    
    # Items are sorted by score DESC, so first item in cluster is canonical
    for i, item in enumerate(items):
        if item["id"] in assigned:
            continue
        
        cluster = Cluster(
            canonical_id=item["id"],
            canonical_score=item["score"],
            canonical_url=item["source_url"],
        )
        assigned.add(item["id"])
        
        # Find similar items
        for j, other in enumerate(items[i + 1:], start=i + 1):
            if other["id"] in assigned:
                continue
            
            # Check cosine similarity (lookup precomputed)
            key = (min(item["id"], other["id"]), max(item["id"], other["id"]))
            similarity = similarities.get(key, 0.0)
            if similarity < CLUSTER_COSINE:
                continue
            
            # Check shared entity
            if not has_shared_entity(item["entities"], other["entities"]):
                continue
            
            # Add to cluster
            cluster.member_ids.append(other["id"])
            cluster.member_urls.append(other["source_url"])
            assigned.add(other["id"])
        
        # Only save clusters with multiple items
        if cluster.member_ids:
            clusters.append(cluster)
    
    return clusters


def save_clusters(conn, clusters: list[Cluster]) -> int:
    """Save clusters to DB and update news_memory."""
    saved = 0
    
    with conn.cursor() as cur:
        for cluster in clusters:
            # Insert cluster
            cur.execute(
                """
                INSERT INTO clusters (canonical_item_id, member_urls)
                VALUES (%s, %s)
                RETURNING id
                """,
                (cluster.canonical_id, cluster.member_urls),
            )
            cluster_id = cur.fetchone()["id"]
            
            # Update canonical item
            cur.execute(
                "UPDATE news_memory SET cluster_id = %s WHERE id = %s",
                (cluster_id, cluster.canonical_id),
            )
            
            # Update member items
            for member_id in cluster.member_ids:
                cur.execute(
                    "UPDATE news_memory SET cluster_id = %s WHERE id = %s",
                    (cluster_id, member_id),
                )
            
            saved += 1
    
    return saved


def run(dry_run: bool = False, limit: int | None = None) -> int:
    """Main entry point."""
    from . import db

    with db.connect() as conn:
        items = get_clusterable_items(conn, limit)
        if not items:
            print("cluster: no items to cluster")
            return 0

        print(f"cluster: analyzing {len(items)} items...")

        # Precompute all similarities in Python (much faster than N² DB queries)
        print("cluster: computing similarities...")
        similarities = compute_cosine_similarity_batch(items)
        
        clusters = find_clusters(items, similarities)

        if dry_run:
            print(f"\n{'=' * 60}")
            print("  DRY RUN - clusters found (not saved)")
            print(f"{'=' * 60}\n")
            print(f"  Threshold: cosine >= {CLUSTER_COSINE}, window = {CLUSTER_WINDOW_HOURS}h\n")
            
            for c in clusters:
                print(f"  Cluster (score={c.canonical_score}):")
                print(f"    canonical: {c.canonical_url[:60] if c.canonical_url else 'N/A'}")
                for url in c.member_urls[:3]:
                    print(f"    + {url[:60] if url else 'N/A'}")
                if len(c.member_urls) > 3:
                    print(f"    + ... and {len(c.member_urls) - 3} more")
                print()
            
            print(f"  Total: {len(clusters)} clusters, {sum(len(c.member_ids) for c in clusters)} items grouped")
            return 0

        saved = save_clusters(conn, clusters)
        total_grouped = sum(len(c.member_ids) for c in clusters)
        
        print(f"cluster: {saved} clusters created, {total_grouped} items grouped")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Cluster same-story coverage.")
    ap.add_argument("--dry-run", action="store_true", help="show clusters without saving")
    ap.add_argument("--limit", type=int, help="only process N items")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
