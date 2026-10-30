"""Phase 3a: LLM scoring + entity extraction.

Uses the Groq API (model in GROQ_MODEL below) to score items 0-100 and
extract entities/topics. If Groq fails: Google Gemini, then Cerebras, then
Cloudflare Workers AI, each only when its key is set.

Scoring rubric:
- Source authority: A=25, B=22, C=20, D=12
- Novelty: 0-25 (is this genuinely new?)
- Impact: 0-25 (how significant?)
- Relevance: 0-25 (should a tech-aware reader know this?)
All three are judged within the story's domain (AI, EVs, space, ...), which
the model also returns and which is stored in score_breakdown->'domain'.

    python -m agent.score                # score unscored items
    python -m agent.score --dry-run      # test scoring without DB
    python -m agent.score --limit 20     # only score 20 items
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass

import httpx
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from .config import env, DOMAINS, PROCESS_DAYS, SCORE_BREAKING, SCORE_MAJOR, SCORE_NOTABLE
from .sources import PAPER_SOURCES

# Source tier scores
TIER_SCORES = {"A": 25, "B": 22, "C": 20, "D": 12}

# Groq config
GROQ_MODEL = "qwen/qwen3.8-27b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Cloudflare Workers AI config (fallback)
CF_MODEL = "@cf/meta/llama-3-8b-instruct"
# First fallback, used only when GEMINI_API_KEY is set (free key from aistudio.google.com).
# Google's OpenAI-compatible endpoint; "gemini-flash-latest" follows Google's current Flash
# model, so a retired model name can't break scoring. GEMINI_MODEL overrides it.
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_DEFAULT_MODEL = "gemini-flash-latest"
# Optional middle fallback, used only when CEREBRAS_API_KEY is set. Same Qwen
# family as Groq, so its scores line up; Cloudflare's 8B model is the last resort.
CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_DEFAULT_MODEL = "qwen-3.8-27b"


@dataclass
class ScoreResult:
    item_id: int
    score: int
    novelty: int
    impact: int
    relevance: int
    entities: list[str]
    topics: list[str]
    market_impact: str | None
    error: str | None
    domain: str = "other"
    model: str = ""


SCORING_PROMPT = """You score news for News Intel, a briefing read by the team at an Indian legal-tech company. They follow important developments across ALL of technology and science, plus Indian legal and business news.

First pick the DOMAIN, one id:
ai (AI and machine learning), chips (semiconductors, computing hardware, data centres), mobility (EVs, cars, flying cars, drones, transport), space, health (medicine, biotech), energy (energy, batteries, climate tech), robotics, fintech (payments, banking tech, crypto), security (cybersecurity, privacy breaches), consumer (phones, gadgets, apps, internet platforms), science (other research), policy (tech regulation and government action outside India), legal_india (ONLY India: Indian law, courts, regulators, arbitration, mediation, ODR; a court case in another country takes the domain of its subject, or other), business (companies, deals, markets, earnings), other.

Then score three dimensions, 0-25 each, judged WITHIN that domain. An equally big EV, space or biotech story gets the same scores as an AI story. Never add points just because AI is mentioned.
- NOVELTY: 0 = rehash or opinion on old news, 10 = incremental update, 18 = notable first, 25 = world first.
- IMPACT: 0 = trivial, 10 = matters to specialists, 18 = changes things for a whole industry, 25 = changes the field.
- RELEVANCE: should a tech-aware reader know this? 0 = not about technology, science, business or Indian law (sport, celebrity, lifestyle, general politics), 8 = niche, 15 = solid news, 20 = widely discussed, 25 = must know.
Use the whole range; most articles land between 8 and 18 on each.

Also extract:
- ENTITIES: key companies, organisations, people, products (max 5)
- TOPICS: specific topics covered (max 5, e.g. "solid-state batteries", "LLM", "satellite launch")
- MARKET_IMPACT: one plain sentence on why it matters to the reader's company, Presolv360: an Indian online dispute resolution (ODR) and legal-tech platform that runs arbitration, mediation and conciliation, mostly for banks, NBFCs and fintech lenders recovering loans. Name the concrete link when there is one (lending, debt recovery, Indian courts and regulators, legal tech, AI they could use, data security, competitors). When there is no real link, do not mention Presolv360 or the missing link at all: just say why it matters to tech or business. Never invent a connection. Under 35 words. "none" if purely academic.

