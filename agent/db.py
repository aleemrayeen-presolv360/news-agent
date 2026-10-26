"""Neon Postgres access.

Neon's free plan auto-suspends after ~5 min idle and auto-resumes on
connect in about a second, so the first connection of a run can be slow.
That is normal operation, not an error -- hence the generous timeout and
the single retry.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Sequence

import psycopg
from psycopg.rows import dict_row

from .config import env
from .sources import SOURCES, Source, _google_news


@contextlib.contextmanager
def connect():
    """Connection context manager. Retries once for Neon cold start."""
    dsn = env("NEON_DSN", required=True)
    try:
        conn = psycopg.connect(dsn, connect_timeout=15, row_factory=dict_row)
    except psycopg.OperationalError:
        # Neon was suspended; it is waking now. One retry is enough.
        conn = psycopg.connect(dsn, connect_timeout=30, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


TREND_PREFIX = "trend_"


def sync_sources(conn, extra: Sequence[Source] = ()) -> None:
    """Push sources.py (plus trend watches and approved website requests) into the sources table. Safe to run every ingest."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO sources (id, name, tier, kind, feed_url, enabled, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name     = EXCLUDED.name,
                tier     = EXCLUDED.tier,
                kind     = EXCLUDED.kind,
                feed_url = EXCLUDED.feed_url,
                enabled  = EXCLUDED.enabled,
                note     = EXCLUDED.note
            """,
            [(s.id, s.name, s.tier, s.kind, s.url, s.enabled, s.note)
             for s in (*SOURCES, *extra)],
        )
        # Expired trend watches stay in the table (raw_items point at them) but switch off
        cur.execute(
            "UPDATE sources SET enabled = false WHERE id LIKE %s AND NOT (id = ANY(%s::text[]))",
            (TREND_PREFIX + "%", [s.id for s in extra]),
        )


def ensure_trend_table(conn) -> None:
    """trend_watches: one Google News search per trending topic, for a few days."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_watches (
              id          BIGSERIAL PRIMARY KEY,
              query       TEXT NOT NULL UNIQUE,     -- lower-case Google News search
              domain      TEXT,
              reason      TEXT,
              signal      TEXT,                     -- what spotted it
              created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
              expires_at  TIMESTAMPTZ NOT NULL
            )
            """
        )


def active_trend_sources(conn) -> list[Source]:
    """Each unexpired trend watch as a last-day Google News source."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, query, reason FROM trend_watches WHERE expires_at > now() ORDER BY id")
        return [
            Source(id=f"{TREND_PREFIX}{r['id']}", name=f"Trending: {r['query']}", tier="D",
                   url=_google_news(r["query"], days=1), note=(r["reason"] or "")[:300])
            for r in cur.fetchall()
        ]


# A source that failed this many times in a row is polled once a day instead of
# every run. `enabled` can't be used for this: sync_sources resets it from
# sources.py, which stays the single on/off switch.
BACKOFF_FAILURES = 3
BACKOFF_HOURS = 24


def backed_off_source_ids(conn) -> set[str]:
    """Failing sources that were already tried in the last BACKOFF_HOURS."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM sources
            WHERE consecutive_failures >= %s
              AND last_poll_at > now() - make_interval(hours => %s)
            """,
            (BACKOFF_FAILURES, BACKOFF_HOURS),
        )
        return {row["id"] for row in cur.fetchall()}


def first_fetch_source_ids(conn) -> set[str]:
    """Sources that have never been fetched successfully (just added, or never working)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM sources WHERE last_success_at IS NULL")
        return {row["id"] for row in cur.fetchall()}


def insert_items(conn, rows: Sequence[dict], skip_reason: str | None = None) -> list[str]:
    """Insert new items, ignoring ones we already have.

    The UNIQUE(url_canonical) constraint plus ON CONFLICT DO NOTHING is the
    real dedup guarantee. RETURNING gives us exactly which rows were new,
    so the caller can hand just those to the enrich stage.

    With skip_reason the rows are stored as already triaged and rejected, so
    they are remembered (never "new" again) but never processed.
    """
    if not rows:
        return []
    # Collapse duplicates inside this batch first -- the same story often
    # appears in two feeds in one run, and ON CONFLICT cannot see rows
    # inserted by the same statement.
    deduped: dict[str, dict] = {}
    for r in rows:
        if r["url_canonical"] and r["url_canonical"] not in deduped:
            deduped[r["url_canonical"]] = r

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_items
                (url_canonical, url_original, title, source_id,
                 published_at, feed_summary, rules_pass, rules_reason)
            SELECT *,
                   CASE WHEN %s::text IS NULL THEN NULL ELSE false END,
                   %s::text
            FROM unnest(
                %s::text[], %s::text[], %s::text[],
                %s::text[], %s::timestamptz[], %s::text[]
            )
            ON CONFLICT (url_canonical) DO NOTHING
            RETURNING url_canonical
            """,
            (
                skip_reason,
                skip_reason,
                [r["url_canonical"] for r in deduped.values()],
                [r["url_original"] for r in deduped.values()],
                [r["title"] for r in deduped.values()],
                [r["source_id"] for r in deduped.values()],
                [r["published_at"] for r in deduped.values()],
                [r["feed_summary"] for r in deduped.values()],
            ),
        )
        return [row["url_canonical"] for row in cur.fetchall()]


def mark_source_result(
    conn, source_id: str, *, ok: bool,
    newest_item: datetime | None = None, error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        if ok:
            # A success clears the failure count, which also ends any back-off
            cur.execute(
                """
                UPDATE sources SET
                    last_poll_at = now(),
                    last_success_at = now(),
                    last_item_at = GREATEST(COALESCE(last_item_at, 'epoch'), %s),
                    consecutive_failures = 0,
                    last_error = NULL
                WHERE id = %s
                """,
                (newest_item, source_id),
            )
        else:
            cur.execute(
                """
                UPDATE sources SET
                    last_poll_at = now(),
                    consecutive_failures = consecutive_failures + 1,
                    last_error = %s
                WHERE id = %s
                """,
                (error[:500] if error else None, source_id),
            )


def record_run(conn, job: str, stats: dict, *, ok: bool) -> None:
    import json
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runs (job, finished_at, sources_total, sources_ok,
                              sources_failed, items_seen, items_new, ok, detail)
            VALUES (%s, now(), %s, %s, %s, %s, %s, %s, %s)
            """,
            (job, stats.get("sources_total"), stats.get("sources_ok"),
             stats.get("sources_failed"), stats.get("items_seen"),
             stats.get("items_new"), ok, json.dumps(stats.get("detail", {}))),
        )


def unhealthy_sources(conn, *, fail_threshold: int = 3, stale_days: int = 14):
    """Sources that look broken. Feeds the website's pipeline health panel."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, tier, consecutive_failures, last_item_at, last_error
            FROM sources
            WHERE enabled
              AND (consecutive_failures >= %s
                   OR last_item_at IS NULL
                   OR last_item_at < now() - make_interval(days => %s))
            ORDER BY tier, id
            """,
            (fail_threshold, stale_days),
        )
        return cur.fetchall()
