"""Phase 4: Publish to Notion.

Creates/updates:
- Weeks database: one page per digest week
- News Items database: top stories with scores, entities, clusters
- Links clusters as "More coverage" toggles

Runs Friday 12:01 IST via GitHub Actions.

    python -m agent.publish              # publish current week
    python -m agent.publish --dry-run    # show what would be published
"""

from __future__ import annotations

import argparse
from datetime import datetime

from notion_client import Client

from . import notion as notion_api
from .config import (
    env, week_window, IST,
    SCORE_MAJOR, SCORE_NOTABLE,
    MAX_ITEMS_PER_DIGEST, MAX_MINOR_ITEMS,
)


def get_week_items(conn, window) -> list[dict]:
    """Get scored items for the week, ordered by score."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.id, m.headline, m.one_liner, m.source_url, m.source_name,
                   m.published_at, m.score, m.score_breakdown, m.entities,
                   m.topics, m.market_impact, m.cluster_id,
                   c.member_urls
            FROM news_memory m
            LEFT JOIN clusters c ON m.cluster_id = c.id AND c.canonical_item_id = m.id
            WHERE m.published_at >= %s
              AND m.published_at < %s
              AND m.score IS NOT NULL
              AND m.score >= %s
            ORDER BY m.score DESC
        """, (window.start, window.end, SCORE_NOTABLE))
        return cur.fetchall()


def get_source_health(conn) -> dict:
    """Get source health stats for provenance footer."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE enabled) as total,
                COUNT(*) FILTER (WHERE enabled AND consecutive_failures = 0) as healthy,
                COUNT(*) FILTER (WHERE enabled AND consecutive_failures >= 3) as failing
            FROM sources
        """)
        return cur.fetchone()


def get_run_stats(conn, window) -> dict:
    """Get ingest run stats for the week."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) as runs,
                SUM(items_seen) as items_seen,
                SUM(items_new) as items_new
            FROM runs
            WHERE job = 'ingest'
              AND finished_at >= %s
              AND finished_at < %s
        """, (window.start, window.end))
        return cur.fetchone()


def create_week_page(notion: Client, window, items: list[dict], health: dict, stats: dict) -> str:
    """Create the Week page in Notion."""
    ds_weeks = env("NOTION_DS_WEEKS", required=True)
    
    major_count = sum(1 for i in items if i["score"] >= SCORE_MAJOR)
    
    # Build page content
    children = []
    
    # Summary block
    children.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"emoji": "📊"},
            "rich_text": [{"type": "text", "text": {
                "content": f"{len(items)} stories scored ≥{SCORE_NOTABLE} | {major_count} major (≥{SCORE_MAJOR})"
            }}],
        }
    })
    
    # Major stories section
    if major_count > 0:
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔥 Major Stories"}}]}
        })
        
        for item in items[:MAX_ITEMS_PER_DIGEST]:
            if item["score"] < SCORE_MAJOR:
                break
            children.append(_item_block(item))
    
    # Notable stories section (collapsed)
    notable = [i for i in items if SCORE_NOTABLE <= i["score"] < SCORE_MAJOR][:MAX_MINOR_ITEMS]
    if notable:
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📌 Also Notable"}}]}
        })
        children.append({
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "text": {"content": f"{len(notable)} more stories..."}}],
                "children": [_item_block(i) for i in notable],
            }
        })
    
    # Provenance footer
    children.append({
        "object": "block",
        "type": "divider",
        "divider": {}
    })
    children.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {
                "content": f"Sources: {health['healthy']}/{health['total']} healthy, {health['failing']} failing | "
                          f"Ingested: {stats['items_new'] or 0} new items from {stats['runs'] or 0} runs"
            }, "annotations": {"color": "gray"}}]
        }
    })
    
    # Create page
    response = notion.pages.create(
        parent={"database_id": ds_weeks},
        properties={
            "Name": {"title": [{"text": {"content": window.label}}]},
            "Status": {"select": {"name": "Published"}},
        },
        children=children,
    )
    
    return response["id"]


