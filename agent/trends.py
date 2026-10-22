"""Trend watcher: spot what's trending and follow it for a few days.

Runs once a day before ingest (daily.yml). Signals, all free:
  - Google Trends daily searches, India and US (with a related headline each)
  - names our own feeds keep repeating: an entity in stories from 3+ sources in 24h

One Groq call decides which signals are news our readers care about and writes a
short search for each. Each kept search becomes a trend watch: ingest fetches it
as a last-day Google News feed (source id trend_<n>) until it expires. The LLM
never invents feed links; it only picks search words.

    python -m agent.trends             # find trends, save watches
    python -m agent.trends --dry-run   # print what it would watch, write nothing
"""

from __future__ import annotations

import argparse
import json
import re

import feedparser
import httpx

from .config import DOMAINS, USER_AGENT
from .score import _INDIA_HINT, _call_groq

TRENDS_FEEDS = {
    "Google Trends India": "https://trends.google.com/trending/rss?geo=IN",
    "Google Trends US": "https://trends.google.com/trending/rss?geo=US",
}
OWN_FEEDS_MIN_SOURCES = 3   # an entity in stories from this many sources in 24h counts as trending
MAX_NEW_PER_DAY = 3
MAX_ACTIVE = 8
WATCH_DAYS = 5

TREND_PROMPT = """You pick trending topics worth following for News Intel, a briefing for the team at an Indian legal-tech company. They follow important developments across all of technology and science, plus Indian legal and business news.

Domains: {domains}

Trending signals (term | context):
{signals}

Already followed: {active}

Pick at most {max_new} signals that are a specific, newsworthy development in one of the domains (a product launch, a breach, an outage, a ruling, a deal, a mission, a scientific result). Skip sport, entertainment, celebrities, weather, generic company names with no event, and anything already followed.

For each, write a Google News search of 2-5 words that finds coverage of that development.

Reply with JSON only: [{{"term": "...", "domain": "<domain id>", "query": "...", "why": "<one short sentence>"}}]. Reply [] if none qualify."""


def google_trends() -> list[dict]:
    """Trending searches with their first related headline."""
    signals = []
    for name, url in TRENDS_FEEDS.items():
        try:
            resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"trends: {name} unavailable ({exc})")
            continue
        for e in feedparser.parse(resp.content).entries:
            signals.append({
                "term": e.get("title", "").strip(),
                "context": f"{e.get('ht_approx_traffic', '')} searches; {e.get('ht_news_item_title', '')}".strip(),
                "signal": name,
            })
    return [s for s in signals if s["term"]]


def own_feed_trends(conn) -> list[dict]:
    """Entities in stories from several of our sources in the last 24 hours."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e AS term, count(DISTINCT m.source_name) AS sources,
                   (array_agg(m.headline ORDER BY m.score DESC NULLS LAST))[1] AS headline
            FROM news_memory m, unnest(m.entities) AS e
            WHERE m.published_at > now() - interval '24 hours'
            GROUP BY e
            HAVING count(DISTINCT m.source_name) >= %s
            ORDER BY sources DESC
            LIMIT 20
            """,
            (OWN_FEEDS_MIN_SOURCES,),
        )
        return [{"term": r["term"], "context": f"in {r['sources']} of our sources; {r['headline']}",
                 "signal": "our feeds"} for r in cur.fetchall()]


def parse_picks(text: str, max_new: int) -> list[dict]:
    """The LLM's JSON list -> clean watches. Bad entries are dropped, not guessed."""
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        picks = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    out, seen = [], set()
    for p in picks if isinstance(picks, list) else []:
        if not isinstance(p, dict):
            continue
        query = re.sub(r"\s+", " ", str(p.get("query") or "")).strip().lower()
        words = len(query.split())
        if not 1 <= words <= 6 or query in seen:
            continue
        domain = str(p.get("domain") or "").strip().lower()
        if domain == "legal_india" and not _INDIA_HINT.search(f"{p.get('term')} {query} {p.get('why')}"):
            domain = "policy"   # the model files any court case under legal_india
        seen.add(query)
        out.append({
            "query": query,
            "term": str(p.get("term") or query)[:100],
            "domain": domain if domain in DOMAINS else "other",
            "why": str(p.get("why") or "")[:200],
        })
    return out[:max_new]


def pick_trends(signals: list[dict], active: list[str], max_new: int) -> list[dict]:
    if not signals or max_new <= 0:
        return []
    prompt = TREND_PROMPT.format(
        domains=", ".join(DOMAINS),
        signals="\n".join(f"- {s['term']} | {s['context'][:160]}" for s in signals),
        active=", ".join(active) or "nothing yet",
        max_new=max_new,
    )
    return parse_picks(_call_groq(prompt), max_new)


def run(dry_run: bool = False) -> int:
    from . import db

    with db.connect() as conn:
        if not dry_run:
            db.ensure_trend_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('trend_watches') IS NOT NULL AS ok")
            active = []
            if cur.fetchone()["ok"]:
                cur.execute("SELECT query FROM trend_watches WHERE expires_at > now()")
                active = [r["query"] for r in cur.fetchall()]
        signals = google_trends() + own_feed_trends(conn)

    room = min(MAX_NEW_PER_DAY, MAX_ACTIVE - len(active))
    print(f"trends: {len(signals)} signals, {len(active)} active watches, room for {max(room, 0)} more")
    if room <= 0:
        return 0

    picks = pick_trends(signals, active, room)
    signal_of = {s["term"].lower(): s["signal"] for s in signals}
    for p in picks:
        print(f"trends: watch '{p['query']}' ({p['domain']}) - {p['why']}")
    if dry_run or not picks:
        return 0

    with db.connect() as conn, conn.cursor() as cur:
        for p in picks:
            cur.execute(
                """
                INSERT INTO trend_watches (query, domain, reason, signal, expires_at)
                VALUES (%s, %s, %s, %s, now() + make_interval(days => %s))
                ON CONFLICT (query) DO UPDATE SET expires_at = EXCLUDED.expires_at
                """,
                (p["query"], p["domain"], p["why"], signal_of.get(p["term"].lower(), "llm"), WATCH_DAYS),
            )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Find trending topics and watch them.")
    ap.add_argument("--dry-run", action="store_true", help="print picks, write nothing")
    args = ap.parse_args()
    try:
        return run(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        # Trends are a bonus; never block the daily website refresh
        print(f"trends: skipped ({type(exc).__name__}: {exc})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
