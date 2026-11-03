# How News Intel is built: the full-stack guide

**For:** a product manager who wants to understand the whole system, from database to screen,
without having to read the code first.
**Last updated:** 2 November 2026

Every library, file name, number and code sample below is taken from the real project. Code samples
are shortened in places (marked `...`), but nothing is invented.

---

## Contents

1. [The 30-second picture](#1-the-30-second-picture)
2. [Full-stack words, explained with our project](#2-full-stack-words-explained-with-our-project)
3. [The tech stack in one table](#3-the-tech-stack-in-one-table)
4. [Backend: the news pipeline](#4-backend-the-news-pipeline)
5. [Databases](#5-databases)
6. [APIs: every outside service we talk to](#6-apis-every-outside-service-we-talk-to)
7. [Frontend: the website](#7-frontend-the-website)
8. [Sign-in, step by step](#8-sign-in-step-by-step)
9. [One story's journey, start to finish](#9-one-storys-journey-start-to-finish)
10. [Infrastructure: hosting, schedules and deploys](#10-infrastructure-hosting-schedules-and-deploys)
11. [Security in one page](#11-security-in-one-page)
12. [Testing](#12-testing)
13. [Limits and costs, in numbers](#13-limits-and-costs-in-numbers)
14. ["If I ask for X, what changes?"](#14-if-i-ask-for-x-what-changes)
15. [File map](#15-file-map)
16. [Glossary](#16-glossary)

---

## 1. The 30-second picture

```
  ┌──────────────────────┐      ┌───────────────────────────────┐      ┌─────────────────────┐
  │  ~70 NEWS SOURCES    │      │  BACKEND: the pipeline        │      │  FRONTEND: website  │
  │  RSS feeds, Google   │ ───▶ │  Python, runs on GitHub       │ ───▶ │  HTML + CSS + JS    │
  │  News, APIs          │      │  Actions on a timer           │ data │  hosted on Atlair   │
  └──────────────────────┘      │                               │ .js  │                     │
                                │  collect, clean, AI-rank,     │      │  Today, All stories │
                                │  group, publish               │      │  Notes, Settings    │
                                └───────────────┬───────────────┘      └──────────┬──────────┘
                                                │                                 │
                                    ┌───────────▼───────────┐         ┌───────────▼───────────┐
                                    │  DATABASE 1: Neon     │         │  DATABASE 2: Supabase │
                                    │  all articles, scores │         │  accounts, notes,     │
                                    │  (pipeline only)      │         │  settings, requests   │
                                    └───────────────────────┘         └───────────────────────┘
```

**The single most important fact:** the backend and the website only meet at **one file**,
`frontend/data.js`. The pipeline writes it every morning; the website reads it. There is no server
answering requests in between. That is why the site is fast, free and works offline.

---

## 2. Full-stack words, explained with our project

| Word | General meaning | In News Intel |
|---|---|---|
| **Frontend** | What runs in the user's browser | `frontend/`: one HTML page, 14 JavaScript files, 7 CSS files |
| **Backend** | Code that runs on a server, out of sight | `agent/`: the Python pipeline. It runs on a schedule, not on request |
| **API** | A way for one program to ask another for data | We *call* other APIs (Groq, Supabase, Google News). We have **no API of our own** |
| **Database** | Where data is stored permanently | Two: **Neon** (news) and **Supabase** (people's data) |
| **Server** | A computer that answers requests | We have none of our own. Atlair serves files; Supabase answers database calls |
| **Static site** | A site made of fixed files, no server code | Ours. News changes because the *file* `data.js` is rewritten daily |
| **Hosting** | Where the site lives on the internet | Atlair, behind Cloudflare's network |
| **Deploy** | Putting a new version live | Automatic: every push to GitHub's `main` branch goes live |
| **CI/CD, cron jobs** | Automated jobs that run on events or timers | GitHub Actions: 4 workflows in `.github/workflows/` |
| **Auth** | Sign-in and knowing who someone is | Supabase Auth: email and password, or Google |
| **Environment variables / secrets** | Passwords and keys kept out of the code | GitHub Secrets (online) and `.env` (on a laptop) |
| **Library / package** | Ready-made code we reuse | 8 Python packages, 1 JavaScript library (supabase-js) |
| **LLM** | Large language model, an AI that reads and writes text | Groq's Qwen model scores stories; Google Gemini is the backup |

---

## 3. The tech stack in one table

| Layer | Technology | Version | Why this one |
|---|---|---|---|
| Pipeline language | **Python** | 3.12 | Best libraries for feeds, text and AI |
| Read RSS feeds | `feedparser` | 6.0.11 | Handles every RSS/Atom variant |
| Web requests | `httpx` | 0.28.1 | Fetches many feeds at once (async) |
| Pull article text out of a page | `trafilatura` | 2.0.0 | Strips menus and ads, keeps the article |
| Talk to Postgres | `psycopg` | 3.2.3 | The standard Postgres driver |
| Parse messy dates | `python-dateutil` | 2.9.0 | Feeds write dates a dozen ways |
| Turn text into numbers (embeddings) | `fastembed` | 0.5.1 | Runs on the CPU, no paid API |
| Maths for similarity | `numpy` | 2.2.2 | Fast comparisons between stories |
| Read `.env` locally | `python-dotenv` | 1.2.4 | Secrets on a laptop |
| AI scoring | **Groq** API, model `qwen/qwen3.8-27b` | | Free tier, very fast |
| AI backup | **Google Gemini** API, `gemini-3.5-flash-lite` | | Free tier, used when Groq runs out |
| Embedding model | `BAAI/bge-small-en-v1.5` | 384 dimensions | Small (67 MB), good quality |
| News database | **Neon** (Postgres + `pgvector`) | free plan | Postgres that can search by meaning |
| User database + sign-in | **Supabase** (Postgres + Auth) | free plan | Database, sign-in and security rules in one |
| Website | Plain **HTML, CSS, JavaScript** | no framework | Nothing to build or maintain |
| Website's database library | `@supabase/supabase-js` | 2.45.4 | Talks to Supabase from the browser |
| Fonts | **Geist** and **Geist Mono** (Google Fonts) | | Clean, readable, by Vercel |
| Website hosting | **Atlair** (Cloudflare CDN) | | Free, deploys from GitHub |
| Automation | **GitHub Actions** | | Free minutes, runs on a timer |
| Code storage | **GitHub** | | Version history, triggers deploys |

The full Python list is [requirements.txt](../requirements.txt). Every version is pinned (fixed), so an
outside update can't break the pipeline by surprise.

---

## 4. Backend: the news pipeline

The pipeline is a chain of **stages**. Each is one Python file in `agent/`, runs on its own, and
only works on what the previous stage finished. So if a run stops halfway, the next run carries on.

```
trends → ingest → triage → extract → embed → score → cluster → threads → publish_static
```

You can run any stage by hand, for example `python -m agent.score --dry-run` (`--dry-run` shows what
would happen without saving anything).

### 4.0 The source list: `agent/sources.py`

Every source is one line of Python:

```python
@dataclass(frozen=True)
class Source:
    id: str                 # stable id, e.g. "barandbench"
    name: str               # shown on the site, e.g. "Bar & Bench"
    tier: str               # A, B, C or D: how trustworthy (feeds the score)
    kind: str = "rss"       # rss | json | cisa_kev | newsdata
    url: str = ""
    enabled: bool = True
    category: str = "tech"  # tech | legal | market | competitors | other

SOURCES = [
    Source("mit_tr", "MIT Technology Review", "A", url="https://www.technologyreview.com/feed/"),
    ...
]
```

For topics without a good feed, a Google News search acts as a feed:

```python
def _google_news(query: str, days: int = 7) -> str:
    return ("https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="
            + quote(f"{query} when:{days}d"))
```

Sources requested on the website are added to this list at run time (as `req_<number>`), and
sources an admin switched off are removed from it.

### 4.1 trends: `agent/trends.py` (daily)

Finds what's trending so we don't miss big stories our sources haven't caught yet.

- Reads **Google Trends** daily feeds for India and the US, plus names 3 or more of our sources
  mention on the same day.
- One AI call keeps only the newsworthy ones and writes a 2 to 5 word search.
- Each becomes a **trend watch**: a Google News search followed for 5 days. Up to 3 new a day, 8 at once.

### 4.2 ingest: `agent/ingest.py` (every 4 hours)

Collects new articles.

1. Builds the list: `sources.py` + approved website requests − switched-off sources + trend watches.
2. Fetches **8 feeds at a time** (`FEED_CONCURRENCY = 8`), 20 seconds max each.
3. Cleans every link so the same article from two places counts once (`normalize.canonical_url`:
   lower-case, force https, drop tracking tags like `utm_source`, drop `www.`).
4. Saves new rows to the `raw_items` table.

Safety rules built in:

- **A dead feed never stops the run.** The error is recorded; after 3 failures in a row the feed is
  tried only once a day.
- **A new source keeps only its last 24 hours** (`FIRST_FETCH_HOURS = 24`), so adding a source doesn't
  flood the queue with weeks of old news.
- **Feed discovery:** if someone requests `epoch.ai`, ingest reads the home page, looks for its feed
  link, then tries the usual addresses (`/feed`, `/rss`, `/atom.xml` ...), and finally falls back to a
  Google News `site:epoch.ai` search.

How ingest reads the website's settings from Supabase (this is a real API call):

```python
def _supabase_rpc(name: str) -> list[dict] | None:
    url, key = supabase_settings()
    resp = httpx.post(f"{url}/rest/v1/rpc/{name}", json={},
                      headers={"apikey": key, "Authorization": f"Bearer {key}"})
    return resp.json()

fetch_requested_sources()  # calls approved_source_feeds()
fetch_switched_off()       # calls switched_off_sources()
```

### 4.3 triage: `agent/triage.py`

Throws out noise for free, by reading only the title. Examples of the real rules:

```python
_NOISE_PATTERNS = [
    (r"\b(we('re| are) hiring|job opening|career|join our team)\b", "job_posting"),
    (r"\b(is (pleased|proud|excited) to announce)\b",                "press_release"),
    (r"\b(raises|raised|secures|secured)\s+\$?\d+\s*(m|million|b|billion)\b", "funding_news"),
    (r"^\d+\s+(best|top|ways|tips|tools|things)\b",                   "listicle"),
    (r"\b(sponsored|promoted|advertisement)\b",                       "sponsored"),
]
```

Those `r"..."` strings are **regular expressions**: text patterns. If a title matches, it's dropped
with that reason. Research papers from arXiv only pass if they have **10+ upvotes on Hugging Face Daily
Papers**; without that gate, papers (about 88% of what's fetched) would crowd out the news.

Why triage runs *before* the AI: every AI call costs quota. Throwing junk out first saves it.

### 4.4 extract: `agent/extract.py`

Downloads each surviving article's web page and pulls out the main text with `trafilatura`. Marks
paywalled pages. Some sites block cloud servers; for those, the story is scored from its feed summary.
Only the last 14 days are processed (`PROCESS_DAYS = 14`).

### 4.5 embed: `agent/embed.py`

Turns each article into an **embedding**: a list of 384 numbers that captures its *meaning*. Two
articles about the same event get very similar lists, even with different wording. This is what lets
us group stories (cluster) and link them over time (threads).

```python
from fastembed import TextEmbedding
model = TextEmbedding("BAAI/bge-small-en-v1.5")
vectors = list(model.embed(["SC asks RBI to vet digital fraud rules", ...]))
```

It runs on GitHub's computer, so it costs nothing per article.

### 4.6 score: `agent/score.py` (the AI part)

Sends each article to the AI with a written brief (a **prompt**). The real prompt starts like this:

```text
You score news for News Intel, a briefing read by the team at an Indian legal-tech company...

First pick the DOMAIN, one id: ai, chips, mobility, space, health, energy, robotics, fintech,
security, consumer, science, policy, legal_india, business, other.

Then score three dimensions, 0-25 each, judged WITHIN that domain...
- NOVELTY:   0 = rehash, 10 = incremental update, 18 = notable first, 25 = world first.
- IMPACT:    0 = trivial, 10 = matters to specialists, 18 = changes an industry, 25 = changes the field.
- RELEVANCE: 0 = not tech/science/business/Indian law, 15 = solid news, 25 = must know.

Also extract: ENTITIES (max 5), TOPICS (max 5), MARKET_IMPACT: one plain sentence on why it matters
to Presolv360 ... Never invent a connection. Under 35 words.

Respond in JSON only:
{"domain": "<id>", "novelty": <0-25>, "impact": <0-25>, "relevance": <0-25>, ...}
```

The AI answers in **JSON** (a structured text format), and the code adds it up:

```python
TIER_SCORES = {"A": 25, "B": 22, "C": 20, "D": 12}
total = TIER_SCORES[tier] + novelty + impact + relevance     # 0 to 100
```

| Score | Label on the site |
|---|---|
| 85 to 100 | **Breaking** |
| 70 to 84 | **Major** |
| 55 to 69 | **Notable** |
| below 55 | not shown |

"Why it matters" on the site is the `market_impact` sentence.

The API call itself (shortened):

```python
resp = httpx.post("https://api.groq.com/openai/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"model": "qwen/qwen3.8-27b",
          "messages": [{"role": "user", "content": prompt}],
          "temperature": 0.1,      # low = consistent answers
          "max_tokens": 500})
```

**Rate limits:** Groq's free tier allows 1,000 calls a day and about 11 a minute. When Groq says "slow
down" (HTTP code `429`), the code waits. When the daily quota is gone, it switches to Gemini. Each score
records which model made it. Every run writes its usage and warnings to the `runs` table, which is what
admins see as "Pipeline health".

### 4.7 cluster: `agent/cluster.py`

Groups coverage of the **same event**. Two articles are grouped when:

- their embeddings are very similar (**cosine similarity ≥ 0.86**, where 1.0 means identical),
- they share a company or person, and
- they were published within **72 hours** of each other.

That's why the site shows "Bar & Bench +3" as one story instead of four.

### 4.8 threads: `agent/threads.py`

Links stories into **ongoing narratives** across weeks, using the database's meaning search directly:

```sql
SELECT ..., 1 - (m1.embedding <=> m2.embedding) AS similarity   -- <=> is pgvector's distance
FROM news_memory m1, news_memory m2
WHERE 1 - (m1.embedding <=> m2.embedding) >= 0.75
```

### 4.9 publish_static: `agent/publish_static.py`

Writes the one file the website reads, `frontend/data.js`:

```javascript
// This file is auto-generated by publish_static.py
// DO NOT EDIT MANUALLY
window.digestData = {
    "generated_at": "2026-11-02T14:17:09+05:30",
    "stats":   { "sources_total": 77, "sources_healthy": 72 },
    "sources": [ { "id": "mit_ai", "name": "MIT News (AI)", "url": "...", "category": "tech" }, ... ],
    "health":  { "last_ingest_at": "...", "warnings": ["Groq's free daily quota ran out ..."] },
    "breaking": [ ... ],   // 10 stories today
    "major":    [ ... ],   // 349
    "notable":  [ ... ]    // 1,352
};
```

One story inside it looks like this (a real one):

```json
{
  "headline": "Watch: What's the deal with OpenAI's massive dump of math papers?",
  "score": 84,
  "source": "Science News",
  "source_id": "science",
  "url": "https://science.org/content/article/...",
  "topics": ["AI for Science", "Mathematical Reasoning", "Large Language Models"],
  "entities": ["OpenAI"],
  "market_impact": "This release signals a shift in AI capabilities ...",
  "cluster_id": 2,
  "coverage": [ { "source": "The Information", "headline": "OpenAI Publishes Over 700 ...", "url": "..." } ],
  "trending": false,
  "published_at": "2026-10-07T06:15:06+00:00"
}
```

It includes every story scored 55+ from the last 30 days (`WEBSITE_DAYS = 30`). It also stamps
**fingerprints** on the page's file links (`css/base.css?v=7e25d561`) so browsers and Cloudflare
always load the newest version, and refreshes the security hash in `index.html` (see section 11).

---

## 5. Databases

We use two, each for a different job. Both are **PostgreSQL** ("Postgres"), the most widely used
open-source database.

### 5.1 Neon: the news database (pipeline only)

Defined in [sql/schema.sql](../sql/schema.sql). The website never touches it.

| Table | Holds | Written by |
|---|---|---|
| `sources` | One row per source, plus health: last success, failure count, last error | ingest |
| `raw_items` | Every article ever fetched, one row per clean link | ingest |
| `news_memory` | Articles that passed triage: text, embedding, score, entities, why it matters | embed, score |
| `clusters` | Groups of articles about the same event | cluster |
| `threads` | Ongoing narratives across weeks | threads |
| `runs` | One row per job run: counts, failures, AI quota left | ingest, score |
| `trend_watches` | Trending topics being followed, until when | trends |
| `feedback` | Reserved for reader ratings later | nobody yet |

The heart of it, `news_memory` (shortened):

```sql
CREATE TABLE news_memory (
  id            BIGINT PRIMARY KEY REFERENCES raw_items(id),
  headline      TEXT NOT NULL,
  source_name   TEXT NOT NULL,
  published_at  TIMESTAMPTZ NOT NULL,
  embedding     VECTOR(384) NOT NULL,      -- the 384 meaning-numbers
  entities      TEXT[],                    -- ["OpenAI", "RBI"]
  topics        TEXT[],
  score         INT,                       -- 0 to 100
  market_impact TEXT,                      -- "why it matters"
  cluster_id    BIGINT REFERENCES clusters(id),
  thread_id     BIGINT REFERENCES threads(id)
);
CREATE INDEX news_memory_embed_idx ON news_memory USING hnsw (embedding vector_cosine_ops);
```

Key ideas:

- **Primary key** (`id`): the unique number of each row.
- **References** (foreign keys): `cluster_id` points at a row in `clusters`, which keeps data consistent.
- **Index**: like a book's index, makes lookups fast. The `hnsw` index makes "find similar stories"
  fast; that's what the `pgvector` extension adds.
- Neon's free plan sleeps when idle and takes a few seconds to wake; the code retries once.

### 5.2 Supabase: the people database (website)

Defined in [sql/supabase.sql](../sql/supabase.sql), with rules in `security.sql`, `hardening.sql` and
`source_switches.sql`.

| Table | Holds | Who can read / write |
|---|---|---|
| `profile` | Name, email, role (`user` or `admin`) | Own row; admins see all |
| `note` | Notes (HTML), pinned, timestamps | Only the owner. Not even admins |
| `user_setting` | Preferences and "My sources" | Only the owner |
| `source_request` | Requested sources: status, who, why, admin's note | Own requests; admins decide |
| `source_off` | Sources an admin switched off for everyone | Everyone signed in reads; admins write |
| `audit_log` | Sign-ins and admin actions | Admins read |

Sign-in accounts themselves live in Supabase's built-in `auth` area, which we never touch directly.
(An old `source` table still exists but is no longer used.)

### 5.3 Row Level Security (RLS): how "only your own notes" is enforced

The website talks to the database **directly from the browser**. So the database itself must refuse
anything a person isn't allowed to do, no matter what the browser asks. That's RLS: a rule attached
to every table. The real rule for notes:

```sql
ALTER TABLE note ENABLE ROW LEVEL SECURITY;

CREATE POLICY note_owner ON note FOR ALL TO authenticated
    USING      (user_id = auth.uid())     -- you can only SEE rows that are yours
    WITH CHECK (user_id = auth.uid());    -- you can only WRITE rows as yourself
```

`auth.uid()` is "the id of whoever is signed in", taken from their sign-in token, which can't be
faked. The admin-only rule for switching sources off:

```sql
CREATE POLICY source_off_admin ON source_off FOR ALL TO authenticated
    USING (public.is_admin()) WITH CHECK (public.is_admin());
```

`hardening.sql` adds **checks** (links must start with http(s); length limits) and **triggers**
(code that runs on every save: stamps the real email, enforces rate limits such as 100 notes an hour
and 10 source requests a day).

### 5.4 Database functions the pipeline calls

The pipeline has no Supabase password. It uses the public key to call two **functions** that return
only harmless data:

```sql
CREATE FUNCTION public.switched_off_sources()
RETURNS TABLE (source_id text)
LANGUAGE sql STABLE SECURITY DEFINER
AS $$ SELECT source_id FROM source_off ORDER BY source_id; $$;

GRANT EXECUTE ON FUNCTION public.switched_off_sources() TO anon, authenticated;
```

`approved_source_feeds()` works the same way, returning id, name, link and category of approved
requests.

---

## 6. APIs: every outside service we talk to

An **API call** is one program sending a request over the internet and getting data back, usually as
JSON. We have no API of our own; these are the ones we call:

| API | Called by | For | Cost |
|---|---|---|---|
| RSS feeds of ~70 sites | ingest | the news | free |
| Google News RSS search | ingest, trends | topics without feeds, gap-fills, trend watches | free |
| Google Trends RSS (IN, US) | trends | what's trending | free |
| Hugging Face Daily Papers (JSON) | ingest, triage | which research papers matter | free |
| CISA Known Exploited Vulnerabilities (JSON) | ingest | security flaws being attacked now | free |
| NewsData.io | ingest | Indian tech press (only if its key is set) | free tier |
| **Groq** chat completions | score, trends | AI scoring | free tier |
| **Google Gemini** (OpenAI-compatible endpoint) | score | backup AI | free tier |
| **Supabase REST** (`/rest/v1/...`) | website, ingest | read and write user data | free plan |
| **Supabase Auth** | website | sign-in, sign-up, password reset | free plan |
| **Google OAuth** | website (through Supabase) | "Continue with Google" | free |
| Google Fonts | website | Geist fonts | free |

How the website calls Supabase (from `frontend/js/supabase.js`). This one line becomes an HTTPS
request to Supabase's REST API:

```javascript
const { data, error } = await supabaseClient
    .from('note')                        // the table
    .select('*')                         // all columns
    .eq('user_id', userId)               // only mine (RLS enforces this anyway)
    .order('pinned', { ascending: false })
    .order('updated_at', { ascending: false });
```

**HTTP status codes** you'll hear about: `200` OK, `401`/`403` not allowed, `404` not found,
`429` too many requests (slow down), `5xx` the other side broke.

---

## 7. Frontend: the website

### 7.1 No framework, on purpose

Most modern sites use React or similar, plus a "build step" that compiles code. We use **plain
HTML, CSS and JavaScript**: the files in `frontend/` are exactly what the browser gets. Fewer moving
parts, nothing to upgrade, nothing to compile.

### 7.2 The files

`frontend/index.html` holds every screen and dialog. The browser loads these scripts in order:

| # | File | Job |
|---|---|---|
| 1 | `js/config.js` | Supabase address and public key, category names, competitor names, score thresholds |
| 2 | `data.js` | The news (written by the pipeline) |
| 3 | `js/util.js` | Helpers: escaping text, India-time dates, browser storage, toasts, `safeUrl`, `cleanHtml` |
| 4 | `js/supabase.js` | **Every** database call (`db.getNotes`, `db.saveNote`, `db.setSourceOff` ...) |
| 5 | `js/stories.js` | Turns `data.js` into stories: label, category, search, the story view |
| 6 | `js/user-state.js` | Read/unread, saved, hidden sources, preferences, Today's list |
| 7 | `js/auth.js` | Sign in, sign up, Google, reset password |
| 8 | `js/panes.js` | Resizable panes in All stories |
| 9 | `js/today.js` | The Today screen |
| 10 | `js/reader.js` | All stories and Saved |
| 11 | `js/notes.js` | Notes and "Add to note" |
| 12 | `js/settings.js` | Settings and admin screens |
| 13 | `js/palette.js` | Ctrl K search |
| 14 | `js/notices.js` | The notice bar and Pipeline health panel |
| 15 | `js/app.js` | Starts everything, routing, keyboard shortcuts, offline banner |

Styles: `css/base.css` (colours, fonts, buttons; all design **tokens** at the top) plus one CSS file per
screen. The only outside script is `supabase-js 2.45.4`, loaded with an **integrity hash** so the browser
refuses it if anyone tampers with it.

### 7.3 How a screen appears

1. The browser loads `index.html`, then the scripts above.
2. `app.js` checks with Supabase whether you're signed in.
3. It loads your settings from Supabase ("My sources", preferences).
4. `stories.js` reads `window.digestData` (from `data.js`), removes duplicates and hidden sources,
   and gives each story a label from its score.
5. `app.js` reads the address after `#` and shows that screen.

### 7.4 Routing: the address bar

The site is one page; the part after `#` decides the screen:

```
#/today              #/today/3   (third story)     #/today/done
#/stories?folder=breaking&from=2026-10-01
#/saved              #/notes/new                   #/settings/sources
```

Because every filter is in the address, Back, refresh and bookmarks all just work.

### 7.5 Where the website keeps data

| Data | Stored in | Why |
|---|---|---|
| News | `data.js` | Same for everyone, rebuilt daily |
| Notes, settings, requests | Supabase, plus a browser copy | Follows you to any device; works offline |
| Read/unread, saved stories, Today's list | Browser storage (`localStorage`) | Fast, personal, no database writes |

So: saved stories and read marks are **per browser** today. Using a second laptop means starting
fresh on those (notes and settings do follow you).

### 7.6 Look and feel

Colours are **tokens** in `css/base.css` (`--ink: #1E3570` for actions, `--tape: #B8282B` only for
Breaking). Dark mode swaps the token values automatically, following the laptop's setting. Fonts are
Geist (all text) and Geist Mono (shortcuts and counts). Full rules: [design.md](design.md).

---

## 8. Sign-in, step by step

**Email and password**

1. You type email and password; `auth.js` sends them to Supabase Auth (never to us).
2. Supabase checks the password (stored scrambled with **bcrypt**; nobody can read it back).
3. Supabase returns a **token** (a signed pass, called a JWT) that the browser keeps.
4. Every later database call carries that token. RLS reads your id from it.
5. The token refreshes itself; you stay signed in until "Sign out".

**Google:** you're sent to Google, approve, and come back to the site with a token. Google shares only
your name, email and picture link.

**New account:** a database trigger creates your `profile` row with role `user` (Member). An admin can
promote you.

---

## 9. One story's journey, start to finish

| When (India time) | What happens | Where |
|---|---|---|
| 10:20 | Bar & Bench publishes an article | their site |
| 10:37 | ingest fetches their feed, cleans the link, saves a `raw_items` row | GitHub Actions → Neon |
| next day 07:01 | daily job starts | GitHub Actions |
| 07:03 | triage: title isn't noise, passes | Neon |
| 07:05 | extract downloads the article text | Bar & Bench → Neon |
| 07:10 | embed turns it into 384 numbers | GitHub's computer → Neon |
| 07:15 | score: Groq says legal_india, novelty 18, impact 20, relevance 22; tier D (12) → **72, Major** | Groq → Neon |
| 07:30 | cluster groups it with SCC Online's take on the same ruling | Neon |
| 07:32 | publish_static writes it into `data.js` | GitHub repo |
| 07:33 | the job commits `data.js` to GitHub | GitHub |
| ~07:35 | Atlair sees the push and deploys | Atlair |
| 08:30 | You open Today; it's story 2 of 5, labelled Major, "Bar & Bench +1" | your browser |
| 08:31 | You press S: saved in your browser. N: added to a note in Supabase | browser, Supabase |

(Times are illustrative; the order and places are exact.)

---

## 10. Infrastructure: hosting, schedules and deploys

### 10.1 GitHub Actions: the robot that runs everything

Workflows are YAML files in `.github/workflows/`. GitHub runs them on its own computers.

| Workflow | When | Does |
|---|---|---|
| `ingest.yml` | every 4 hours | fetch feeds only |
| `daily.yml` | 07:01, catch-up 09:01 | the whole pipeline, then commits `data.js` |
| `new-source.yml` | when `agent/sources.py` changes | fetch and score just the new source, publish in ~10 min |
| `keepalive.yml` | 1st of the month | a tiny commit; GitHub pauses timers on repos idle for 60 days |

A shortened real step:

```yaml
- name: Score items
  run: python -m agent.score --limit 200
  env:
    NEON_DSN: ${{ secrets.NEON_DSN }}          # secrets are injected here, never in the code
    GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
```

If two jobs try to save `data.js` at the same moment, `scripts/push_site_data.sh` pulls the other
job's change first, rebuilds the page stamps, and tries again (up to 3 times).

### 10.2 Hosting and caching

- **Atlair** serves the `frontend/` folder and redeploys on every push to `main`.
- **Cloudflare** (in front of Atlair) keeps copies worldwide for **4 hours**, so the site loads fast.
  The catch: a changed file could stay stale for 4 hours. That's why links carry **fingerprints**
  (`?v=7e25d561`, from the file's content): a changed file gets a new address, so it's always fresh.

### 10.3 Secrets

| Secret | Where | Used for |
|---|---|---|
| `NEON_DSN` | GitHub Secrets, `.env` | the news database's address and password |
| `GROQ_API_KEY` | GitHub Secrets, `.env` | AI scoring |
| `GEMINI_API_KEY` | GitHub Secrets, `.env` | backup AI |
| `NEWSDATA_API_KEY` | GitHub Secrets, `.env` | optional Indian news source |
| Supabase anon key | `frontend/js/config.js` | **public on purpose**; RLS protects the data |

`.env.example` lists them with placeholders. `.env` is never committed.

---

## 11. Security in one page

| Layer | What protects us |
|---|---|
| Database | RLS on every Supabase table; checks and rate limits in `hardening.sql` |
| Sign-in | Supabase Auth, bcrypt passwords, signed tokens |
| Page | **Content-Security-Policy** (a rule in `index.html` that blocks any script not ours), anti-framing, referrer policy |
| Data shown | Every headline and note is **escaped** (shown as text, never run as code); links pass `Util.safeUrl` (http(s) only); note HTML passes `Util.cleanHtml` |
| Secrets | Only in GitHub Secrets and `.env`; git history checked clean |
| Libraries | Exact versions pinned; supabase-js has an integrity hash |

The CSP allows our one small inline script by its **hash** (a fingerprint of its exact text). Edit
that script and the hash must be refreshed with `python -m agent.publish_static --stamp-only`, or the
browser blocks it. Every decision is in [SECURITY.md](../SECURITY.md).

---

## 12. Testing

```bash
python scripts/selftest.py     # 104 offline tests, a few seconds, no internet or keys needed
```

They check, among other things: link cleaning, feed parsing, feed discovery, triage rules, score
parsing and the Groq-then-Gemini chain, trend picks, source categories, switched-off sources, the
CSP hash and the page's asset fingerprints. Before any push, they must all pass. Other checks:
`python -m agent.ingest --dry-run` (fetch every feed, save nothing) and browser checks on the live site.

---

## 13. Limits and costs, in numbers

| Limit | Number | Effect |
|---|---|---|
| Groq free calls | 1,000 a day, ~11 a minute | scoring is capped at **200 a day** |
| Articles arriving | ~210 news items a day + trend watches | busy days leave a backlog; Gemini helps |
| GitHub Actions | 2,000 free minutes a month (private repo) | why scoring is capped |
| Supabase free | 500 MB database | rate limits stop one account filling it |
| Cloudflare cache | 4 hours | fingerprints keep files fresh |
| Stories on the site | last 30 days, score 55+ | ~1,700 stories in `data.js` |
| Processing window | 14 days | older unscored items are skipped |

Running cost today: **zero**. The first thing to pay for, if usage grows, would be the AI (a paid Groq
tier removes the 200-a-day cap).

---

## 14. "If I ask for X, what changes?"

| Request | What an engineer changes | Size |
|---|---|---|
| Add a source | one line in `agent/sources.py` (or a member requests it on the site, no code) | tiny |
| Change Breaking/Major thresholds | `agent/config.py` and `frontend/js/config.js`, together | tiny |
| Add a competitor name | `COMPETITORS` in `frontend/js/config.js` | tiny |
| Show 10 stories in Today | `frontend/js/config.js` and the Settings options | small |
| Better "why it matters" lines | the prompt in `agent/score.py`; test on real examples first | small, needs care |
| A new domain (e.g. "Climate law") | the prompt, `DOMAINS` in both config files, colours | medium |
| Saved stories follow you across devices | a new Supabase table + RLS, `supabase.js`, `user-state.js` | medium |
| Email digest | **against the product rules** (the website is the only notifier) | n/a |
| Score more than 200 a day | a paid AI tier or a second free provider | small code, money |
| A mobile app | a new project; the site already works on phones | large |
| Custom domain | Atlair setting, DNS, Supabase redirect URLs, Google sign-in settings | small, no code |

---

## 15. File map

```
news-agent/
├── agent/                    BACKEND (Python pipeline)
│   ├── config.py             settings and thresholds
│   ├── sources.py            the source list
│   ├── normalize.py          cleans links, dates, text
│   ├── db.py                 talks to Neon
│   ├── trends.py             trend watches
│   ├── ingest.py             collect
│   ├── triage.py             drop noise
│   ├── extract.py            download article text
│   ├── embed.py              meaning-numbers
│   ├── score.py              AI scoring
│   ├── cluster.py            same-event groups
│   ├── threads.py            long-running narratives
│   ├── publish_static.py     writes data.js
│   └── pipeline.py           runs all stages (local use)
├── frontend/                 FRONTEND (deployed as-is)
│   ├── index.html            every screen
│   ├── privacy.html          privacy page
│   ├── data.js               the news (generated)
│   ├── css/                  styles
│   ├── js/                   behaviour
│   └── favicon.*             icons
├── sql/                      DATABASE definitions (run by hand in Neon / Supabase)
├── scripts/                  selftest.py, push_site_data.sh
├── .github/workflows/        AUTOMATION (the timers)
├── docs/                     these documents
├── requirements.txt          Python libraries
├── .env.example              list of secrets needed
├── README.md                 plain-English overview
└── SECURITY.md               security decisions
```

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **Async** | Doing many waits at once (fetching 8 feeds together instead of one by one) |
| **Cache / CDN** | Copies of files kept close to users so pages load fast (Cloudflare) |
| **Commit / push** | Saving a change in git / sending it to GitHub |
| **Cosine similarity** | How alike two embeddings are, from 0 (unrelated) to 1 (identical) |
| **CSP** | Content-Security-Policy: the browser rule listing which scripts may run |
| **Cron** | A timer schedule, like "every day at 07:01" |
| **Dry run** | Run without saving anything, to see what would happen |
| **Embedding / vector** | A list of numbers that captures a text's meaning |
| **Escaping** | Showing text as text, so `<script>` in a headline can't run |
| **Feed (RSS/Atom)** | A site's machine-readable list of new articles |
| **Fingerprint (`?v=`)** | A tag from a file's content so a changed file gets a fresh address |
| **Foreign key** | A column pointing at a row in another table |
| **Index** | A lookup structure that makes database searches fast |
| **JSON** | A plain text format for structured data: `{"score": 84}` |
| **JWT / token** | The signed pass that proves who you are after sign-in |
| **LLM** | Large language model: the AI that reads and writes text |
| **Migration / SQL file** | A script that creates or changes database tables |
| **pgvector** | The Postgres add-on that stores embeddings and finds similar ones |
| **Prompt** | The written instructions sent to the AI |
| **Rate limit** | A cap on how often something may be called |
| **Regex** | A text pattern, used by triage to spot noise |
| **REST** | The common style of web API: an address per resource, standard verbs |
| **RLS** | Row Level Security: database rules on who may see or change each row |
| **RPC** | Calling a named database function over the API |
| **Static site** | A site of fixed files, no server code |
| **Trigger** | Database code that runs automatically when a row is saved |
| **YAML** | The settings format GitHub Actions uses |

---

**Related documents:** [architecture.md](architecture.md) (engineer's summary),
[developer-guide.md](developer-guide.md) (setup and commands), [prd.md](prd.md) (what the product
must do), [SECURITY.md](../SECURITY.md).
