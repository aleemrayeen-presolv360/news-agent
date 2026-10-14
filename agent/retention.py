"""Phase 7: Retention - archive old Notion pages, keep memory.

Archives Notion pages older than 30 days while keeping news_memory rows
intact, so old news can still be referenced.

Auto-restores items with reference_count >= 2 (frequently cited).

Runs daily 03:00 IST via GitHub Actions.

    python -m agent.retention            # run retention
    python -m agent.retention --dry-run  # show what would be archived
"""

from __future__ import annotations

import argparse
from datetime import datetime

from notion_client import Client

from . import notion as notion_api
from .config import env, retention_cutoff


def get_items_to_archive(conn, cutoff: datetime) -> list[dict]:
    """Get items older than cutoff that are still live in Notion."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, headline, notion_page_id, published_at, reference_count
            FROM news_memory
            WHERE notion_status = 'live'
              AND notion_page_id IS NOT NULL
              AND published_at < %s
              AND reference_count < 2
            ORDER BY published_at ASC
        """, (cutoff,))
        return cur.fetchall()


def get_items_to_restore(conn) -> list[dict]:
    """Get archived items that should be restored (high reference count)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, headline, one_liner, source_url, source_name, 
                   score, reference_count
            FROM news_memory
            WHERE notion_status = 'archived'
              AND reference_count >= 2
            ORDER BY reference_count DESC
            LIMIT 10
        """)
        return cur.fetchall()


def archive_notion_page(notion: Client, page_id: str) -> bool:
    """Archive a Notion page (set archived=true)."""
    try:
        notion.pages.update(page_id=page_id, archived=True)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  failed to archive {page_id}: {e}")
        return False


def restore_notion_page(notion: Client, item: dict, ds_items: str) -> str | None:
    """Restore an item by creating a new Notion page."""
    try:
        response = notion.pages.create(
            parent={"database_id": ds_items},
            properties={
                "Name": {"title": [{"text": {"content": item["headline"][:100]}}]},
                "Score": {"number": item["score"]},
                "Source": {"rich_text": [{"text": {"content": item["source_name"]}}]},
                "URL": {"url": item["source_url"]},
                "Status": {"select": {"name": "Restored"}},
            },
            children=[
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "icon": {"emoji": "🔄"},
                        "rich_text": [{"type": "text", "text": {
                            "content": f"Auto-restored: referenced {item['reference_count']} times"
                        }}],
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {
                        "content": item["one_liner"] or ""
                    }}]}
                },
            ],
        )
        return response["id"]
    except Exception as e:  # noqa: BLE001
        print(f"  failed to restore {item['headline'][:30]}: {e}")
        return None


def mark_archived(conn, item_ids: list[int]) -> None:
    """Mark items as archived in news_memory."""
    if not item_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE news_memory 
            SET notion_status = 'archived', notion_page_id = NULL
            WHERE id = ANY(%s)
            """,
            (item_ids,),
        )


def mark_restored(conn, item_id: int, page_id: str) -> None:
    """Mark item as restored with new Notion page."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE news_memory 
            SET notion_status = 'restored', notion_page_id = %s
            WHERE id = %s
            """,
            (page_id, item_id),
        )


def run(dry_run: bool = False, days: int = 30) -> int:
    """Main entry point."""
    from . import db

    if not dry_run and not notion_api.is_configured():
        print("retention: Notion not configured (NOTION_TOKEN unset), skipping")
        return 0

    cutoff = retention_cutoff(days=days)
    
    with db.connect() as conn:
        to_archive = get_items_to_archive(conn, cutoff)
        to_restore = get_items_to_restore(conn)

        if dry_run:
            print(f"\n{'=' * 60}")
            print(f"  DRY RUN - retention (cutoff: {cutoff:%Y-%m-%d})")
            print(f"{'=' * 60}\n")
            
            print(f"  To archive: {len(to_archive)} items")
            for item in to_archive[:10]:
                print(f"    {item['published_at']:%Y-%m-%d} | {item['headline'][:45]}")
            if len(to_archive) > 10:
                print(f"    ... and {len(to_archive) - 10} more")
            
            print(f"\n  To restore: {len(to_restore)} items")
            for item in to_restore:
                print(f"    [refs={item['reference_count']}] {item['headline'][:45]}")
            
            return 0

        if not to_archive and not to_restore:
            print("retention: nothing to do")
            return 0

        notion = notion_api.get_client()
        ds_items = env("NOTION_DS_ITEMS")

        # Archive old items
        archived_ids = []
        for item in to_archive:
            if archive_notion_page(notion, item["notion_page_id"]):
                archived_ids.append(item["id"])
        
        mark_archived(conn, archived_ids)

        # Restore high-reference items
        restored = 0
        if ds_items:
            for item in to_restore:
                page_id = restore_notion_page(notion, item, ds_items)
                if page_id:
                    mark_restored(conn, item["id"], page_id)
                    restored += 1

        print(f"retention: {len(archived_ids)} archived, {restored} restored")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Run retention policy.")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen")
    ap.add_argument("--days", type=int, default=30, help="retention period in days")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, days=args.days)


if __name__ == "__main__":
    raise SystemExit(main())
