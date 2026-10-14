"""Phase 2c: Triage - rules gate + arXiv signal filter.

Two-stage filter before expensive LLM scoring:
1. Rules gate: regex filters kill obvious noise (job posts, press releases)
2. arXiv gate: only pass arXiv papers with HF Daily Papers upvotes >= threshold

    python -m agent.triage                # triage unprocessed items
    python -m agent.triage --dry-run      # test rules without DB
    python -m agent.triage --limit 50     # only process 50 items
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass

# ---------------------------------------------------------------- rules gate

# Patterns that indicate noise - these items are killed immediately
_NOISE_PATTERNS = [
    # Job postings
    (r"\b(we('re| are) hiring|job opening|career|join our team)\b", "job_posting"),
    (r"\b(apply now|open position|seeking candidates)\b", "job_posting"),
    
    # Press releases / corporate fluff
    (r"\b(is (pleased|proud|excited) to announce)\b", "press_release"),
    (r"\b(partnership with|strategic partnership)\b", "partnership_pr"),
    (r"\b(appoints|appointed|names).{0,20}(ceo|cto|cfo|chief|vp|president)\b", "executive_appointment"),
    
    # Funding announcements (usually not technical)
    (r"\b(raises|raised|secures|secured)\s+\$?\d+\s*(m|million|b|billion)\b", "funding_news"),
    (r"\b(series [a-d]|seed round|funding round)\b", "funding_news"),
    
    # Events / webinars
    (r"\b(register now|join us for|upcoming webinar|save the date)\b", "event_promo"),
    (r"\b(conference|summit|symposium).{0,30}(registration|register)\b", "event_promo"),
    
    # Listicles / roundups (low signal)
    (r"^\d+\s+(best|top|ways|tips|tools|things)\b", "listicle"),
    (r"\b(roundup|weekly digest|news roundup)\b", "roundup"),
    
    # Sponsored / promotional
    (r"\b(sponsored|promoted|advertisement)\b", "sponsored"),
    
    # Podcasts / videos without substance
    (r"^\[?(podcast|video|episode)\]?:", "media_only"),
]

# Compile patterns for efficiency
_NOISE_COMPILED = [(re.compile(p, re.I), reason) for p, reason in _NOISE_PATTERNS]

# Patterns that boost an item (override noise if matched)
_SIGNAL_PATTERNS = [
    r"\b(breakthrough|novel|state[- ]of[- ]the[- ]art|sota)\b",
    r"\b(outperforms|surpass|beats|exceeds)\b",
    r"\b(open[- ]source|released|launches)\b",
    r"\b(arxiv|paper|research|study|findings)\b",
    r"\b(gpt|llm|transformer|diffusion|neural|model)\b",
]

_SIGNAL_COMPILED = [re.compile(p, re.I) for p in _SIGNAL_PATTERNS]


@dataclass
class TriageResult:
    item_id: int
    passed: bool
    reason: str


def check_rules(title: str, summary: str | None) -> tuple[bool, str]:
    """Apply rules gate. Returns (passed, reason)."""
    text = f"{title} {summary or ''}"
    
    # Check for noise patterns
    for pattern, reason in _NOISE_COMPILED:
        if pattern.search(text):
            # Check if signal patterns override
            signal_count = sum(1 for p in _SIGNAL_COMPILED if p.search(text))
            if signal_count >= 2:
                return True, f"noise_{reason}_but_signal_override"
            return False, reason
    
    return True, "passed"


# ---------------------------------------------------------------- arXiv gate

# Minimum HF upvotes for arXiv papers to pass
ARXIV_UPVOTE_THRESHOLD = 10


def extract_hf_upvotes(feed_summary: str | None) -> int | None:
    """Extract upvote count from HF Daily Papers feed_summary.
    
    Format: "[upvotes:42] Abstract here..."
    """
    if not feed_summary:
        return None
    match = re.match(r"\[upvotes:(\d+)\]", feed_summary)
    return int(match.group(1)) if match else None


def check_arxiv_gate(source_id: str, url: str, feed_summary: str | None, 
                     hf_upvotes: dict[str, int]) -> tuple[bool, str]:
    """Apply arXiv signal gate. Returns (passed, reason).
    
    arXiv papers only pass if they appeared in HF Daily Papers with enough upvotes.
    This filters ~300 papers/day down to ~10-20 that the community cares about.
    """
    # Non-arXiv sources always pass this gate
    if source_id not in ("arxiv_ai", "arxiv_lg", "arxiv_cl"):
        return True, "not_arxiv"
    
    # Check if this paper has HF upvotes
    upvotes = hf_upvotes.get(url, 0)
    
    if upvotes >= ARXIV_UPVOTE_THRESHOLD:
        return True, f"hf_upvotes_{upvotes}"
    elif upvotes > 0:
        return False, f"hf_upvotes_{upvotes}_below_threshold"
    else:
        return False, "no_hf_signal"


# ---------------------------------------------------------------- main

def get_untriaged_items(conn, limit: int | None = None) -> list[dict]:
    """Get items that haven't been triaged yet."""
    with conn.cursor() as cur:
        query = """
            SELECT id, url_canonical, title, feed_summary, source_id
            FROM raw_items
            WHERE rules_pass IS NULL
            ORDER BY published_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        return cur.fetchall()


def get_hf_upvotes(conn) -> dict[str, int]:
    """Get HF Daily Papers upvotes for arXiv signal gate.
    
    Returns {arxiv_url: upvotes} for recent HF papers.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT url_canonical, feed_summary
            FROM raw_items
            WHERE source_id = 'hf_papers'
              AND published_at > now() - interval '14 days'
        """)
        result = {}
        for row in cur.fetchall():
            upvotes = extract_hf_upvotes(row["feed_summary"])
            if upvotes is not None:
                result[row["url_canonical"]] = upvotes
        return result


def update_triage(conn, results: list[TriageResult]) -> dict:
    """Update raw_items with triage results."""
    stats = {"passed": 0, "filtered": 0}
    
    with conn.cursor() as cur:
        for r in results:
            cur.execute(
                """
                UPDATE raw_items
                SET rules_pass = %s, rules_reason = %s
                WHERE id = %s
                """,
                (r.passed, r.reason, r.item_id),
            )
            if r.passed:
                stats["passed"] += 1
            else:
                stats["filtered"] += 1
    
    return stats


def triage_item(item: dict, hf_upvotes: dict[str, int]) -> TriageResult:
    """Run both gates on a single item."""
    # Gate 1: Rules
    passed, reason = check_rules(item["title"], item["feed_summary"])
    if not passed:
        return TriageResult(item["id"], False, reason)
    
    # Gate 2: arXiv signal
    passed, arxiv_reason = check_arxiv_gate(
        item["source_id"], 
        item["url_canonical"],
        item["feed_summary"],
        hf_upvotes
    )
    if not passed:
        return TriageResult(item["id"], False, arxiv_reason)
    
    # Both gates passed
    final_reason = reason if arxiv_reason == "not_arxiv" else f"{reason}+{arxiv_reason}"
    return TriageResult(item["id"], True, final_reason)


def run(dry_run: bool = False, limit: int | None = None) -> int:
    """Main entry point."""
    if dry_run:
        print(f"\n{'=' * 60}")
        print("  DRY RUN - testing triage rules")
        print(f"{'=' * 60}\n")

        test_cases = [
            ("OpenAI releases GPT-5 with breakthrough reasoning", None, "openai", True),
            ("We're hiring ML engineers to join our team", None, "techcrunch_ai", False),
            ("Acme Corp is pleased to announce partnership with BigCo", None, "venturebeat", False),
            ("Startup raises $50M Series B funding", None, "techcrunch_ai", False),
            ("10 Best AI Tools for Developers", None, "verge_ai", False),
            ("Novel transformer architecture outperforms GPT-4", None, "arxiv_ai", True),
            ("Company appoints new CEO John Smith", None, "reuters", False),
            ("Register now for AI Summit 2026", None, "ieee", False),
            ("Breakthrough: MIT develops new neural network", "Research paper details...", "mit_ai", True),
        ]

        print(f"  Rules patterns: {len(_NOISE_PATTERNS)} noise, {len(_SIGNAL_PATTERNS)} signal\n")
        
        for title, summary, source, expected in test_cases:
            passed, reason = check_rules(title, summary)
            status = "✓" if passed == expected else "✗ UNEXPECTED"
            icon = "✓" if passed else "✗"
            print(f"  {status} [{icon}] {title[:45]:<45} -> {reason}")

        print(f"\n  arXiv gate threshold: {ARXIV_UPVOTE_THRESHOLD} upvotes")
        
        return 0

    from . import db

    with db.connect() as conn:
        items = get_untriaged_items(conn, limit)
        if not items:
            print("triage: no items need triage")
            return 0

        print(f"triage: processing {len(items)} items...")

        # Get HF upvotes for arXiv gate
        hf_upvotes = get_hf_upvotes(conn)
        print(f"triage: loaded {len(hf_upvotes)} HF papers for arXiv gate")

        # Triage all items
        results = [triage_item(item, hf_upvotes) for item in items]

        # Update database
        stats = update_triage(conn, results)

        print(f"triage: {stats['passed']} passed, {stats['filtered']} filtered")

        # Show filter breakdown
        reasons = {}
        for r in results:
            if not r.passed:
                reasons[r.reason] = reasons.get(r.reason, 0) + 1
        if reasons:
            print("  filtered by:", ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Triage items through rules and arXiv gates.")
    ap.add_argument("--dry-run", action="store_true", help="test rules without DB")
    ap.add_argument("--limit", type=int, help="only process N items")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
