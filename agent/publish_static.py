"""Write frontend/data.js, the only news file the News Intel website reads.

Runs after scoring in the daily, Friday and new-source workflows (and can be run by hand).
The website has no API: it loads this file directly.

    python -m agent.publish_static              # generate data.js
    python -m agent.publish_static --dry-run    # preview without writing
    python -m agent.publish_static --stamp-only # only refresh the ?v= links in index.html

"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
                   (SELECT r.source_id FROM raw_items r WHERE r.id = m.id) as source_id,
                   (SELECT COUNT(*) FROM news_memory m2
                    WHERE m2.cluster_id = m.cluster_id AND m2.cluster_id IS NOT NULL) as cluster_count
            FROM news_memory m
            WHERE m.score IS NOT NULL
              AND m.score >= %s
              AND m.published_at >= now() - make_interval(days => %s)
            ORDER BY m.score DESC
        """, (SCORE_NOTABLE, WEBSITE_DAYS))
        return cur.fetchall()


COVERAGE_MAX = 12   # other outlets listed under one story


def get_cluster_members(conn, cluster_ids: list[int]) -> dict[int, list[dict]]:
    """Every article in these clusters, scored or not: the outlets that covered each event."""
    if not cluster_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, cluster_id, headline, source_name, source_url, published_at
            FROM news_memory WHERE cluster_id = ANY(%s)
            ORDER BY published_at NULLS LAST
        """, (cluster_ids,))
        members: dict[int, list[dict]] = {}
        for row in cur.fetchall():
            members.setdefault(row["cluster_id"], []).append(row)
        return members


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


INGEST_LATE_HOURS = 10   # no feed fetch for this long means GitHub skipped or failed ingests


def get_health(conn) -> dict:
    """Pipeline health for the website, which is the only place problems are shown."""
    from .db import unhealthy_sources

    with conn.cursor() as cur:
        cur.execute("""
            SELECT max(finished_at) AS last_at,
                   count(*) FILTER (WHERE finished_at > now() - interval '24 hours') AS runs_24h
            FROM runs WHERE job = 'ingest'
        """)
        ingest = cur.fetchone()
        cur.execute("SELECT finished_at, detail FROM runs WHERE job = 'score' ORDER BY finished_at DESC LIMIT 1")
        score = cur.fetchone()

    broken = [s for s in unhealthy_sources(conn) if not s["id"].startswith("trend_")]
    failing = [s["name"] for s in broken if s["consecutive_failures"] >= 3]
    quiet = [s["name"] for s in broken if s["consecutive_failures"] < 3]
    detail = (score or {}).get("detail") or {}

    warnings = []
    last_ingest = ingest["last_at"]
    if last_ingest is None or (datetime.now(IST) - last_ingest).total_seconds() > INGEST_LATE_HOURS * 3600:
        warnings.append(f"Feeds haven't been fetched for over {INGEST_LATE_HOURS} hours. "
                        "Check the ingest workflow in GitHub Actions.")
    warnings += detail.get("warnings") or []
    # Failing feeds are listed in the health panel, not warned about: some sites block GitHub
    # for good, and a banner that never goes away stops being read

    def iso(value):
        return value.astimezone(IST).isoformat(timespec="seconds") if value else None

    return {
        "last_ingest_at": iso(last_ingest),
        "ingest_runs_24h": ingest["runs_24h"] or 0,
        "last_score": {
            "at": iso(score["finished_at"]),
            "scored": detail.get("scored", 0),
            "waiting": detail.get("waiting"),
            "groq_remaining": detail.get("groq_remaining"),
        } if score else None,
        "failing_sources": failing,
        "quiet_sources": quiet,
        "warnings": warnings,
    }


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


TRENDING_SOURCES = 3   # a story carried by this many of our sources counts as trending


def display_names(headline: str | None, source: str | None, url: str | None) -> tuple[str, str]:
    """Headline and outlet as readers should see them."""
    headline, source = headline or "Untitled", source or "Unknown"
    aggregated = "news.google.com" in (url or "") or source.endswith("(NewsData)")
    if aggregated and " - " in headline:
        # Google News and NewsData titles end in " - Publisher"; show the publisher, not the search
        headline, source = headline.rsplit(" - ", 1)
    return headline, source


def coverage_for(item: dict, members: list[dict]) -> list[dict]:
    """The other outlets in this story's cluster, oldest first, one entry per article."""
    seen = {item.get("source_url")}
    out = []
    for m in members:
        if m["id"] == item.get("id") or m["source_url"] in seen:
            continue
        seen.add(m["source_url"])
        headline, source = display_names(m["headline"], m["source_name"], m["source_url"])
        out.append({"source": source, "headline": headline, "url": m["source_url"]})
    return out[:COVERAGE_MAX]


