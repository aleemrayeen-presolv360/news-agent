"""Phase 6: Telegram alerts for breaking news.

Sends immediate alerts for high-scoring items (score >= 85).
Runs as separate pass after scoring for clean separation.

    python -m agent.alerts               # send pending alerts
    python -m agent.alerts --dry-run     # show what would be sent
"""

from __future__ import annotations

import argparse
from html import escape

from . import telegram
from .config import SCORE_BREAKING

ALERT_MAX_AGE_DAYS = 3


def get_unalerted_breaking(conn) -> list[dict]:
    """Get recent breaking news items that haven't been alerted yet.

    Only the last ALERT_MAX_AGE_DAYS: when a backlog gets scored late, old stories
    still reach the website but don't arrive on Telegram as "breaking".
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.id, m.headline, m.one_liner, m.source_url, m.source_name,
                   m.score, m.entities, m.market_impact
            FROM news_memory m
            WHERE m.score >= %s
              AND m.alerted_at IS NULL
              AND m.published_at >= now() - make_interval(days => %s)
            ORDER BY m.score DESC
        """, (SCORE_BREAKING, ALERT_MAX_AGE_DAYS))
        return cur.fetchall()


def format_alert(item: dict) -> str:
    """Format item as Telegram message."""
    score_bar = "*" * (item["score"] // 20)
    
    # Telegram parses HTML: an "&" or "<" in feed text would make it reject the message
    msg = f"BREAKING: <b>{escape(item['headline'][:100])}</b>\n\n"

    if item["one_liner"]:
        msg += f"{escape(item['one_liner'][:200])}\n\n"

    if item["market_impact"] and item["market_impact"] != "none":
        msg += f"Market: {escape(item['market_impact'][:150])}\n\n"

    if item["entities"]:
        msg += f"Tags: {escape(', '.join(item['entities'][:4]))}\n"

    msg += f"\n{score_bar} Score: {item['score']}/100\n"
    msg += f"Source: {escape(item['source_name'])}\n"
    msg += f"Link: {escape(item['source_url'])}"
    
    return msg


def mark_alerted(conn, item_ids: list[int]) -> None:
    """Mark items as alerted."""
    if not item_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE news_memory SET alerted_at = now() WHERE id = ANY(%s)",
            (item_ids,),
        )


def run(dry_run: bool = False) -> int:
    """Main entry point."""
    from . import db

    with db.connect() as conn:
        items = get_unalerted_breaking(conn)
        
        if not items:
            print("alerts: no breaking news to alert")
            return 0

        print(f"alerts: {len(items)} breaking news items (score >= {SCORE_BREAKING})")

        if dry_run:
            print(f"\n{'=' * 60}")
            print("  DRY RUN - alerts that would be sent")
            print(f"{'=' * 60}\n")
            
            for item in items:
                print(f"  [{item['score']}] {item['headline'][:60]}")
                print(f"       {item['source_name']} - {item['source_url'][:40]}")
                print()
            
            return 0

        # Send alerts
        sent_ids = []
        for item in items:
            msg = format_alert(item)
            if telegram.send(msg, link_preview=True):
                sent_ids.append(item["id"])
                print(f"  [OK] [{item['score']}] {item['headline'][:50]}")
            else:
                print(f"  [SKIP] [{item['score']}] {item['headline'][:50]}")

        # Mark as alerted
        mark_alerted(conn, sent_ids)
        
        print(f"alerts: {len(sent_ids)}/{len(items)} sent successfully")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Send Telegram alerts for breaking news.")
    ap.add_argument("--dry-run", action="store_true", help="show alerts without sending")
    args = ap.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
