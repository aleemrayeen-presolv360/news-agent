"""Phase 7b: Monday audit - source health report.

Sends weekly health report via Telegram:
- Failing sources (consecutive_failures >= 3)
- Stale sources (no items in 14+ days)
- Pipeline stats from the week

Runs Monday 08:30 IST via GitHub Actions.

    python -m agent.audit                # send audit report
    python -m agent.audit --dry-run      # show report without sending
"""

from __future__ import annotations

import argparse
from html import escape

from . import telegram
from .config import week_window
from .db import unhealthy_sources


def get_week_stats(conn, window) -> dict:
    """Get pipeline stats for the week."""
    with conn.cursor() as cur:
        # Ingest stats
        cur.execute("""
            SELECT 
                COUNT(*) as runs,
                SUM(items_seen) as items_seen,
                SUM(items_new) as items_new,
                SUM(sources_failed) as total_failures
            FROM runs
            WHERE job = 'ingest'
              AND finished_at >= %s
              AND finished_at < %s + interval '2 days'
        """, (window.start, window.end))
        ingest = cur.fetchone()
        
        # Scoring stats
        cur.execute("""
            SELECT 
                COUNT(*) as scored,
                COUNT(*) FILTER (WHERE score >= 85) as breaking,
                COUNT(*) FILTER (WHERE score >= 70) as major,
                AVG(score) as avg_score
            FROM news_memory
            WHERE published_at >= %s
              AND published_at < %s + interval '2 days'
              AND score IS NOT NULL
        """, (window.start, window.end))
        scoring = cur.fetchone()
        
        # Source health
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE enabled) as total,
                COUNT(*) FILTER (WHERE enabled AND consecutive_failures = 0) as healthy,
                COUNT(*) FILTER (WHERE enabled AND consecutive_failures >= 3) as failing
            FROM sources
        """)
        health = cur.fetchone()
        
        return {
            "ingest": ingest,
            "scoring": scoring,
            "health": health,
        }


def format_audit_report(window, stats: dict, unhealthy: list[dict]) -> str:
    """Format the audit report for Telegram."""
    ingest = stats["ingest"]
    scoring = stats["scoring"]
    health = stats["health"]
    
    msg = f"📊 <b>Weekly Audit: {window.label}</b>\n\n"
    
    # Pipeline stats
    msg += "<b>Pipeline</b>\n"
    msg += f"• Ingest runs: {ingest['runs'] or 0}\n"
    msg += f"• Items seen: {ingest['items_seen'] or 0}\n"
    msg += f"• New items: {ingest['items_new'] or 0}\n"
    msg += f"• Feed failures: {ingest['total_failures'] or 0}\n\n"
    
    # Scoring stats
    msg += "<b>Scoring</b>\n"
    msg += f"• Scored: {scoring['scored'] or 0}\n"
    msg += f"• Breaking (≥85): {scoring['breaking'] or 0}\n"
    msg += f"• Major (≥70): {scoring['major'] or 0}\n"
    if scoring['avg_score']:
        msg += f"• Avg score: {scoring['avg_score']:.1f}\n"
    msg += "\n"
    
    # Source health
    msg += "<b>Sources</b>\n"
    msg += f"• Healthy: {health['healthy']}/{health['total']}\n"
    msg += f"• Failing: {health['failing']}\n\n"
    
    # Unhealthy sources detail
    if unhealthy:
        msg += "<b>⚠️ Needs Attention</b>\n"
        for src in unhealthy[:5]:
            reason = ""
            if src["consecutive_failures"] >= 3:
                reason = f"({src['consecutive_failures']} failures)"
            elif src["last_item_at"] is None:
                reason = "(never fetched)"
            else:
                reason = f"(stale since {src['last_item_at']:%m-%d})"
            msg += f"• [{src['tier']}] {escape(src['name'][:20])} {reason}\n"  # "Bar & Bench" breaks Telegram HTML
        
        if len(unhealthy) > 5:
            msg += f"• ... and {len(unhealthy) - 5} more\n"
    else:
        msg += "✅ All sources healthy\n"
    
    return msg


def run(dry_run: bool = False) -> int:
    """Main entry point."""
    from . import db

    window = week_window()
    
    with db.connect() as conn:
        stats = get_week_stats(conn, window)
        unhealthy = unhealthy_sources(conn)

        report = format_audit_report(window, stats, unhealthy)

        if dry_run:
            print(f"\n{'=' * 60}")
            print("  DRY RUN - audit report")
            print(f"{'=' * 60}\n")
            # Convert HTML to plain text for console
            plain = report.replace("<b>", "").replace("</b>", "")
            print(plain)
            return 0

        if telegram.send(report):
            print(f"audit: report sent for {window.label}")
        else:
            print("audit: failed to send report")
            print(report)
            return 1

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Send weekly audit report.")
    ap.add_argument("--dry-run", action="store_true", help="show report without sending")
    args = ap.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