def _item_block(item: dict) -> dict:
    """Create a block for a single news item."""
    # Score badge
    score_emoji = "🔴" if item["score"] >= 85 else "🟠" if item["score"] >= 70 else "🟡"
    
    # Main content
    content = f"{score_emoji} [{item['score']}] {item['headline']}"
    
    block = {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": content[:100]}},
                {"type": "text", "text": {"content": f" — {item['source_name']}"}, 
                 "annotations": {"italic": True, "color": "gray"}},
            ],
            "children": []
        }
    }
    
    # Add one-liner
    if item["one_liner"]:
        block["bulleted_list_item"]["children"].append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": item["one_liner"][:200]}}]}
        })
    
    # Add link
    block["bulleted_list_item"]["children"].append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{
            "type": "text",
            "text": {"content": "Read →", "link": {"url": item["source_url"]}},
            "annotations": {"color": "blue"}
        }]}
    })
    
    # Add "More coverage" if clustered
    if item.get("member_urls"):
        coverage_text = " | ".join(url.split("/")[2][:20] for url in item["member_urls"][:3])
        block["bulleted_list_item"]["children"].append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{
                "type": "text",
                "text": {"content": f"More coverage: {coverage_text}"},
                "annotations": {"color": "gray", "italic": True}
            }]}
        })
    
    return block


def update_item_notion_ids(conn, items: list[dict], week_page_id: str) -> None:
    """Update news_memory with Notion page references."""
    with conn.cursor() as cur:
        for item in items:
            cur.execute(
                """
                UPDATE news_memory 
                SET notion_page_id = %s, notion_status = 'live', published_week = %s
                WHERE id = %s
                """,
                (week_page_id, datetime.now(IST).date(), item["id"]),
            )


def run(dry_run: bool = False) -> int:
    """Main entry point."""
    from . import db

    if not dry_run and not notion_api.is_configured():
        print("publish: Notion not configured (NOTION_TOKEN unset), skipping")
        return 0

    window = week_window()
    
    with db.connect() as conn:
        items = get_week_items(conn, window)
        health = get_source_health(conn)
        stats = get_run_stats(conn, window)

        if dry_run:
            print(f"\n{'=' * 60}")
            print(f"  DRY RUN - {window.label}")
            print(f"{'=' * 60}\n")
            
            print(f"  Sources: {health['healthy']}/{health['total']} healthy")
            print(f"  Ingest runs: {stats['runs'] or 0}, items: {stats['items_new'] or 0} new\n")
            
            major = [i for i in items if i["score"] >= SCORE_MAJOR]
            notable = [i for i in items if SCORE_NOTABLE <= i["score"] < SCORE_MAJOR]
            
            print(f"  Major stories (>={SCORE_MAJOR}): {len(major)}")
            for i in major[:MAX_ITEMS_PER_DIGEST]:
                cluster_mark = " [+cluster]" if i.get("member_urls") else ""
                print(f"    [{i['score']:3}] {i['headline'][:50]}{cluster_mark}")
            
            print(f"\n  Notable (>={SCORE_NOTABLE}): {len(notable)}")
            for i in notable[:5]:
                print(f"    [{i['score']:3}] {i['headline'][:50]}")
            if len(notable) > 5:
                print(f"    ... and {len(notable) - 5} more")
            
            return 0

        if not items:
            print(f"publish: no items for {window.label}")
            return 0

        print(f"publish: creating digest for {window.label}...")

        notion = notion_api.get_client()
        week_page_id = create_week_page(notion, window, items, health, stats)
        update_item_notion_ids(conn, items, week_page_id)

        major_count = sum(1 for i in items if i["score"] >= SCORE_MAJOR)
        print(f"publish: created {window.label} with {major_count} major, {len(items)} total")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish weekly digest to Notion.")
    ap.add_argument("--dry-run", action="store_true", help="show what would be published")
    args = ap.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