Article:
Title: {title}
Source: {source_name} (Tier {tier})
Summary: {summary}

Respond in JSON only:
{{"domain": "<id>", "novelty": <0-25>, "impact": <0-25>, "relevance": <0-25>, "entities": [...], "topics": [...], "market_impact": "..."}}"""


def _parse_score_response(text: str, tier: str) -> dict:
    """Parse LLM JSON response, extract scores."""
    # Try to find JSON in response
    text = text.strip()
    
    # Handle markdown code blocks
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
    
    # Find JSON object
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON found in response")
    
    data = json.loads(match.group())
    
    # Extract and validate scores
    novelty = max(0, min(25, int(data.get("novelty", 0))))
    impact = max(0, min(25, int(data.get("impact", 0))))
    relevance = max(0, min(25, int(data.get("relevance", 0))))
    
    # Total score = tier + novelty + impact + relevance
    tier_score = TIER_SCORES.get(tier, 12)
    total = tier_score + novelty + impact + relevance

    domain = str(data.get("domain") or "").strip().lower()

    return {
        "score": total,
        "domain": domain if domain in DOMAINS else "other",
        "novelty": novelty,
        "impact": impact,
        "relevance": relevance,
        "entities": data.get("entities", [])[:5],
        "topics": data.get("topics", [])[:5],
        "market_impact": data.get("market_impact"),
    }


# Groq's free tier for GROQ_MODEL (from its x-ratelimit headers, Oct 2026):
# 1,000 requests/day and 8,000 tokens/minute. A scoring call is ~1,000 tokens,
# so the minute limit is hit after ~8 calls. Waiting it out keeps scoring on
# Groq instead of falling back to the weaker Cloudflare model.
# Article text sent per call. 2,000 chars = ~890 tokens a call, 1,200 = ~690: about
# 11 calls a minute instead of 9. The headline and opening carry the news anyway.
SUMMARY_CHARS = 1200
GROQ_MAX_WAIT = 65         # seconds; a longer retry-after means the daily quota is gone
_groq_exhausted = False     # set once the daily quota is gone, so the rest of the run skips Groq
_groq_remaining: int | None = None   # daily requests left, from Groq's last response
GROQ_WARN_REMAINING = 150   # the website warns admins when fewer daily calls than this are left


class GroqQuotaExhausted(RuntimeError):
    pass


def _call_groq(prompt: str, attempts: int = 4) -> str:
    """Call Groq, waiting out per-minute rate limits."""
    global _groq_exhausted, _groq_remaining
    if _groq_exhausted:
        raise GroqQuotaExhausted("daily quota used up earlier in this run")
    api_key = env("GROQ_API_KEY", required=True)

    for attempt in range(attempts):
        try:
            resp = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
                timeout=30,
            )
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after") or 10)
            if wait > GROQ_MAX_WAIT:
                _groq_exhausted = True
                raise GroqQuotaExhausted(f"daily quota used up (retry-after {wait:.0f}s)")
            if attempt < attempts - 1:
                time.sleep(wait + 1)
                continue
        remaining = resp.headers.get("x-ratelimit-remaining-requests")
        if remaining and remaining.isdigit():
            _groq_remaining = int(remaining)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    raise RuntimeError("unreachable")


GEMINI_MAX_WAIT = 65        # seconds; a longer wait, or a per-day limit, means today's quota is gone
_gemini_exhausted = False   # set once Gemini's quota is gone, so the rest of the run skips it


def _call_gemini(prompt: str, attempts: int = 3) -> str:
    """Google Gemini, waiting out per-minute limits. Raises when no key is set, so the caller moves on."""
    global _gemini_exhausted
    if _gemini_exhausted:
        raise RuntimeError("Gemini quota used up earlier in this run")
    api_key = env("GEMINI_API_KEY", required=True)

    for attempt in range(attempts):
        resp = httpx.post(
            GEMINI_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": env("GEMINI_MODEL") or GEMINI_DEFAULT_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                # Flash models think before answering and that counts against max_tokens
                "reasoning_effort": "low",
                "max_tokens": 2000,
            },
            timeout=60,
        )
        if resp.status_code == 429:
            # Google puts the wait in the body ("retryDelay": "36s") rather than a header
            delay = re.search(r'retryDelay"?\s*:\s*"(\d+)', resp.text)
            wait = float(resp.headers.get("retry-after") or (delay.group(1) if delay else 15))
            if wait > GEMINI_MAX_WAIT or "PerDay" in resp.text or attempt == attempts - 1:
                _gemini_exhausted = True
                raise RuntimeError("Gemini free quota used up")
            time.sleep(wait + 1)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    raise RuntimeError("unreachable")


def _call_cerebras(prompt: str) -> str:
    """Cerebras (OpenAI-compatible). Raises when no key is set, so the caller moves on."""
    api_key = env("CEREBRAS_API_KEY", required=True)
    resp = httpx.post(
        CEREBRAS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": env("CEREBRAS_MODEL") or CEREBRAS_DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 500,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
def _call_cloudflare(prompt: str) -> str:
    """Call Cloudflare Workers AI as fallback."""
    account_id = env("CF_ACCOUNT_ID", required=True)
    api_token = env("CF_API_TOKEN", required=True)
    
    resp = httpx.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{CF_MODEL}",
        headers={"Authorization": f"Bearer {api_token}"},
        json={
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["result"]["response"]


# Indian legal news nearly always names India or an Indian institution. The
# small scoring model sometimes files any court case under legal_india, so the
# domain is only kept when one of these appears.
_INDIA_HINT = re.compile(
    r"\b(india|indian|bharat|delhi|mumbai|bengaluru|bangalore|chennai|kolkata|hyderabad"
    r"|sebi|rbi|nclt|nclat|meity|niti aayog|lok sabha|rajya sabha|high court|supreme court of india"
    r"|crore|lakh|rupees?|inr)\b",
    re.I,
)


def _result(item: dict, parsed: dict, model: str) -> ScoreResult:
    domain = parsed["domain"]
    # Headline and opening only: Indian outlets mention India in page furniture, so a US
    # court story from ET Tech would otherwise pass
    text = f"{item['title']} {(item.get('article_text') or item.get('feed_summary') or '')[:500]}"
    if domain == "legal_india" and not _INDIA_HINT.search(text):
        domain = "other"
    return ScoreResult(
        item_id=item["id"],
        score=parsed["score"],
        novelty=parsed["novelty"],
        impact=parsed["impact"],
        relevance=parsed["relevance"],
        entities=parsed["entities"],
        topics=parsed["topics"],
        market_impact=parsed["market_impact"],
        error=None,
        domain=domain,
        model=model,
    )


def score_item(item: dict) -> ScoreResult:
    """Score a single item: Groq, then each backup model whose key is set."""
    prompt = SCORING_PROMPT.format(
        title=item["title"],
        source_name=item["source_name"],
        tier=item["tier"],
        summary=(item.get("article_text") or item.get("feed_summary") or "")[:SUMMARY_CHARS],
    )

    models = [("groq", _call_groq, True),
              ("gemini", _call_gemini, env("GEMINI_API_KEY")),
              ("cerebras", _call_cerebras, env("CEREBRAS_API_KEY")),
              ("cloudflare", _call_cloudflare, env("CF_ACCOUNT_ID") and env("CF_API_TOKEN"))]
    errors = []
    for name, call, has_key in models:
        if not has_key:
            continue
        try:
            return _result(item, _parse_score_response(call(prompt), item["tier"]), name)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {_short_error(e)}")
    if len(errors) == 1:
        errors.append("no backup model has a key set")
    return ScoreResult(
        item_id=item["id"],
        score=0,
        novelty=0,
        impact=0,
        relevance=0,
        entities=[],
        topics=[],
        market_impact=None,
        error="; ".join(errors),
    )


def _short_error(e: Exception) -> str:
    """A reason an admin can act on, never a URL or key."""
    if isinstance(e, RetryError):
        e = e.last_attempt.exception() or e
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        return {401: "key rejected (401)", 403: "key not allowed (403)", 404: "model not found (404)",
                429: "rate limited (429)"}.get(code, f"HTTP {code}")
    return str(e)[:80]


def get_unscored_items(conn, limit: int | None = None,
                       ingested_hours: int | None = None) -> list[dict]:
    """Get recent items that passed triage but haven't been scored. News first, papers after.

    ingested_hours limits it to items fetched in the last N hours (the new-source run).
    """
    with conn.cursor() as cur:
        query = """
            SELECT r.id, r.title, r.article_text, r.feed_summary,
                   s.name as source_name, s.tier
            FROM raw_items r
            JOIN sources s ON r.source_id = s.id
            JOIN news_memory m ON r.id = m.id
            WHERE r.rules_pass = true
              AND m.score IS NULL
              AND r.published_at >= now() - make_interval(days => %s)
              AND (%s::int IS NULL OR r.ingested_at >= now() - make_interval(hours => %s::int))
            ORDER BY (r.source_id = ANY(%s)), r.published_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query, (PROCESS_DAYS, ingested_hours, ingested_hours, list(PAPER_SOURCES)))
        return cur.fetchall()


