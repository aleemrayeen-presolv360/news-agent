"""Configuration and the week-window maths.

The week window is the most bug-prone part of this project, so it lives
here on its own and is covered by scripts/selftest.py.

Week = Sunday 00:00 IST  ->  Friday 12:00 IST (noon).
Digest publishes Friday 12:01 IST.
Addendum covers Friday 12:00 IST -> Saturday 00:00 IST.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Local runs read secrets from .env; GitHub Actions passes them as env vars.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------- secrets


def env(key: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(
            f"Missing required environment variable {key!r}. "
            "Copy .env.example to .env for local runs, or add it to "
            "GitHub Settings -> Secrets and variables -> Actions."
        )
    return val or ""


def supabase_settings() -> tuple[str, str]:
    """The website's Supabase URL and anon key, used to read approved source requests.

    The anon key is public (the website ships it), so by default both are read
    from frontend/js/config.js and no extra secret is needed. Env vars override.
    """
    url, key = env("SUPABASE_URL"), env("SUPABASE_ANON_KEY")
    if url and key:
        return url, key
    try:
        js = (Path(__file__).parent.parent / "frontend" / "js" / "config.js").read_text(encoding="utf-8")
    except OSError:
        return "", ""
    found = dict(re.findall(r"(SUPABASE_URL|SUPABASE_ANON_KEY):\s*'([^']*)'", js))
    return url or found.get("SUPABASE_URL", ""), key or found.get("SUPABASE_ANON_KEY", "")


# ---------------------------------------------------------------- tuning

# How far back a feed item may be and still count as new on first sight.
# Guards against a feed that suddenly republishes its whole archive.
MAX_ITEM_AGE_DAYS = 21

# A source's first successful fetch only keeps this much of its feed. Older
# items are stored as already seen, so adding a source shows its last day of
# news instead of queueing weeks of back catalogue ahead of today's stories.
FIRST_FETCH_HOURS = 24

# Per-feed network timeout, seconds.
FEED_TIMEOUT = 20.0

# Feeds fetched concurrently. Keep modest — some publishers rate-limit.
FEED_CONCURRENCY = 8

# Several publishers 403 the default python-httpx UA.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Scoring thresholds (score = source tier points + novelty + impact + relevance).
SCORE_BREAKING = 85   # Breaking: red label, and a banner on the website until read
SCORE_MAJOR = 70      # headline section; below this a week is "no big news"
SCORE_NOTABLE = 55    # collapsed toggle
MAX_ITEMS_PER_DIGEST = 12   # Notion digest only; the website shows everything
MAX_MINOR_ITEMS = 5         # Notion digest only

# The domain the scoring model puts each story in, and the website category
# (group) it belongs to. Keep in step with DOMAINS in frontend/js/config.js.
DOMAINS = {
    "ai": "tech", "chips": "tech", "mobility": "tech", "space": "tech",
    "health": "tech", "energy": "tech", "robotics": "tech", "fintech": "tech",
    "security": "tech", "consumer": "tech", "science": "tech", "policy": "tech",
    "legal_india": "legal", "business": "market", "other": "tech",
}

# Only articles published in the last PROCESS_DAYS are downloaded and scored,
# so an old backlog never crowds out this week's news.
PROCESS_DAYS = 14

# How far back frontend/data.js goes.
WEBSITE_DAYS = 30

# Embedding model — 384-dim, 67 MB, MIT licence.
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384

# Clustering: same event if cosine >= this AND >= 1 shared entity.
CLUSTER_COSINE = 0.86
CLUSTER_WINDOW_HOURS = 72


# ---------------------------------------------------------------- window


@dataclass(frozen=True)
class Window:
    start: datetime   # Sunday 00:00 IST, inclusive
    end: datetime     # Friday 12:00 IST, exclusive
    label: str        # "Week 41 - 04-09 Oct 2026"

    def __contains__(self, ts: datetime) -> bool:
        return self.start <= ts.astimezone(IST) < self.end


def week_window(now: datetime | None = None) -> Window:
    """The digest window containing `now`.

    Python's weekday(): Monday=0 ... Sunday=6.
    (weekday() + 1) % 7 is therefore "days since the most recent Sunday".
    """
    now = (now or datetime.now(IST)).astimezone(IST)
    days_since_sunday = (now.weekday() + 1) % 7
    start = (now - timedelta(days=days_since_sunday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = (start + timedelta(days=5)).replace(hour=12)  # Friday 12:00
    label = (
        f"Week {start.isocalendar().week} - "
        f"{start:%d}-{(end - timedelta(days=0)):%d %b %Y}"
    )
    return Window(start=start, end=end, label=label)


def addendum_window(now: datetime | None = None) -> Window:
    """Friday 12:00 IST -> Saturday 00:00 IST, the gap the digest misses.

    Called from the Saturday 08:00 IST job, so `now` is Saturday and the
    containing week window is still the one that just closed.
    """
    wk = week_window(now)
    start = wk.end                                   # Friday 12:00
    end = (wk.start + timedelta(days=6))             # Saturday 00:00
    return Window(start=start, end=end, label=wk.label + " (late breaking)")


def retention_cutoff(now: datetime | None = None, days: int = 30) -> datetime:
    """Items published before this are archived from Notion unless saved."""
    now = (now or datetime.now(IST)).astimezone(IST)
    return now - timedelta(days=days)
