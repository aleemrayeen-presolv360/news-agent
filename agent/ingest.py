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
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import feedparser
import httpx

from .config import (
    FEED_CONCURRENCY, FEED_TIMEOUT, FIRST_FETCH_HOURS, MAX_ITEM_AGE_DAYS, USER_AGENT,
)
from .normalize import normalize_entry, normalize_hf_paper
from .sources import Source, _google_news, enabled_sources


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


FIRST_FETCH_REASON = f"first_fetch_older_than_{FIRST_FETCH_HOURS}h"
TREND_MAX_ITEMS = 8   # per trend watch per fetch, so trends can't swamp the scoring budget


def split_first_fetch(rows: list[dict], first_ids: set[str],
                      now: datetime) -> tuple[list[dict], list[dict]]:
    """Rows to process, and rows from first-time sources too old to process.

    A source seen for the first time only contributes its last FIRST_FETCH_HOURS;
    the rest is returned separately so it can be stored as already seen.
    """
    cutoff = now - timedelta(hours=FIRST_FETCH_HOURS)
    keep, seen = [], []
    for r in rows:
        (seen if r["source_id"] in first_ids and r["published_at"] < cutoff else keep).append(r)
    return keep, seen


def needs_gap_fill(source: Source, rows: list[dict], now: datetime) -> bool:
    """A new feed whose item list doesn't reach back FIRST_FETCH_HOURS.

    Many feeds list only their last 10-50 items, so a busy channel's feed can
    cover just the last few hours. Google News fills in the rest of the day.
    """
    if source.kind != "rss" or "news.google.com" in source.url or not rows:
        return False
    return min(r["published_at"] for r in rows) > now - timedelta(hours=FIRST_FETCH_HOURS)


def _title_key(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()[:60]


def gap_fill_rows(source: Source, feed_rows: list[dict], gn_rows: list[dict]) -> list[dict]:
    """Google News rows for this source that its own feed doesn't already carry."""
    seen = {_title_key(r["title"]) for r in feed_rows}
    out = []
    for r in gn_rows:
        title = re.sub(r"\s+-\s+[^-]+$", "", r["title"])   # drop the " - Publisher" suffix
        if _title_key(title) in seen:
            continue
        seen.add(_title_key(title))
        out.append({**r, "title": title, "source_id": source.id})
    return out


async def fetch_gap_fill(results: list[FetchResult], now: datetime) -> list[dict]:
    """Last-day Google News rows for new sources whose feed is too short."""
    todo = [r for r in results if needs_gap_fill(r.source, r.rows, now)]
    if not todo:
        return []
    searches = [
        Source(id=r.source.id, name=r.source.name, tier=r.source.tier,
               url=_google_news(f"site:{urlsplit(r.source.url).hostname.removeprefix('www.')}", days=1))
        for r in todo
    ]
    found = await fetch_all(searches)
    rows = []
    for r, gn in zip(todo, found):
        rows += gap_fill_rows(r.source, r.rows, gn.rows)
    return rows


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
    backed_off: set[str] = set()
    if not dry_run:
        from . import db
        with db.connect() as conn:
            db.ensure_trend_table(conn)
            trend_sources = db.active_trend_sources(conn)
            db.sync_sources(conn, trend_sources)
            backed_off = db.backed_off_source_ids(conn)
        sources = [s for s in sources + trend_sources if s.id not in backed_off]

    results = asyncio.run(fetch_all(sources))

    for r in results:
        if r.source.id.startswith("trend_"):
            # A hot topic can return 100 results a day; the newest few are enough
            r.rows = sorted(r.rows, key=lambda x: x["published_at"], reverse=True)[:TREND_MAX_ITEMS]

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
            "backed_off": sorted(backed_off),
            "failures": {r.source.id: r.error for r in failed},
            "per_source": {r.source.id: len(r.rows) for r in ok},
        },
    }

    if dry_run:
        _print_report(results, stats)
        return 0

    from . import db
    with db.connect() as conn:
        first_ids = db.first_fetch_source_ids(conn) & {r.source.id for r in ok}
        now = datetime.now(timezone.utc)
        gap_rows = asyncio.run(fetch_gap_fill([r for r in ok if r.source.id in first_ids], now))
        if gap_rows:
            print(f"ingest: {len(gap_rows)} extra items from Google News for busy new sources")
        keep, seen = split_first_fetch(all_rows + gap_rows, first_ids, now)
        new_urls = db.insert_items(conn, keep)
        # After the real rows, so an article another feed also carries is processed normally
        db.insert_items(conn, seen, skip_reason=FIRST_FETCH_REASON)
        stats["items_new"] = len(new_urls)
        if first_ids:
            stats["detail"]["first_fetch"] = {
                "sources": sorted(first_ids),
                "kept": sum(r["source_id"] in first_ids for r in keep),
                "stored_as_seen": len(seen),
            }
            print(f"ingest: first fetch for {', '.join(sorted(first_ids))}: "
                  f"kept the last {FIRST_FETCH_HOURS}h, {len(seen)} older items stored as seen")
        for r in ok:
            db.mark_source_result(conn, r.source.id, ok=True, newest_item=r.newest)
        for r in failed:
            db.mark_source_result(conn, r.source.id, ok=False, error=r.error)
        db.record_run(conn, "ingest", stats, ok=True)

    print(
        f"ingest: {stats['sources_ok']}/{stats['sources_total']} sources ok, "
        f"{stats['items_seen']} items seen, {stats['items_new']} new"
        + (f", {len(backed_off)} failing sources skipped until tomorrow" if backed_off else "")
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