def update_scores(conn, results: list[ScoreResult]) -> dict:
    """Update news_memory with scores."""
    stats = {"scored": 0, "failed": 0, "breaking": 0, "major": 0, "notable": 0, "gemini": 0, "cerebras": 0, "cloudflare": 0}
    
    with conn.cursor() as cur:
        for r in results:
            if r.error:
                stats["failed"] += 1
                continue
            
            breakdown = {
                "novelty": r.novelty,
                "impact": r.impact,
                "relevance": r.relevance,
                "domain": r.domain,
                "model": r.model,
            }
            
            cur.execute(
                """
                UPDATE news_memory
                SET score = %s,
                    score_breakdown = %s,
                    entities = %s,
                    topics = %s,
                    market_impact = %s
                WHERE id = %s
                """,
                (
                    r.score,
                    json.dumps(breakdown),
                    r.entities,
                    r.topics,
                    r.market_impact,
                    r.item_id,
                ),
            )
            stats["scored"] += 1
            for backup in ("gemini", "cerebras", "cloudflare"):
                stats[backup] += r.model == backup
            
            # Track score distribution
            if r.score >= SCORE_BREAKING:
                stats["breaking"] += 1
            elif r.score >= SCORE_MAJOR:
                stats["major"] += 1
            elif r.score >= SCORE_NOTABLE:
                stats["notable"] += 1
    
    return stats


