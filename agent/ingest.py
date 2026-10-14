"""Phase 1: ingest.

Runs every 4 hours. Pulls every enabled source, normalises, dedups, writes
to raw_items, and records per-source health.

Design rule: ONE DEAD FEED MUST NEVER KILL THE RUN. Every fetch is isolated
and failures are recorded, not raised. The thing that actually hurts you is
a feed dying silently and the agent reporting a quiet week -- so failures
are counted and surfaced, never swallowed.

    python -m agent.ingest              # normal, writes to Neon
    python -m agent.ingest --dry-run    # no DB needed, prints a report
    python -m agent.ingest --dry-run --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from .config import FEED_CONCURRENCY, FEED_TIMEOUT, MAX_ITEM_AGE_DAYS, USER_AGENT
from .normalize import normalize_entry, normalize_hf_paper
from .sources import Source, enabled_sources


class FetchResult:
    __slots__ = ("source", "rows", "error", "newest")

    def __init__(self, source: Source, rows: list[dict],
                 error: str | None = None):
        self.source = source
        self.rows = rows
        self.error = error
        self.newest = max((r["published_at"] for r in rows), default=None)


async def _fetch_one(client: httpx.AsyncClient, source: Source,
                     sem: asyncio.Semaphore) -> FetchResult:
    async with sem:
        try:
            resp = await client.get(source.url, timeout=FEED_TIMEOUT)
            resp.raise_for_status()
            body = resp.content
        except Exception as exc:                      # noqa: BLE001
            return FetchResult(source, [], f"{type(exc).__name__}: {exc}")

    try:
        if source.kind == "json":
            payload = json.loads(body)
            raw = [normalize_hf_paper(p) for p in payload]
        else:
            parsed = feedparser.parse(body)
            if parsed.bozo and not parsed.entries:
                return FetchResult(
                    source, [], f"unparseable feed: {parsed.bozo_exception}"
                )
            raw = [normalize_entry(e, source) for e in parsed.entries]
    except Exception as exc:                          # noqa: BLE001
        return FetchResult(source, [], f"parse failed: {type(exc).__name__}: {exc}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_ITEM_AGE_DAYS)
    rows = [
        r for r in raw
        if r and r["url_canonical"] and r["published_at"] >= cutoff
    ]
    if not rows and raw:
        # Feed parsed fine but everything in it is old. Not an error --
        # low-cadence sources like Nature MI look like this for weeks.
        return FetchResult(source, [])
    return FetchResult(source, rows)


async def fetch_all(sources: list[Source]) -> list[FetchResult]:
    sem = asyncio.Semaphore(FEED_CONCURRENCY)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml,"
                  " application/json;q=0.9, text/xml;q=0.8, */*;q=0.5",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        return await asyncio.gather(*(_fetch_one(client, s, sem) for s in sources))


def run(dry_run: bool = False, limit: int | None = None) -> int:
    sources = enabled_sources()
    if limit:
        sources = sources[:limit]

    results = asyncio.run(fetch_all(sources))

    ok = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]
    all_rows = [row for r in ok for row in r.rows]

    stats = {
        "sources_total": len(results),
        "sources_ok": len(ok),
        "sources_failed": len(failed),
        "items_seen": len(all_rows),
        "items_new": 0,
        "detail": {
            "failures": {r.source.id: r.error for r in failed},
            "per_source": {r.source.id: len(r.rows) for r in ok},
        },
    }

    if dry_run:
        _print_report(results, stats)
        return 0

    from . import db
    with db.connect() as conn:
        db.sync_sources(conn)
        new_urls = db.insert_items(conn, all_rows)
        stats["items_new"] = len(new_urls)
        for r in ok:
            db.mark_source_result(conn, r.source.id, ok=True, newest_item=r.newest)
        for r in failed:
            db.mark_source_result(conn, r.source.id, ok=False, error=r.error)
        db.record_run(conn, "ingest", stats, ok=True)

    print(
        f"ingest: {stats['sources_ok']}/{stats['sources_total']} sources ok, "
        f"{stats['items_seen']} items seen, {stats['items_new']} new"
    )
    if failed:
        print("  failures:", ", ".join(f"{r.source.id} ({r.error[:60]})"
                                       for r in failed), file=sys.stderr)

    # Phase 2+ will hand new_urls to the enrich stage here.
    return 0


def _print_report(results: list[FetchResult], stats: dict) -> None:
    ok = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]

    print("\n" + "=" * 68)
    print("  DRY RUN - no database writes")
    print("=" * 68)

    by_tier = Counter()
    for r in ok:
        by_tier[r.source.tier] += len(r.rows)

    print(f"\n  sources polled : {stats['sources_total']}")
    print(f"  succeeded      : {stats['sources_ok']}")
    print(f"  failed         : {stats['sources_failed']}")
    print(f"  items (<= {MAX_ITEM_AGE_DAYS}d): {stats['items_seen']}")
    print("  by tier        : " + "  ".join(
        f"{t}={by_tier[t]}" for t in sorted(by_tier)))

    urls = [row["url_canonical"] for r in ok for row in r.rows]
    dupes = len(urls) - len(set(urls))
    print(f"  cross-feed dupes collapsed: {dupes}")

    print("\n  --- per source " + "-" * 50)
    for r in sorted(ok, key=lambda x: (x.source.tier, x.source.id)):
        newest = r.newest.strftime("%Y-%m-%d") if r.newest else "   none   "
        flag = "  " if r.rows else " !"
        print(f"  {flag}[{r.source.tier}] {r.source.id:<18} "
              f"{len(r.rows):>4} items   newest {newest}")

    if failed:
        print("\n  --- FAILURES " + "-" * 52)
        for r in failed:
            print(f"    [{r.source.tier}] {r.source.id:<18} {r.error[:70]}")

    print("\n  --- 10 most recent " + "-" * 46)
    newest = sorted(
        (row for r in ok for row in r.rows),
        key=lambda x: x["published_at"], reverse=True,
    )[:10]
    for row in newest:
        print(f"    {row['published_at']:%m-%d} [{row['source_id']:<16}] "
              f"{row['title'][:62]}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch all sources into raw_items.")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and report, but do not touch the database")
    ap.add_argument("--limit", type=int, help="only poll the first N sources")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
