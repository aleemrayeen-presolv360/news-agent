"""Write frontend/data.js, the only news file the News Intel website reads.

Runs after scoring in the Friday publish workflow (and can be run by hand).
The website has no API: it loads this file directly.

    python -m agent.publish_static              # generate data.js
    python -m agent.publish_static --dry-run    # preview without writing

"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from .config import (
    DOMAINS, IST, week_window,
    SCORE_BREAKING, SCORE_MAJOR, SCORE_NOTABLE, WEBSITE_DAYS,
)


FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def get_week_items(conn, window) -> list[dict]:
    """Every story scored Notable or above from the last WEBSITE_DAYS, highest score first."""
    with conn.cursor() as cur:
        # Not just this week, so the site's date filter has something to work with
        cur.execute("""
            SELECT m.id, m.headline, m.one_liner, m.source_url, m.source_name,
                   m.published_at, m.score, m.entities, m.topics,
                   m.market_impact, m.cluster_id, m.score_breakdown,
                   (SELECT COUNT(*) FROM news_memory m2
                    WHERE m2.cluster_id = m.cluster_id AND m2.cluster_id IS NOT NULL) as cluster_count
            FROM news_memory m
            WHERE m.score IS NOT NULL
              AND m.score >= %s
              AND m.published_at >= now() - make_interval(days => %s)
            ORDER BY m.score DESC
        """, (SCORE_NOTABLE, WEBSITE_DAYS))
        return cur.fetchall()


def get_source_health(conn) -> dict:
    """Get source health stats."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE enabled) as total,
                COUNT(*) FILTER (WHERE enabled AND consecutive_failures = 0) as healthy
            FROM sources
        """)
        return cur.fetchone()


def get_run_stats(conn, window) -> dict:
    """Get ingest run stats for the week."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COALESCE(SUM(items_new), 0) as items_new
            FROM runs
            WHERE job = 'ingest'
              AND finished_at >= %s
              AND finished_at < %s
        """, (window.start, window.end))
        return cur.fetchone()


NEW_SOURCE_DAYS = 2   # how long Settings shows "Added today" for a source


def get_new_sources(conn) -> list[dict]:
    """Sources whose first items arrived in the last NEW_SOURCE_DAYS, newest first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.name, min(r.ingested_at) AS added
            FROM raw_items r JOIN sources s ON s.id = r.source_id
            GROUP BY s.name
            HAVING min(r.ingested_at) > now() - make_interval(days => %s)
            ORDER BY added DESC, s.name
            """,
            (NEW_SOURCE_DAYS,),
        )
        return [{"name": r["name"], "added_at": r["added"].astimezone(IST).isoformat(timespec="seconds")}
                for r in cur.fetchall()]


def item_to_dict(item: dict) -> dict:
    """Convert DB row to frontend-friendly dict."""
    # Stories scored before domains existed have none; the website guesses those from keywords
    domain = (item.get("score_breakdown") or {}).get("domain")
    return {
        "headline": item["headline"] or "Untitled",
        "score": item["score"],
        "source": item["source_name"] or "Unknown",
        "url": item["source_url"] or "#",
        "one_liner": item["one_liner"],
        "topics": item["topics"] or [],
        "entities": item["entities"] or [],
        "market_impact": item["market_impact"],
        "domain": domain,
        "category": DOMAINS.get(domain),
        "cluster_count": item["cluster_count"] or 1,
        "published_at": item["published_at"].isoformat() if item.get("published_at") else None,
    }


def split_by_label(items: list[dict]) -> dict[str, list[dict]]:
    """Breaking / Major / Notable, no caps. Items below Notable are dropped."""
    return {
        "breaking": [i for i in items if i["score"] >= SCORE_BREAKING],
        "major": [i for i in items if SCORE_MAJOR <= i["score"] < SCORE_BREAKING],
        "notable": [i for i in items if SCORE_NOTABLE <= i["score"] < SCORE_MAJOR],
    }


def generate_data(conn, window) -> dict:
    """Generate the full data structure for frontend."""
    items = get_week_items(conn, window)
    health = get_source_health(conn)
    stats = get_run_stats(conn, window)
    groups = split_by_label(items)

    return {
        "week_label": window.label,
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
        "stats": {
            "sources_total": health["total"] or 40,
            "sources_healthy": health["healthy"] or 0,
            "items_ingested": stats["items_new"] or 0,
            "major_stories": len(groups["breaking"]) + len(groups["major"]),
            "notable_stories": len(groups["notable"]),
        },
        "new_sources": get_new_sources(conn),
        **{label: [item_to_dict(i) for i in group] for label, group in groups.items()},
    }


def write_data_js(data: dict) -> None:
    """Write data.js via a temp file, so a failed run never leaves the website a half-written file."""
    js_content = f"""// This file is auto-generated by publish_static.py
// DO NOT EDIT MANUALLY

window.digestData = {json.dumps(data, indent=4, ensure_ascii=False)};
"""
    output_path = FRONTEND_DIR / "data.js"
    tmp_path = output_path.with_suffix(".js.tmp")
    tmp_path.write_text(js_content, encoding="utf-8")
    os.replace(tmp_path, output_path)
    print(f"publish_static: wrote {output_path}")


def run(dry_run: bool = False, week_offset: int = 0) -> int:
    """Main entry point."""
    from . import db
    from datetime import timedelta

    window = week_window()
    
    # Allow generating for previous weeks
    if week_offset != 0:
        from dataclasses import replace
        days = week_offset * 7
        window = replace(
            window,
            start=window.start - timedelta(days=days),
            end=window.end - timedelta(days=days),
            label=f"Week {int(window.label.split()[1]) + week_offset} (offset {week_offset})"
        )
    
    with db.connect() as conn:
        data = generate_data(conn, window)

        if dry_run:
            print(f"\n{'=' * 60}")
            print(f"  DRY RUN - {window.label}")
            print(f"{'=' * 60}\n")
            
            print(f"  Sources: {data['stats']['sources_healthy']}/{data['stats']['sources_total']}")
            print(f"  Items: {data['stats']['items_ingested']}")
            print(f"\n  Breaking (>={SCORE_BREAKING}): {len(data['breaking'])}")
            for i in data['breaking'][:5]:
                print(f"    [{i['score']}] {i['headline'][:50]}")
            
            print(f"\n  Major (>={SCORE_MAJOR}): {len(data['major'])}")
            for i in data['major'][:5]:
                print(f"    [{i['score']}] {i['headline'][:50]}")
            
            print(f"\n  Notable (>={SCORE_NOTABLE}): {len(data['notable'])}")
            print(f"    ... {len(data['notable'])} items")
            
            return 0

        write_data_js(data)
        
        print(f"publish_static: {window.label}")
        print(f"  breaking={len(data['breaking'])}, major={len(data['major'])}, notable={len(data['notable'])}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate static frontend data.")
    ap.add_argument("--dry-run", action="store_true", help="preview without writing")
    ap.add_argument("--week-offset", type=int, default=0, help="-1 for last week, -2 for two weeks ago")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, week_offset=args.week_offset)


if __name__ == "__main__":
    raise SystemExit(main())