BATCH_SIZE = 25  # Save to DB every N items to avoid connection timeout


def run(dry_run: bool = False, limit: int | None = None, ingested_hours: int | None = None) -> int:
    """Main entry point."""
    if dry_run:
        print(f"\n{'=' * 60}")
        print("  DRY RUN - testing LLM scoring")
        print(f"{'=' * 60}\n")

        test_item = {
            "id": 0,
            "title": "OpenAI releases GPT-5 with 10x reasoning improvement",
            "source_name": "OpenAI",
            "tier": "B",
            "article_text": "OpenAI announced GPT-5 today, claiming a 10x improvement in complex reasoning tasks. The model uses a new architecture combining chain-of-thought with retrieval augmentation.",
            "feed_summary": None,
        }

        print(f"  Model: {GROQ_MODEL} (backups: Gemini, Cerebras, Cloudflare {CF_MODEL})")
        print(f"  Tier scores: {TIER_SCORES}")
        print(f"  Thresholds: breaking={SCORE_BREAKING}, major={SCORE_MAJOR}, notable={SCORE_NOTABLE}\n")
        
        print(f"  Test: {test_item['title'][:50]}...")
        
        # Check if API keys are set
        groq_key = env("GROQ_API_KEY")
        if not groq_key:
            print("\n  ⚠ GROQ_API_KEY not set - skipping live test")
            print("  Set it in .env to test scoring")
            return 0
        
        result = score_item(test_item)
        
        if result.error:
            print(f"\n  ✗ Error: {result.error}")
        else:
            print(f"\n  ✓ Score: {result.score}/100")
            print(f"    Breakdown: novelty={result.novelty}, impact={result.impact}, relevance={result.relevance}")
            print(f"    Entities: {result.entities}")
            print(f"    Topics: {result.topics}")
            print(f"    Market: {result.market_impact}")
            
            if result.score >= SCORE_BREAKING:
                print(f"\n    → BREAKING NEWS (≥{SCORE_BREAKING})")
            elif result.score >= SCORE_MAJOR:
                print(f"\n    → Major story (≥{SCORE_MAJOR})")
            elif result.score >= SCORE_NOTABLE:
                print(f"\n    → Notable (≥{SCORE_NOTABLE})")
        
        return 0

    from . import db

    # Get items with fresh connection
    with db.connect() as conn:
        items = get_unscored_items(conn, limit, ingested_hours)
    
    if not items:
        print("score: no items need scoring")
        return 0

    print(f"score: processing {len(items)} items...")

    total_stats = {"scored": 0, "failed": 0, "breaking": 0, "major": 0, "notable": 0, "gemini": 0, "cerebras": 0, "cloudflare": 0}
    batch_results = []
    first_error = None   # why scoring failed, for the website's warning

    for i, item in enumerate(items):
        result = score_item(item)
        first_error = first_error or result.error
        batch_results.append(result)
        
        # Save batch to DB periodically
        if len(batch_results) >= BATCH_SIZE or i == len(items) - 1:
            with db.connect() as conn:
                stats = update_scores(conn, batch_results)
            for k in total_stats:
                total_stats[k] += stats[k]
            batch_results = []
            print(f"score: {i + 1}/{len(items)} (saved batch)")
        elif (i + 1) % 10 == 0:
            print(f"score: {i + 1}/{len(items)}...")

    print(
        f"score: {total_stats['scored']} scored, {total_stats['failed']} failed | "
        f"breaking={total_stats['breaking']}, major={total_stats['major']}, notable={total_stats['notable']} | "
        f"gemini={total_stats['gemini']}, cerebras={total_stats['cerebras']}, "
        f"cloudflare={total_stats['cloudflare']} | "
        f"groq calls left today={_groq_remaining if _groq_remaining is not None else '?'}"
    )

    # Kept in Neon (the runner is wiped after each run); publish_static shows the warnings
    # on the website's pipeline health panel
    warnings = budget_warnings(total_stats, _groq_remaining, _groq_exhausted, first_error)
    with db.connect() as conn:
        waiting = len(get_unscored_items(conn))
        db.record_run(conn, "score", {"detail": {
            **total_stats, "waiting": waiting, "warnings": warnings,
            "groq_remaining": _groq_remaining, "groq_exhausted": _groq_exhausted,
        }}, ok=True)
    print(f"score: {waiting} items still waiting")
    for w in warnings:
        print(f"score: warning: {w}")

    return 0


