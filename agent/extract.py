"""Phase 2a: Extract full article text.

Uses trafilatura to fetch and extract main content from URLs.
Handles paywalls, timeouts, and rate limiting gracefully.

    python -m agent.extract              # process unextracted items
    python -m agent.extract --dry-run    # fetch but don't update DB
    python -m agent.extract --limit 10   # only process 10 items
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

import httpx
import trafilatura

from .config import FEED_TIMEOUT, USER_AGENT

# Patterns that indicate a paywall or login wall
_PAYWALL_SIGNALS = (
    "subscribe to continue",
    "subscription required",
    "sign in to read",
    "create a free account",
    "members-only",
    "premium content",
    "paywall",
    "register to continue",
)


@dataclass
class ExtractResult:
    url: str
    text: str | None
    paywalled: bool
    error: str | None


async def _fetch_html(client: httpx.AsyncClient, url: str) -> tuple[bytes | None, str | None]:
    """Fetch raw HTML, return (content, error)."""
    try:
        resp = await client.get(url, timeout=FEED_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.content, None
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPStatusError as e:
        return None, f"http_{e.response.status_code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:100]}"


def _extract_text(html: bytes, url: str) -> tuple[str | None, bool]:
    """Extract main content, return (text, is_paywalled)."""
    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
            favor_precision=True,
        )
    except Exception:  # noqa: BLE001
        return None, False

    if not text:
        return None, False

    # Check for paywall signals
    text_lower = text.lower()
    paywalled = any(signal in text_lower for signal in _PAYWALL_SIGNALS)

    # If text is suspiciously short, might be paywalled
    if len(text) < 200 and not paywalled:
        paywalled = True

    return text, paywalled


async def extract_one(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> ExtractResult:
    """Extract article text from a single URL."""
    async with sem:
        html, error = await _fetch_html(client, url)
        if error:
            return ExtractResult(url=url, text=None, paywalled=False, error=error)

        # trafilatura is sync, run in thread pool
        loop = asyncio.get_event_loop()
        text, paywalled = await loop.run_in_executor(None, _extract_text, html, url)

        if text is None and not paywalled:
            return ExtractResult(url=url, text=None, paywalled=False, error="extraction_failed")

        return ExtractResult(url=url, text=text, paywalled=paywalled, error=None)


async def extract_batch(urls: list[str], concurrency: int = 5) -> list[ExtractResult]:
    """Extract article text from multiple URLs concurrently."""
    sem = asyncio.Semaphore(concurrency)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [extract_one(client, url, sem) for url in urls]
        return await asyncio.gather(*tasks)


def get_unextracted_items(conn, limit: int | None = None) -> list[dict]:
    """Get items that need text extraction."""
    with conn.cursor() as cur:
        query = """
            SELECT id, url_canonical, url_original, title, feed_summary
            FROM raw_items
            WHERE article_text IS NULL
              AND paywalled = false
            ORDER BY published_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        return cur.fetchall()


def update_extracted(conn, results: list[ExtractResult]) -> dict:
    """Update raw_items with extracted text."""
    stats = {"extracted": 0, "paywalled": 0, "failed": 0}

    with conn.cursor() as cur:
        for r in results:
            if r.text:
                cur.execute(
                    """
                    UPDATE raw_items
                    SET article_text = %s, paywalled = %s
                    WHERE url_canonical = %s
                    """,
                    (r.text[:50000], r.paywalled, r.url),  # cap at 50k chars
                )
                stats["extracted"] += 1
                if r.paywalled:
                    stats["paywalled"] += 1
            elif r.paywalled:
                cur.execute(
                    "UPDATE raw_items SET paywalled = true WHERE url_canonical = %s",
                    (r.url,),
                )
                stats["paywalled"] += 1
            else:
                stats["failed"] += 1

    return stats


def run(dry_run: bool = False, limit: int | None = None) -> int:
    """Main entry point."""
    if dry_run:
        # Dry run: just test extraction on a few sample URLs
        sample_urls = [
            "https://news.mit.edu/2024/ai-model-can-predict-breast-cancer-risk-0508",
            "https://openai.com/index/hello-gpt-4o/",
        ]
        if limit:
            sample_urls = sample_urls[:limit]

        print(f"\n{'=' * 60}")
        print("  DRY RUN - testing extraction on sample URLs")
        print(f"{'=' * 60}\n")

        results = asyncio.run(extract_batch(sample_urls))
        for r in results:
            status = "✓" if r.text else ("paywall" if r.paywalled else f"✗ {r.error}")
            text_preview = (r.text[:100] + "...") if r.text else "N/A"
            print(f"  {status:20} {r.url[:50]}")
            if r.text:
                print(f"                       {text_preview}\n")
        return 0

    from . import db

    with db.connect() as conn:
        items = get_unextracted_items(conn, limit)
        if not items:
            print("extract: no items need extraction")
            return 0

        print(f"extract: processing {len(items)} items...")

        urls = [item["url_canonical"] for item in items]
        results = asyncio.run(extract_batch(urls))

        # Map results by URL for update
        result_map = {r.url: r for r in results}
        ordered_results = [result_map[url] for url in urls]

        stats = update_extracted(conn, ordered_results)

        print(
            f"extract: {stats['extracted']} extracted, "
            f"{stats['paywalled']} paywalled, {stats['failed']} failed"
        )

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract full article text from URLs.")
    ap.add_argument("--dry-run", action="store_true", help="test extraction without DB")
    ap.add_argument("--limit", type=int, help="only process N items")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
