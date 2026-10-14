"""Phase 5: Thread detection.

Groups related stories across weeks into threads (ongoing narratives).
Uses pgvector similarity + shared entities to find connections.

Examples of threads:
- "GPT-5 development" (announcement → benchmarks → reactions → updates)
- "EU AI Act" (proposal → amendments → vote → implementation)

    python -m agent.threads              # detect threads
    python -m agent.threads --dry-run    # show threads without saving
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field


@dataclass
class Thread:
    id: int | None
    label: str
    item_ids: list[int] = field(default_factory=list)
    entities: set[str] = field(default_factory=set)


def get_recent_items(conn, days: int = 30) -> list[dict]:
    """Get scored items from recent period for thread detection."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.id, m.headline, m.source_url, m.entities, m.topics,
                   m.published_at, m.thread_id, m.embedding
            FROM news_memory m
            WHERE m.score IS NOT NULL
              AND m.published_at > now() - interval '%s days'
            ORDER BY m.published_at DESC
        """, (days,))
        return cur.fetchall()


def get_existing_threads(conn) -> list[Thread]:
    """Get existing threads."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.id, t.label, array_agg(m.id) as item_ids,
                   array_agg(DISTINCT unnest_entity) as entities
            FROM threads t
            JOIN news_memory m ON m.thread_id = t.id
            CROSS JOIN LATERAL unnest(m.entities) as unnest_entity
            GROUP BY t.id, t.label
        """)
        threads = []
        for row in cur.fetchall():
            threads.append(Thread(
                id=row["id"],
                label=row["label"],
                item_ids=row["item_ids"] or [],
                entities=set(row["entities"] or []),
            ))
        return threads


def find_similar_items(conn, item_id: int, threshold: float = 0.75, limit: int = 10) -> list[dict]:
    """Find items similar to given item using pgvector."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m2.id, m2.headline, m2.entities,
                   1 - (m1.embedding <=> m2.embedding) as similarity
            FROM news_memory m1, news_memory m2
            WHERE m1.id = %s
              AND m2.id != m1.id
              AND m2.score IS NOT NULL
              AND 1 - (m1.embedding <=> m2.embedding) >= %s
            ORDER BY m1.embedding <=> m2.embedding
            LIMIT %s
        """, (item_id, threshold, limit))
        return cur.fetchall()


def find_thread_for_item(item: dict, threads: list[Thread], conn) -> Thread | None:
    """Find existing thread that matches this item."""
    item_entities = set(e.lower() for e in (item["entities"] or []))
    
    for thread in threads:
        thread_entities = set(e.lower() for e in thread.entities)
        
        # Need at least 2 shared entities to join existing thread
        shared = item_entities & thread_entities
        if len(shared) >= 2:
            return thread
    
    return None


def create_thread_label(items: list[dict]) -> str:
    """Generate a label for a new thread based on common entities/topics."""
    # Collect all entities
    all_entities = []
    for item in items:
        all_entities.extend(item.get("entities") or [])
    
    # Find most common
    from collections import Counter
    common = Counter(all_entities).most_common(2)
    
    if common:
        return " + ".join(e for e, _ in common)
    
    # Fallback to first headline keywords
    return items[0]["headline"][:40] + "..."


def detect_new_threads(conn, items: list[dict], existing_threads: list[Thread], 
                       min_items: int = 3) -> list[Thread]:
    """Detect new threads from unthreaded items."""
    # Get items not in any thread
    threaded_ids = set()
    for t in existing_threads:
        threaded_ids.update(t.item_ids)
    
    unthreaded = [i for i in items if i["id"] not in threaded_ids and not i["thread_id"]]
    
    if len(unthreaded) < min_items:
        return []
    
    new_threads = []
    processed = set()
    
    for item in unthreaded:
        if item["id"] in processed:
            continue
        
        # Find similar items
        similar = find_similar_items(conn, item["id"], threshold=0.72, limit=20)
        
        # Filter to unthreaded items with shared entities
        item_entities = set(e.lower() for e in (item["entities"] or []))
        cluster = [item]
        
        for sim in similar:
            if sim["id"] in processed or sim["id"] in threaded_ids:
                continue
            
            sim_entities = set(e.lower() for e in (sim["entities"] or []))
            if item_entities & sim_entities:  # At least 1 shared entity
                cluster.append(sim)
                processed.add(sim["id"])
        
        # Need minimum items to form a thread
        if len(cluster) >= min_items:
            thread = Thread(
                id=None,
                label=create_thread_label(cluster),
                item_ids=[i["id"] for i in cluster],
                entities=item_entities,
            )
            new_threads.append(thread)
        
        processed.add(item["id"])
    
    return new_threads


def save_threads(conn, threads: list[Thread]) -> int:
    """Save new threads and update item references."""
    saved = 0
    
    with conn.cursor() as cur:
        for thread in threads:
            if thread.id is None:
                # Create new thread
                cur.execute(
                    """
                    INSERT INTO threads (label, first_seen, last_seen, part_count)
                    SELECT %s, MIN(published_at), MAX(published_at), %s
                    FROM news_memory WHERE id = ANY(%s)
                    RETURNING id
                    """,
                    (thread.label, len(thread.item_ids), thread.item_ids),
                )
                thread.id = cur.fetchone()["id"]
                saved += 1
            
            # Update items
            cur.execute(
                "UPDATE news_memory SET thread_id = %s WHERE id = ANY(%s)",
                (thread.id, thread.item_ids),
            )
            
            # Update thread stats
            cur.execute(
                """
                UPDATE threads SET
                    last_seen = (SELECT MAX(published_at) FROM news_memory WHERE thread_id = %s),
                    part_count = (SELECT COUNT(*) FROM news_memory WHERE thread_id = %s)
                WHERE id = %s
                """,
                (thread.id, thread.id, thread.id),
            )
    
    return saved


def update_thread_assignments(conn, items: list[dict], threads: list[Thread]) -> int:
    """Assign unthreaded items to existing threads."""
    assigned = 0
    
    with conn.cursor() as cur:
        for item in items:
            if item["thread_id"]:
                continue
            
            thread = find_thread_for_item(item, threads, conn)
            if thread and thread.id:
                cur.execute(
                    "UPDATE news_memory SET thread_id = %s WHERE id = %s",
                    (thread.id, item["id"]),
                )
                thread.item_ids.append(item["id"])
                assigned += 1
    
    return assigned


def run(dry_run: bool = False) -> int:
    """Main entry point."""
    from . import db

    with db.connect() as conn:
        items = get_recent_items(conn, days=30)
        if not items:
            print("threads: no items to process")
            return 0

        existing = get_existing_threads(conn)
        print(f"threads: {len(items)} items, {len(existing)} existing threads")

        # Detect new threads
        new_threads = detect_new_threads(conn, items, existing)
        
        if dry_run:
            print(f"\n{'=' * 60}")
            print("  DRY RUN - thread detection")
            print(f"{'=' * 60}\n")
            
            print(f"  Existing threads: {len(existing)}")
            for t in existing[:5]:
                print(f"    [{len(t.item_ids)} items] {t.label}")
            
            print(f"\n  New threads detected: {len(new_threads)}")
            for t in new_threads:
                print(f"    [{len(t.item_ids)} items] {t.label}")
                for iid in t.item_ids[:3]:
                    item = next((i for i in items if i["id"] == iid), None)
                    if item:
                        print(f"      - {item['headline'][:50]}")
            
            return 0

        # Save new threads
        saved = save_threads(conn, new_threads)
        
        # Assign items to existing threads
        all_threads = existing + new_threads
        assigned = update_thread_assignments(conn, items, all_threads)

        print(f"threads: {saved} new threads, {assigned} items assigned to existing")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect story threads.")
    ap.add_argument("--dry-run", action="store_true", help="show threads without saving")
    args = ap.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