def budget_warnings(stats: dict, groq_remaining: int | None, groq_exhausted: bool,
                    error: str | None = None) -> list[str]:
    """Plain-English problems with the free LLM budget in this run, if any."""
    problems = []
    if groq_exhausted:
        problems.append("Groq's free daily quota ran out during scoring")
    elif groq_remaining is not None and groq_remaining < GROQ_WARN_REMAINING:
        problems.append(f"Only {groq_remaining} Groq calls were left for the day")
    backups = {"Gemini": stats.get("gemini", 0), "Cerebras": stats.get("cerebras", 0),
               "Cloudflare": stats.get("cloudflare", 0)}
    if sum(backups.values()):
        used = ", ".join(f"{name} {n}" for name, n in backups.items() if n)
        problems.append(f"{sum(backups.values())} stories were scored by a backup model ({used})")
    if stats.get("failed"):
        problems.append(f"{stats['failed']} stories could not be scored"
                        + (f" ({error})" if error else "") + "; they wait for the next run")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Score items using LLM.")
    ap.add_argument("--dry-run", action="store_true", help="test scoring without DB")
    ap.add_argument("--limit", type=int, help="only score N items")
    ap.add_argument("--ingested-within-hours", type=int, help="only items fetched in the last N hours")
    args = ap.parse_args()
    return run(dry_run=args.dry_run, limit=args.limit, ingested_hours=args.ingested_within_hours)


if __name__ == "__main__":
    raise SystemExit(main())
