"""Offline self-test. No network, no database.

    python scripts/selftest.py

Covers the two things most likely to be quietly wrong:
  1. URL canonicalisation  -> wrong = duplicate stories in your digest
  2. The IST week window   -> wrong = digest covers the wrong days
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser  # noqa: E402

from agent.config import IST, addendum_window, week_window  # noqa: E402
from agent.normalize import (  # noqa: E402
    canonical_url, clean_text, normalize_entry, normalize_hf_paper,
)
from agent.sources import SOURCES, by_id, enabled_sources  # noqa: E402
from agent.extract import _extract_text, _PAYWALL_SIGNALS  # noqa: E402

PASS, FAIL = 0, 0


def check(label: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


# ------------------------------------------------------- canonical URLs
print("\ncanonical_url")
check("strips utm params",
      canonical_url("https://openai.com/news/x?utm_source=rss&utm_medium=feed"),
      "https://openai.com/news/x")
check("strips www and forces https",
      canonical_url("http://www.technologyreview.com/a/b/"),
      "https://technologyreview.com/a/b")
check("drops fragment",
      canonical_url("https://news.mit.edu/2026/story#section-2"),
      "https://news.mit.edu/2026/story")
check("keeps meaningful query, sorted",
      canonical_url("https://example.com/p?b=2&a=1&fbclid=xyz"),
      "https://example.com/p?a=1&b=2")
check("arxiv abs/pdf/html collapse to one id",
      canonical_url("https://arxiv.org/pdf/2510.01234v3"),
      "https://arxiv.org/abs/2510.01234")
check("arxiv abs form is stable",
      canonical_url("http://www.arxiv.org/abs/2510.01234"),
      "https://arxiv.org/abs/2510.01234")
check("two trackers on the same story collapse",
      canonical_url("https://a.com/x?utm_source=hn")
      == canonical_url("https://a.com/x?utm_source=twitter&gclid=1"),
      True)
check("empty stays empty", canonical_url(""), "")

# --------------------------------------------------------- week window
print("\nweek_window (Sunday 00:00 IST -> Friday 12:00 IST)")

# Thursday 8 Oct 2026, mid-week
w = week_window(datetime(2026, 10, 8, 15, 0, tzinfo=IST))
check("thu -> starts Sun 4 Oct 00:00", w.start.isoformat(), "2026-10-04T00:00:00+05:30")
check("thu -> ends Fri 9 Oct 12:00", w.end.isoformat(), "2026-10-09T12:00:00+05:30")

# Sunday itself must start that same day, not a week earlier
w = week_window(datetime(2026, 10, 4, 0, 30, tzinfo=IST))
check("sun 00:30 -> same-day start", w.start.isoformat(), "2026-10-04T00:00:00+05:30")

# Friday 12:01, the moment the digest runs
w = week_window(datetime(2026, 10, 9, 12, 1, tzinfo=IST))
check("fri 12:01 -> window already closed",
      w.end.isoformat(), "2026-10-09T12:00:00+05:30")
check("fri 12:01 is NOT in the window",
      datetime(2026, 10, 9, 12, 1, tzinfo=IST) in w, False)
check("fri 11:59 IS in the window",
      datetime(2026, 10, 9, 11, 59, tzinfo=IST) in w, True)
check("sat is not in the window",
      datetime(2026, 10, 10, 9, 0, tzinfo=IST) in w, False)

# The Friday-afternoon gap -- drawback 1
a = addendum_window(datetime(2026, 10, 10, 8, 0, tzinfo=IST))  # Sat 08:00
check("addendum starts Fri 12:00", a.start.isoformat(), "2026-10-09T12:00:00+05:30")
check("addendum ends Sat 00:00", a.end.isoformat(), "2026-10-10T00:00:00+05:30")
check("fri 18:00 news lands in the addendum",
      datetime(2026, 10, 9, 18, 0, tzinfo=IST) in a, True)
check("fri 23:59 news lands in the addendum",
      datetime(2026, 10, 9, 23, 59, tzinfo=IST) in a, True)

# UTC input must be converted, not assumed
w = week_window(datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc))  # 01:30 IST Fri
check("utc input converts to IST correctly",
      w.start.isoformat(), "2026-10-04T00:00:00+05:30")

# ----------------------------------------------------- feed parsing
print("\nfeed parsing")
FIXTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test</title>
  <item>
    <title>Lab demonstrates new photonic compute architecture</title>
    <link>https://example.edu/news/photonic?utm_source=rss</link>
    <pubDate>Mon, 05 Oct 2026 10:00:00 +0000</pubDate>
    <description>&lt;p&gt;A &lt;b&gt;new&lt;/b&gt; approach    to optical compute.&lt;/p&gt;</description>
  </item>
  <item>
    <title>Duplicate of the above via another feed</title>
    <link>https://example.edu/news/photonic?utm_medium=twitter</link>
    <pubDate>Mon, 05 Oct 2026 11:00:00 +0000</pubDate>
  </item>
  <item>
    <title>No link here</title>
    <pubDate>Mon, 05 Oct 2026 12:00:00 +0000</pubDate>
  </item>
</channel></rss>"""

