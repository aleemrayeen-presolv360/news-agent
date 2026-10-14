"""Phase 6b: Saturday addendum for late-breaking news.

Covers the Friday 12:00 IST -> Saturday 00:00 IST gap that the main
digest misses. Appends to the existing week's Notion page.

Runs Saturday 08:00 IST via GitHub Actions.

    python -m agent.addendum             # process and publish addendum
    python -m agent.addendum --dry-run   # show what would be added
"""

from __future__ import annotations

import argparse

from notion_client import Client

from . import notion as notion_api
from .config import addendum_window, SCORE_NOTABLE


def get_addendum_items(conn, window) -> list[dict]:
    """Get items from the addendum window (Friday afternoon)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.id, m.headline, m.one_liner, m.source_url, m.source_name,
                   m.score, m.published_at
            FROM news_memory m
            WHERE m.published_at >= %s
              AND m.published_at < %s
              AND m.score IS NOT NULL
              AND m.score >= %s
              AND m.notion_page_id IS NULL
            ORDER BY m.score DESC
            LIMIT 5
        """, (window.start, window.end, SCORE_NOTABLE))
        return cur.fetchall()


def get_week_page_id(conn, window) -> str | None:
    """Get the Notion page ID for this week's digest."""
    with conn.cursor() as cur:
        # Find any item from this week that has a notion_page_id
        cur.execute("""
            SELECT DISTINCT notion_page_id
            FROM news_memory
            WHERE published_week = (
                SELECT published_week FROM news_memory
                WHERE published_at >= %s - interval '5 days'
                  AND published_at < %s
                  AND notion_page_id IS NOT NULL
                LIMIT 1
            )
            AND notion_page_id IS NOT NULL
            LIMIT 1
        """, (window.start, window.start))
        row = cur.fetchone()
        return row["notion_page_id"] if row else None


def append_to_week_page(notion: Client, page_id: str, items: list[dict], window) -> bool:
    """Append addendum section to existing week page."""
    children = [
        {
            "object": "block",
            "type": "divider",
            "divider": {}
        },
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {"content": "⚡ Late Breaking (Friday PM)"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"Added Saturday — covers {window.start:%H:%M} to {window.end:%H:%M} IST"},
                    "annotations": {"italic": True, "color": "gray"}
                }]
            }
        },
    ]
    
    for item in items:
        score_emoji = "🔴" if item["score"] >= 85 else "🟠" if item["score"] >= 70 else "🟡"
        
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"{score_emoji} [{item['score']}] {item['headline'][:80]}"}},
                    {"type": "text", "text": {"content": f" — {item['source_name']}"}, 
                     "annotations": {"italic": True, "color": "gray"}},
                ],
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{
                            "type": "text",
                            "text": {"content": "Read →", "link": {"url": item["source_url"]}},
                            "annotations": {"color": "blue"}
                        }]}
                    }
                ]
            }
        })
    
    try:
        notion.blocks.children.append(block_id=page_id, children=children)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  failed to append to Notion: {e}")
        return False


def update_addendum_items(conn, items: list[dict], page_id: str) -> None:
    """Mark addendum items as published."""
    with conn.cursor() as cur:
        for item in items:
            cur.execute(
                """
                UPDATE news_memory 
                SET notion_page_id = %s, notion_status = 'live'
                WHERE id = %s
                """,
                (page_id, item["id"]),
            )


def run(dry_run: bool = False) -> int:
    """Main entry point."""
    from . import db

    window = addendum_window()
    
    with db.connect() as conn:
        items = get_addendum_items(conn, window)
        
        if not items:
            print(f"addendum: no late-breaking news for {window.label}")
            return 0

        page_id = get_week_page_id(conn, window)
        
        if dry_run:
            print(f"\n{'=' * 60}")
            print(f"  DRY RUN - {window.label}")
            print(f"{'=' * 60}\n")
            print(f"  Window: {window.start:%Y-%m-%d %H:%M} to {window.end:%H:%M} IST")
            print(f"  Week page: {page_id or 'NOT FOUND'}\n")
            
            print(f"  Late-breaking items: {len(items)}")
            for item in items:
                print(f"    [{item['score']:3}] {item['headline'][:50]}")
                print(f"          {item['source_name']} @ {item['published_at']:%H:%M}")
            
            return 0

        if not page_id:
            print("addendum: week page not found, skipping")
            return 1

        print(f"addendum: adding {len(items)} items to {window.label}...")

        notion = notion_api.get_client()
        if append_to_week_page(notion, page_id, items, window):
            update_addendum_items(conn, items, page_id)
            print(f"addendum: {len(items)} items added successfully")
        else:
            print("addendum: failed to update Notion")
            return 1

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish Saturday addendum.")
    ap.add_argument("--dry-run", action="store_true", help="show what would be added")
    args = ap.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