def item_to_dict(item: dict, members: list[dict] | None = None) -> dict:
    """Convert DB row to frontend-friendly dict. `members` is the story's cluster, if it has one."""
    # Stories scored before domains existed have none; the website guesses those from keywords
    domain = (item.get("score_breakdown") or {}).get("domain")
    headline, source = display_names(item["headline"], item["source_name"], item["source_url"])
    cluster_count = item["cluster_count"] or 1
    return {
        "headline": headline,
        "score": item["score"],
        "source": source,
        "url": item["source_url"] or "#",
        "one_liner": item["one_liner"],
        "topics": item["topics"] or [],
        "entities": item["entities"] or [],
        "market_impact": item["market_impact"],
        "domain": domain,
        "category": DOMAINS.get(domain),
        "cluster_count": cluster_count,
        "cluster_id": item.get("cluster_id"),
        "coverage": coverage_for(item, members or []),
        "trending": (item.get("source_id") or "").startswith("trend_") or cluster_count >= TRENDING_SOURCES,
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
    members = get_cluster_members(conn, sorted({i["cluster_id"] for i in items if i.get("cluster_id")}))

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
        "health": get_health(conn),
        **{label: [item_to_dict(i, members.get(i.get("cluster_id"))) for i in group]
           for label, group in groups.items()},
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


ASSET_REF = re.compile(r'((?:href|src)=")((?:css|js)/[\w.-]+\.(?:css|js)|data\.js)(?:\?v=\w+)?(")')


def stamp_assets(html: str, frontend_dir: Path) -> str:
    """Add ?v=<content hash> to local css/js links. The host's CDN caches these
    files for 4 hours by name, so without a new name visitors get stale code and
    yesterday's news."""
    def repl(m):
        path = frontend_dir / m.group(2)
        if not path.exists():
            return m.group(0)
        digest = hashlib.md5(path.read_bytes()).hexdigest()[:8]
        return f"{m.group(1)}{m.group(2)}?v={digest}{m.group(3)}"
    return ASSET_REF.sub(repl, html)


def write_index_html() -> None:
    """Re-stamp index.html so every changed css/js/data file gets a fresh URL."""
    path = FRONTEND_DIR / "index.html"
    html = path.read_text(encoding="utf-8")
    stamped = stamp_assets(html, FRONTEND_DIR)
    if stamped != html:
        path.write_text(stamped, encoding="utf-8")
        print(f"publish_static: re-stamped {path}")


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
        write_index_html()

        print(f"publish_static: {window.label}")
        print(f"  breaking={len(data['breaking'])}, major={len(data['major'])}, notable={len(data['notable'])}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate static frontend data.")
    ap.add_argument("--dry-run", action="store_true", help="preview without writing")
    ap.add_argument("--week-offset", type=int, default=0, help="-1 for last week, -2 for two weeks ago")
    ap.add_argument("--stamp-only", action="store_true",
                    help="only refresh the ?v= links in index.html (after a css/js change)")
    args = ap.parse_args()
    if args.stamp_only:
        write_index_html()
        return 0
    return run(dry_run=args.dry_run, week_offset=args.week_offset)


if __name__ == "__main__":
    raise SystemExit(main())
