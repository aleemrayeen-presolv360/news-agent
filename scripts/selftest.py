"""Offline self-test. No network, no database.

    python scripts/selftest.py

Covers the two things most likely to be quietly wrong:
  1. URL canonicalisation  -> wrong = duplicate stories in your digest
  2. The IST week window   -> wrong = digest covers the wrong days
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser  # noqa: E402

from agent.config import IST, addendum_window, week_window  # noqa: E402
from agent.normalize import (  # noqa: E402
    canonical_url, clean_text, normalize_entry, normalize_hf_paper,
)
from agent.sources import (  # noqa: E402
    ARXIV_SOURCES, PAPER_SOURCES, SOURCES, by_id, enabled_sources,
)
from agent.extract import (  # noqa: E402
    ExtractResult, _extract_text, _PAYWALL_SIGNALS, get_unextracted_items, update_extracted,
)
from agent.embed import get_unembedded_items  # noqa: E402
from agent.db import backed_off_source_ids  # noqa: E402
from agent.trends import parse_picks  # noqa: E402
from agent.config import DOMAINS  # noqa: E402
from agent.publish_static import item_to_dict, split_by_label  # noqa: E402
from agent.ingest import gap_fill_rows, needs_gap_fill, split_first_fetch  # noqa: E402
from agent.triage import check_arxiv_gate  # noqa: E402
import agent.score as score_mod  # noqa: E402

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

# ------------------------------------------------------------ funnel
print("\nfunnel")

check("every arXiv feed is a paper source",
      {s.id for s in SOURCES if s.id.startswith("arxiv")} <= set(ARXIV_SOURCES), True)
check("paper sources all exist in the source list",
      all(by_id(sid) for sid in PAPER_SOURCES), True)
check("triage gates every arXiv source",
      [check_arxiv_gate(sid, "u", None, {})[0] for sid in ARXIV_SOURCES], [False] * len(ARXIV_SOURCES))
check("triage lets news through the arXiv gate",
      check_arxiv_gate("techcrunch_ai", "u", None, {})[0], True)

groups = split_by_label([{"score": s} for s in (97, 85, 84, 70, 69, 55, 54, 10)])
check("website groups: 85+ breaking", [i["score"] for i in groups["breaking"]], [97, 85])
check("website groups: 70-84 major", [i["score"] for i in groups["major"]], [84, 70])
check("website groups: 55-69 notable", [i["score"] for i in groups["notable"]], [69, 55])
many = split_by_label([{"score": 75}] * 40 + [{"score": 60}] * 20)
check("website groups are not capped", (len(many["major"]), len(many["notable"])), (40, 20))

# ------------------------------------------------------------ groq rate limits
print("\ngroq rate limits")


class _FakeResp:
    def __init__(self, status, retry_after=None):
        self.status_code = status
        self.headers = {"retry-after": retry_after} if retry_after else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


def _fake_groq(responses):
    """Run _call_groq against canned responses; returns (result or error, sleeps)."""
    queue, sleeps = list(responses), []
    score_mod._groq_exhausted = False
    with mock.patch.object(score_mod.httpx, "post", lambda *a, **k: queue.pop(0)), \
         mock.patch.object(score_mod.time, "sleep", sleeps.append), \
         mock.patch.dict(os.environ, {"GROQ_API_KEY": "test"}):
        try:
            return score_mod._call_groq("p"), sleeps
        except Exception as e:  # noqa: BLE001
            return type(e).__name__, sleeps


check("waits out a per-minute 429, then succeeds",
      _fake_groq([_FakeResp(429, "7"), _FakeResp(200)]), ("ok", [8.0]))
check("daily quota gone: gives up at once, no waiting",
      _fake_groq([_FakeResp(429, "3600")]), ("GroqQuotaExhausted", []))
try:  # flag is still set from the call above; no request may be made now
    with mock.patch.object(score_mod.httpx, "post", side_effect=AssertionError("called Groq")):
        score_mod._call_groq("p")
    skipped = "called"
except score_mod.GroqQuotaExhausted:
    skipped = "skipped"
check("after daily quota is gone, later calls skip Groq", skipped, "skipped")
score_mod._groq_exhausted = False

# ------------------------------------------------------------ domains
print("\ndomains")

parsed = score_mod._parse_score_response(
    '{"domain": "Mobility", "novelty": 30, "impact": 10, "relevance": 15}', "D")
check("domain read case-insensitively", parsed["domain"], "mobility")
check("dimension scores capped at 25", parsed["score"], 12 + 25 + 10 + 15)
check("unknown domain becomes other",
      score_mod._parse_score_response('{"domain": "sports", "novelty": 1}', "A")["domain"], "other")
check("missing domain becomes other",
      score_mod._parse_score_response('{"novelty": 1}', "A")["domain"], "other")


def _domain_for(title, domain):
    return score_mod._result({"id": 1, "title": title}, {**parsed, "domain": domain}, "groq").domain


check("legal_india kept for Indian courts", _domain_for("Delhi High Court rules on ODR", "legal_india"), "legal_india")
check("legal_india dropped for a US court case", _domain_for("Judge dismisses lawsuit in Boston", "legal_india"), "other")

row = {"headline": "h", "score": 70, "source_name": "s", "source_url": "u", "one_liner": "o",
       "topics": [], "entities": [], "market_impact": None, "cluster_count": 1, "published_at": None}
check("website gets domain and category",
      [(d["domain"], d["category"]) for d in map(item_to_dict, [
          {**row, "score_breakdown": {"domain": "space"}},
          {**row, "score_breakdown": {"domain": "legal_india"}},
          {**row, "score_breakdown": {"domain": "business"}},
          {**row, "score_breakdown": None}])],
      [("space", "tech"), ("legal_india", "legal"), ("business", "market"), (None, None)])

_gn_row = {**row, "headline": "eMudhra key flaw explained - MediaNama", "source_name": "Trending: emudhra",
           "source_url": "https://news.google.com/rss/articles/x", "source_id": "trend_4"}
_d = item_to_dict(_gn_row)
check("Google News story shows its publisher", (_d["headline"], _d["source"]),
      ("eMudhra key flaw explained", "MediaNama"))
check("trend-watch story is trending", _d["trending"], True)
check("story in 3 sources is trending", item_to_dict({**row, "cluster_count": 3})["trending"], True)
check("ordinary story is not trending", item_to_dict({**row, "source_id": "electrek"})["trending"], False)

# ------------------------------------------------------------ trends
print("\ntrends")

_picks = parse_picks('Sure: [{"term": "x", "domain": "Security", "query": " eMudhra  Key Flaw ", "why": "w"},'
                     ' {"term": "Meta fine", "domain": "legal_india", "query": "meta new mexico penalty", "why": "US case"},'
                     ' {"term": "dup", "domain": "ai", "query": "emudhra key flaw"},'
                     ' {"term": "long", "domain": "ai", "query": "one two three four five six seven"}]', 5)
check("trend picks cleaned", [(p["query"], p["domain"]) for p in _picks],
      [("emudhra key flaw", "security"), ("meta new mexico penalty", "policy")])
check("trend picks capped", len(parse_picks('[{"query": "a"}, {"query": "b"}, {"query": "c"}]', 2)), 2)
check("unparseable trend reply means no picks", parse_picks("no idea", 3), [])

# ------------------------------------------------------------ pipeline queues
print("\npipeline queues")

_reply = '{"domain": "space", "novelty": 10, "impact": 10, "relevance": 10}'
_item = {"id": 1, "title": "t", "source_name": "s", "tier": "A"}
with mock.patch.object(score_mod, "_call_groq", return_value=_reply):
    check("Groq score records its model", score_mod.score_item(_item).model, "groq")
with mock.patch.object(score_mod, "_call_groq", side_effect=RuntimeError("429")), \
     mock.patch.object(score_mod, "_call_cloudflare", return_value=_reply):
    check("fallback score records cloudflare", score_mod.score_item(_item).model, "cloudflare")


class _FakeCur:
    def __init__(self):
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append((" ".join(q.split()), params))

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCur()

    def cursor(self):
        return self.cur


_c = _FakeConn()
update_extracted(_c, [ExtractResult(url="https://x/1", text=None, paywalled=False, error="timeout")])
check("failed download marked as tried", _c.cur.sql[0][0].startswith("UPDATE raw_items SET article_text = ''"), True)
_c = _FakeConn()
backed_off_source_ids(_c)
check("failing sources back off for a day",
      ("consecutive_failures >=" in _c.cur.sql[0][0], _c.cur.sql[0][1]), (True, (3, 24)))

_ok = {"scored": 200, "failed": 0, "cerebras": 0, "cloudflare": 0}
check("no warning on a healthy run", score_mod.quota_warning(_ok, 600, False, 40), None)
check("warns when Groq runs low", "only 90 Groq calls" in score_mod.quota_warning(_ok, 90, False, 40), True)
check("warns when the quota ran out", "ran out" in score_mod.quota_warning(_ok, 0, True, 40), True)
check("warns on fallback scores",
      "Cloudflare 3" in score_mod.quota_warning({**_ok, "cloudflare": 3}, 600, False, 40), True)

for _fn in (get_unextracted_items, get_unembedded_items):
    _c = _FakeConn()
    _fn(_c, 10)
    _q, _params = _c.cur.sql[0]
    check(f"{_fn.__name__}: news first, last PROCESS_DAYS only",
          ("ORDER BY (" in _q and "make_interval" in _q, list(PAPER_SOURCES) in _params), (True, True))

# ------------------------------------------------------------ first fetch
print("\nfirst fetch")

_now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
_rows = [
    {"source_id": "new_feed", "published_at": datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)},   # 11h old
    {"source_id": "new_feed", "published_at": datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)},  # 2 days old
    {"source_id": "old_feed", "published_at": datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)},  # 11 days old
]
_keep, _seen = split_first_fetch(_rows, {"new_feed"}, _now)
check("new source keeps its last 24h", [r["published_at"].day for r in _keep if r["source_id"] == "new_feed"], [21])
check("new source's older items stored as seen", [r["published_at"].day for r in _seen], [19])
check("known sources unaffected", [r["source_id"] for r in _keep if r["published_at"].day == 10], ["old_feed"])
check("no first-time sources: everything kept", len(split_first_fetch(_rows, set(), _now)[0]), 3)

_busy = by_id("electrek")
_recent = [{"title": "Tesla ships Cybercab", "published_at": datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)}]
_older = _recent + [{"title": "x", "published_at": datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)}]
check("short feed of a new source gets a Google News gap fill", needs_gap_fill(_busy, _recent, _now), True)
check("feed reaching back 24h needs no gap fill", needs_gap_fill(_busy, _older, _now), False)
check("Google News sources are never gap-filled",
      needs_gap_fill(next(s for s in SOURCES if "news.google.com" in s.url), _recent, _now), False)
_gn = [{"title": "Tesla ships Cybercab - Electrek", "source_id": "gn"},
       {"title": "Rivian cuts prices - Electrek", "source_id": "gn"}]
check("gap fill drops stories the feed already has and keeps the source",
      [(r["title"], r["source_id"]) for r in gap_fill_rows(_busy, _recent, _gn)],
      [("Rivian cuts prices", "electrek")])

check("source ids are unique", len({s.id for s in SOURCES}), len(SOURCES))
check("Google News feeds are encoded and limited to 7 days",
      all(" " not in s.url and "when%3A7d" in s.url for s in SOURCES if "news.google.com" in s.url), True)

js_config = (Path(__file__).resolve().parent.parent / "frontend/js/config.js").read_text(encoding="utf-8")
js_domains = re.search(r"DOMAINS:\s*\{(.*?)\}", js_config, re.S).group(1)
check("website config names every domain but other",
      set(re.findall(r"^\s*(\w+):", js_domains, re.M)), set(DOMAINS) - {"other"})

print(f"\n{'=' * 50}\n  {PASS} passed, {FAIL} failed\n{'=' * 50}")
print(f"  enabled sources : {len(enabled_sources())}")
print(f"  known gaps      : {len([s for s in SOURCES if not s.enabled])}"
      "  (no working feed; need RSSHub or Exa)\n")
sys.exit(1 if FAIL else 0)
