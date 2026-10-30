"""URL canonicalisation and feed-entry normalisation.

Canonical URL is the dedup key. Getting it wrong is the difference between
"600 items/week" and "600 items/week plus 300 duplicates of the same story
with different tracking params".
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser as dateparser

# Tracking params to strip. Order-insensitive; everything else is kept
# because some sites genuinely route content through query strings.
_JUNK_PARAM_RE = re.compile(
    r"^(utm_[a-z_]+|fbclid|gclid|gbraid|wbraid|mc_cid|mc_eid|ref|ref_src|"
    r"source|cmpid|cmp|icid|ncid|sh|share|__twitter_impression|guccounter|"
    r"guce_referrer\w*|_hsenc|_hsmi|igshid|si|spm|at_medium|at_campaign)$",
    re.I,
)

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", re.I)


def canonical_url(url: str) -> str:
    """Stable dedup key for a URL.

    - lowercase scheme+host, drop 'www.'
    - force https (same article, same story)
    - strip tracking params, sort the rest
    - drop the fragment
    - drop a trailing slash
    - collapse arXiv abs/pdf/html + version to one id
    """
    if not url:
        return ""
    url = url.strip()

    m = _ARXIV_RE.search(url)
    if m:
        return f"https://arxiv.org/abs/{m.group(1)}"

    parts = urlsplit(url)
    scheme = "https"
    netloc = (parts.hostname or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if parts.port and parts.port not in (80, 443):
        netloc = f"{netloc}:{parts.port}"

    query = urlencode(
        sorted(
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if not _JUNK_PARAM_RE.match(k)
        )
    )

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    return urlunsplit((scheme, netloc, path, query, ""))


def parse_date(value, fallback: datetime | None = None) -> datetime:
    """Best-effort published date, always timezone-aware UTC."""
    if value is None:
        return fallback or datetime.now(timezone.utc)
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (tuple, list)) and len(value) >= 6:
        # feedparser's published_parsed struct_time, always UTC
        dt = datetime(*value[:6], tzinfo=timezone.utc)
    else:
        try:
            dt = dateparser.parse(str(value))
        except (ValueError, TypeError, OverflowError):
            return fallback or datetime.now(timezone.utc)
    if dt is None:
        return fallback or datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str | None, limit: int = 2000) -> str:
    """Strip HTML from a feed summary and squeeze whitespace."""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">")
        .replace("&#39;", "'").replace("&quot;", '"')
    )
    return _WS_RE.sub(" ", text).strip()[:limit]


def normalize_entry(entry, source) -> dict | None:
    """feedparser entry -> our row shape. None if unusable."""
    link = (
        entry.get("link")
        or next((l.get("href") for l in entry.get("links", []) if l.get("href")), "")
    )
    title = clean_text(entry.get("title"), 500)
    if not link or not title:
        return None

    published = parse_date(
        entry.get("published_parsed") or entry.get("updated_parsed")
        or entry.get("published") or entry.get("updated")
    )
    summary = clean_text(
        entry.get("summary")
        or (entry.get("content", [{}])[0].get("value") if entry.get("content") else "")
    )

    return {
        "url_canonical": canonical_url(link),
        "url_original": link,
        "title": title,
        "source_id": source.id,
        "published_at": published,
        "feed_summary": summary,
    }


def normalize_cisa_kev(vuln: dict, source) -> dict | None:
    """One entry of CISA's Known Exploited Vulnerabilities catalogue -> our row shape.

    Each entry is a flaw attackers are using right now. It links to the CVE's NVD page,
    which describes it in full.
    """
    cve = vuln.get("cveID")
    name = clean_text(vuln.get("vulnerabilityName"), 400)
    if not cve or not name:
        return None
    ransomware = " Used in ransomware campaigns." if vuln.get("knownRansomwareCampaignUse") == "Known" else ""
    return {
        "url_canonical": f"https://nvd.nist.gov/vuln/detail/{cve}",
        "url_original": f"https://nvd.nist.gov/vuln/detail/{cve}",
        "title": f"Actively exploited: {name} ({cve})",
        "source_id": source.id,
        "published_at": parse_date(vuln.get("dateAdded")),
        "feed_summary": clean_text(
            f"CISA added {cve} ({vuln.get('vendorProject', '')} {vuln.get('product', '')}) to its list of "
            f"vulnerabilities attackers are exploiting. {vuln.get('shortDescription', '')}{ransomware} "
            f"US agencies must fix it by {vuln.get('dueDate', 'the due date')}."
        ),
    }


def normalize_newsdata(article: dict, source) -> dict | None:
    """One NewsData.io article -> our row shape.

    The title gets " - Outlet" appended, like Google News titles, so the website shows the
    real publisher instead of the NewsData search (publish_static.display_names).
    """
    link = article.get("link")
    title = clean_text(article.get("title"), 450)
    if not link or not title or article.get("duplicate"):
        return None
    outlet = clean_text(article.get("source_name") or article.get("source_id"), 60)
    return {
        "url_canonical": canonical_url(link),
        "url_original": link,
        "title": f"{title} - {outlet}" if outlet else title,
        "source_id": source.id,
        # NewsData dates are UTC without a zone: "2026-10-30 06:12:45"
        "published_at": parse_date(article.get("pubDate")),
        "feed_summary": clean_text(article.get("description")),
    }


def normalize_hf_paper(paper: dict) -> dict | None:
    """Hugging Face Daily Papers JSON -> our row shape.

    Keeps the upvote count in feed_summary so the arXiv signal gate
    in triage.py can read it without another request.
    """
    inner = paper.get("paper") or paper
    arxiv_id = inner.get("id")
    title = clean_text(inner.get("title"), 500)
    if not arxiv_id or not title:
        return None
    upvotes = inner.get("upvotes") or 0
    return {
        "url_canonical": f"https://arxiv.org/abs/{arxiv_id}",
        "url_original": f"https://huggingface.co/papers/{arxiv_id}",
        "title": title,
        "source_id": "hf_papers",
        "published_at": parse_date(paper.get("publishedAt")),
        "feed_summary": f"[upvotes:{upvotes}] " + clean_text(inner.get("summary")),
    }