parsed = feedparser.parse(FIXTURE)
src = by_id("mit_ai")
rows = [normalize_entry(e, src) for e in parsed.entries]
good = [r for r in rows if r]

check("3 entries parsed", len(parsed.entries), 3)
check("linkless entry dropped", len(good), 2)
check("html stripped from summary",
      good[0]["feed_summary"], "A new approach to optical compute.")
check("published parsed as tz-aware",
      good[0]["published_at"].isoformat(), "2026-10-05T10:00:00+00:00")
check("the two tracker variants share one canonical url",
      good[0]["url_canonical"] == good[1]["url_canonical"], True)

seen = {r["url_canonical"]: r for r in good}
check("in-batch dedup leaves 1 row", len(seen), 1)

paper = normalize_hf_paper(
    {"paper": {"id": "2510.09999", "title": "A paper", "upvotes": 42,
               "summary": "Abstract here"},
     "publishedAt": "2026-10-06T00:00:00.000Z"}
)
check("hf paper -> arxiv canonical url",
      paper["url_canonical"], "https://arxiv.org/abs/2510.09999")
check("upvotes preserved for the signal gate",
      paper["feed_summary"].startswith("[upvotes:42]"), True)

check("clean_text truncates", len(clean_text("x" * 5000, 100)), 100)

# ------------------------------------------------------------ sources
print("\nsources")
ids = [s.id for s in SOURCES]
check("no duplicate source ids", len(ids), len(set(ids)))
check("every enabled source has a url",
      all(s.url for s in enabled_sources()), True)
check("tiers are A-D only",
      set(s.tier for s in SOURCES) <= {"A", "B", "C", "D"}, True)
check("disabled sources carry an explanatory note",
      all(s.note for s in SOURCES if not s.enabled), True)
check("arxiv polled per-category, never combined",
      all("+" not in s.url for s in SOURCES if "arxiv" in s.id), True)

# ------------------------------------------------------------ extract
print("\nextract")

# Test paywall detection
paywall_html = b"<html><body><p>Subscribe to continue reading this article. Premium content.</p></body></html>"
text, paywalled = _extract_text(paywall_html, "https://example.com/article")
check("paywall detected in short content", paywalled, True)

# Test normal extraction
normal_html = b"""<html><body>
<article>
<h1>Scientists Discover New AI Architecture</h1>
<p>Researchers at MIT have developed a groundbreaking new neural network architecture
that significantly improves performance on language tasks. The new approach combines
transformer attention mechanisms with novel memory systems.</p>
<p>The team published their findings in Nature, demonstrating a 40% improvement
in efficiency compared to existing models. This breakthrough could lead to more
accessible AI systems that require less computational resources.</p>
</article>
</body></html>"""
text2, paywalled2 = _extract_text(normal_html, "https://example.com/article")
check("normal article not marked as paywall", paywalled2, False)
check("text extracted from normal article", text2 is not None and len(text2) > 50, True)

# Test paywall signals list
check("paywall signals defined", len(_PAYWALL_SIGNALS) > 5, True)

print(f"\n{'=' * 50}\n  {PASS} passed, {FAIL} failed\n{'=' * 50}")
print(f"  enabled sources : {len(enabled_sources())}")
print(f"  known gaps      : {len([s for s in SOURCES if not s.enabled])}"
      "  (no working feed; need RSSHub or Exa)\n")
sys.exit(1 if FAIL else 0)
