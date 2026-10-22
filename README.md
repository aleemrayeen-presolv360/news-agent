# News Intel

A weekly news-intelligence website for Presolv360. A Python pipeline reads dozens of
news feeds, uses an AI model to rank every story, and publishes the important ones to a
simple website where the team reads, saves and takes notes.

**In one sentence:** feeds go in, an AI ranks them, the website shows the ones that matter
and tells you why.

---

## Contents

1. [How it works](#how-it-works)
2. [Quick start](#quick-start)
3. [Project layout](#project-layout)
4. [The website](#the-website)
5. [The pipeline](#the-pipeline)
6. [Databases](#databases)
7. [Configuration](#configuration)
8. [Schedules (GitHub Actions)](#schedules-github-actions)
9. [Common tasks](#common-tasks)
10. [Troubleshooting](#troubleshooting)
11. [Security notes](#security-notes)
12. [Known gaps and next steps](#known-gaps-and-next-steps)

---

## How it works

```
 News feeds (RSS)                  Python pipeline (agent/)                     Website (frontend/)
 ────────────────                  ────────────────────────                     ───────────────────
 OpenAI, Electrek,     ──every──▶  ingest (+ trend watches)                     index.html + js/ + css/
 Bar & Bench, Nature …   4 hours     │                                                  │
                                     ▼                                                  │ reads
                  Daily 07:01:  trends ─▶ ingest ─▶ triage ─▶ extract ─▶ embed          ▼
                                     │      ─▶ score (Groq AI)
                                     │      ─▶ cluster ─▶ threads                 frontend/data.js
                                     │                                                  ▲
                                     └─▶ publish_static ─────────────── writes ─────────┘
                  Friday 12:01: same, plus publish (Notion page, optional)

 Storage:  Neon Postgres + pgvector  →  all articles, scores, embeddings (pipeline only)
           Supabase                  →  sign-in, notes, source switches, audit log (website only)
```

There are two halves that only meet at one file:

- **The pipeline** (`agent/`, Python) does all the heavy work and writes `frontend/data.js`.
- **The website** (`frontend/`, plain HTML/CSS/JavaScript, no build step) reads `data.js`
  for news and uses Supabase for accounts and notes.

The website has no backend API of its own. That keeps it fast, free to host, and working even
when offline.

---

## Quick start

### See the website

**Live site:** <https://news-agent.atlair.app/>

Or run locally:
```bash
cd frontend
python -m http.server 8000
```

Open <http://localhost:8000> and sign in with your Supabase account. It shows whatever is in
`frontend/data.js` right now.

> No Supabase? If the Supabase script can't load, the site runs in **demo mode**: any email
> and a 6+ character password signs you in, and everything is stored in the browser only.

### Run the pipeline locally

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env, then fill it in

python scripts/selftest.py        # offline tests, should end "84 passed, 0 failed"
python -m agent.ingest --dry-run  # fetch every feed, write nothing, print a report
python -m agent.pipeline          # run every stage for real (needs .env filled in)
```

---

## Project layout

```
news-agent/
├── agent/                   Python pipeline (one file per stage)
│   ├── config.py            settings, score thresholds, IST week window, env helper
│   ├── sources.py           the feed list the pipeline fetches (75 entries, 67 enabled)
│   ├── normalize.py         clean URLs and feed entries, so duplicates collapse
│   ├── db.py                Neon connection, inserts, source health
│   ├── ingest.py            stage 1: fetch feeds → raw_items
│   ├── extract.py           stage 2: download article text, detect paywalls
│   ├── embed.py             stage 3: 384-dim embedding per article → news_memory
│   ├── triage.py            stage 4: drop noise (job posts, PR, listicles), gate arXiv papers
│   ├── score.py             stage 5: AI score 0–100 + people/companies + "why it matters"
│   ├── trends.py            daily: pick trending topics and watch them through Google News
│   ├── cluster.py           stage 6: group coverage of the same story
│   ├── threads.py           stage 7: link stories into ongoing narratives across weeks
│   ├── publish_static.py    writes frontend/data.js (what the website shows)
│   ├── publish.py           optional weekly digest page in Notion
│   ├── addendum.py          optional Saturday "late breaking" add-on to the Notion page
│   ├── retention.py         optional: archive Notion pages older than 30 days
│   ├── pipeline.py          run all stages in order (for local runs)
│   └── notion.py            shared Notion client
├── frontend/                the website (static files, deploy this folder)
│   ├── index.html           every screen and dialog lives here
│   ├── data.js              GENERATED by publish_static.py; don't edit by hand
│   ├── css/                 base.css (colours, type, controls) + one file per screen
│   └── js/                  one file per screen + shared helpers (see "The website")
├── sql/
│   ├── schema.sql           Neon tables for the pipeline (safe to re-run)
│   └── supabase.sql         Supabase tables for the website
├── scripts/selftest.py      offline tests: URLs, week window, feeds, queues, scoring, trends
├── .github/workflows/       the schedules (see below)
├── .env.example             every setting the pipeline needs, with where to get it
└── requirements.txt         Python packages
```

---

## The website

### Screens

| Screen | Address | What it's for |
|---|---|---|
| **Today** | `#/today` | Home. A short list (5 by default) of the most important stories you haven't read. Read them one at a time with **→**, then it says "Up to date". |
| **All stories** | `#/stories` | Everything, Gmail-style: folders (Trending / Breaking / Major / Notable), categories, domains, a date filter, sort, and a reading pane. |
| **Saved** | `#/saved` | Stories you pressed **S** on. A copy is kept, so they stay after leaving the weekly file. |
| **Notes** | `#/notes` | Private notes that save as you type. Press **N** on any story to add it to a note. |
| **Settings** | `#/settings` | Preferences (including the domains you follow), hide sources you don't need, change your password. |
| **Admin** (admins only) | inside Settings | Turn sources on/off for everyone, change roles, read the audit log. |

Every filter is in the address bar (for example `#/stories?folder=breaking&from=2026-10-01`), so
**Back**, refresh, bookmarks and Ctrl-click all work.

**Keyboard:** `Ctrl K` or `/` search · `J`/`K` next/previous · `S` save · `N` add to note ·
`E` read/unread · `O` open article · `C` new note · `?` all shortcuts.

### How stories are labelled

The AI score is never shown. Readers see a label instead:

| Label | Score | Meaning |
|---|---|---|
| **Breaking** (red) | 85 and up | Read this today. A banner at the top of the site shows it until you read or dismiss it. |
| **Major** | 70–84 | Important this week. |
| **Notable** | 55–69 | Worth a look if it's your area. |

Stories below 55 never reach the website. The scoring model puts each story in a **domain**
(AI, Chips and computing, EVs and mobility, Space, Health and biotech, Energy and climate, Robotics,
Fintech, Cybersecurity, Gadgets and internet, Science, Tech policy, Legal India, Business), shown on
the story. Each domain belongs to one of four **categories** used for filters and colours: Tech and
science, Legal India, Market (Business) and Competitors (found by company name, `COMPETITORS` in
`frontend/js/config.js`). Stories scored before domains existed (before 21 Oct 2026) are guessed
from keywords, with AI as the fallback since scoring was AI-only then. The domain list lives in
`agent/config.py` and `frontend/js/config.js`; change both together.

### Notices (the website is the only notifier)

The pipeline sends no Telegram, email or chat alerts. Everything shows on the site, in a bar under the top bar
(`frontend/js/notices.js`):

- **Breaking stories** from the last 3 days that you haven't read. The browser tab title counts them
  too, for example "(2) Today · News Intel". Opening the story or pressing ✕ clears it.
- **News is out of date**, when `data.js` is more than 30 hours old. That means the daily workflow
  failed or didn't run, so it doubles as the failure alert.
- **For admins: the pipeline needs a look**, when the last run reported a problem (feeds not fetched
  for 10+ hours, Groq quota low or used up, a backup model used, stories that couldn't be scored).
  Settings → Sources has a **Pipeline health** panel with the details, plus feeds that keep failing.

The pipeline writes this into `data.js` as `health` (`publish_static.py`).

A **Trending** tag marks stories that came from a trend watch or that 3+ of our sources carried.

**Today's list** takes the highest-ranked unread stories from the domains you follow (Settings →
Preferences; all of them by default). Breaking stories always come through, and no domain gets more
than 2 of the slots, so one busy domain can't fill the list.

### Where things are stored

| What | Where |
|---|---|
| News | `frontend/data.js` (static file) |
| Accounts, roles | Supabase `auth` + `profile` table |
| Notes | Supabase `note` table, plus a browser copy so notes work offline |
| Source on/off for everyone | Supabase `source` table |
| Admin history | Supabase `audit_log` table |
| Read/unread, saved stories, hidden sources, preferences, Today's list | Browser storage, per user |

### JavaScript files (`frontend/js/`), in load order

| File | Job |
|---|---|
| `config.js` | Supabase URL and public key, category names, score thresholds |
| `util.js` | HTML escaping, India-time dates, safe browser storage, toasts |
| `supabase.js` | Every Supabase read/write (`db.*`), with a browser-storage fallback |
| `stories.js` | Turns `data.js` into stories: label, category, search, the story view |
| `user-state.js` | Read, saved, hidden sources, preferences, Today's list |
| `auth.js` | Sign in, create account, reset and set password |
| `today.js` | The Today screen |
| `reader.js` | All stories and Saved, including the date filter |
| `notes.js` | Notes screen and the "Add to note" dialog |
| `default-sources.js` | The first source list put into Supabase when its table is empty |
| `settings.js` | Settings and admin screens |
| `palette.js` | `Ctrl K` search |
| `notices.js` | The notice bar (Breaking, out-of-date news, pipeline problems) and the Pipeline health panel |
| `app.js` | Starts everything, routes between screens, keyboard, offline banner |

### Design

Colours come from a lawyer's desk: **signature ink** `#1E3570` for anything you can act on,
**red tape** `#B8282B` only for Breaking, **manila** `#EFE5CC` for things you kept.
Headlines use *Newsreader*, the interface uses *Public Sans*. Light and dark themes follow
the laptop's setting. Built for 1366 × 768 laptops first. All tokens are at the top of
`frontend/css/base.css`.

---

## The pipeline

Each stage is a separate command and can be run alone. Each one only picks up rows the
previous stage finished, so re-running is always safe.

| Stage | Command | What it does |
|---|---|---|
| ingest | `python -m agent.ingest` | Fetches every enabled feed in `sources.py`, cleans URLs so the same article from two feeds counts once, stores new items. A dead feed never stops the run; it's recorded instead, and after 3 failures in a row it's only retried once a day. Active trend watches are fetched too. A source's first successful fetch keeps only its last 24 hours (`FIRST_FETCH_HOURS`); older items are stored as already seen, so a new source never queues weeks of old news. If a new feed's list doesn't reach back 24 hours, a Google News `site:` search fills in the rest of that day. |
| triage | `python -m agent.triage` | Runs first, on everything (it only reads titles, so it's free). Drops obvious noise: job posts, PR, funding fluff, events, listicles. arXiv papers only pass if they have 10+ upvotes on Hugging Face Daily Papers; without this, papers (about 88% of what's fetched) would queue ahead of news. |
| extract | `python -m agent.extract` | Downloads the page of each article that passed triage in the last 14 days (`PROCESS_DAYS`), news before papers, and pulls out the text. Marks paywalls. A failed download (sites that block bots, Google News links) is stored as empty text, so it's tried once and then scored from its feed summary. |
| embed | `python -m agent.embed` | Turns each article from the last 14 days into a 384-number vector (model `BAAI/bge-small-en-v1.5`, runs locally), news before papers. |
| score | `python -m agent.score` | Asks the Groq AI model for the story's domain and for novelty, impact and relevance (0–25 each, judged within that domain, so an EV or space story competes fairly with AI), people/companies, topics and one "why it matters" sentence. News is scored before papers. Groq's free tier allows 1,000 calls a day and 8,000 tokens a minute (about 11 calls), so the scorer waits when Groq asks it to. Backups: Cerebras (same Qwen family, only if `CEREBRAS_API_KEY` is set), then Cloudflare Workers AI. Each score records which model made it. Every run saves its usage and any warnings (fewer than 150 Groq calls left, quota used up, a backup model used, items failed) to the `runs` table; the website shows them to admins. `--ingested-within-hours N` scores only what was just fetched. |
| cluster | `python -m agent.cluster` | Groups articles about the same event (very similar text + a shared company or person, within 72 hours). |
| threads | `python -m agent.threads` | Links stories into ongoing narratives across weeks. |
| publish_static | `python -m agent.publish_static` | Writes `frontend/data.js`: every story scored 55+ from the last 30 days (`WEBSITE_DAYS`). |
| publish | `python -m agent.publish` | Optional Notion digest page. |
| trends | `python -m agent.trends` | Daily, before ingest. Reads Google Trends (India, US) and the names 3+ of our sources mention in a day. One Groq call keeps the newsworthy ones and writes a 2–5 word search (it never writes feed links). Each becomes a trend watch for 5 days: a last-day Google News search, 8 items a fetch. Up to 3 new a day, 8 at once. |

Every stage accepts `--dry-run` (show what would happen, write nothing). Most accept `--limit N`.
Run everything in order with `python -m agent.pipeline` (add `--stage score` to start part-way).

### How the score is made

```
score = source tier points + novelty (0–25) + impact (0–25) + relevance (0–25)

tier points:  A university / public lab   25
              B company research lab      22
              C journal / preprint        20
              D press                     12
```

Thresholds live in `agent/config.py` (`SCORE_BREAKING`, `SCORE_MAJOR`, `SCORE_NOTABLE`) and are
mirrored in `frontend/js/config.js`. Change both together.

### The week

A digest week runs **Sunday 00:00 → Friday 12:00 India time**. News from Friday afternoon is
picked up by the Saturday addendum. The maths is in `agent/config.py` and tested in
`scripts/selftest.py`.

---

## Databases

### Neon (pipeline), `sql/schema.sql`

| Table | Holds |
|---|---|
| `sources` | One row per feed in `sources.py`, plus health: last success, failures, last error |
| `raw_items` | Every article ever fetched (deduplicated by clean URL) |
| `news_memory` | Articles that passed triage: embedding, score, entities, topics, why it matters. Never deleted. |
| `clusters` | Groups of articles about the same story |
| `threads` | Ongoing narratives across weeks |
| `runs` | One row per ingest run (counts, failures) and per score run (models used, Groq calls left, items waiting). Powers health stats. |
| `trend_watches` | Trending topics being followed: search words, domain, why, expiry. Created by the first trends run. |
| `feedback` | Reserved for future reader ratings |

Create once: paste `sql/schema.sql` into Neon's SQL Editor, or `psql "$NEON_DSN" -f sql/schema.sql`.

### Supabase (website), `sql/supabase.sql`

| Table | Holds |
|---|---|
| `profile` | Name, email and role (`user` = Member, `admin`) for each account. Created on sign-up by a trigger. |
| `note` | Notes (HTML), pinned flag, timestamps |
| `source` | The source list shown in Settings and its on/off switch |
| `audit_log` | Sign-ins and admin actions |
| `user_setting` | Exists but unused for now |

---

## Configuration

### Pipeline secrets: `.env` locally, GitHub Secrets in production

| Variable | Needed for | Where to get it |
|---|---|---|
| `NEON_DSN` | everything | Neon dashboard → Connection string → *Pooled*. Must end `?sslmode=require`. |
| `GROQ_API_KEY` | score | <https://console.groq.com/keys> (free) |
| `CF_ACCOUNT_ID`, `CF_API_TOKEN` | score (last backup) | Cloudflare → Workers AI. Optional but recommended. |
| `CEREBRAS_API_KEY` | score (first backup) | <https://cloud.cerebras.ai> (free). Optional. `CEREBRAS_MODEL` overrides the default `qwen-3.8-27b`. |
| `NOTION_TOKEN`, `NOTION_VERSION`, `NOTION_DS_*` | optional Notion digest | Notion → Integrations. Share each database with the integration. |

Never commit `.env`; it's in `.gitignore`.

### Website: `frontend/js/config.js`

Supabase URL and **anon** key (public by design), category names, competitor names used for
the Competitors category, score thresholds, and the Today list size.

### Supabase dashboard settings

- **Authentication → URL Configuration → Redirect URLs:** add every address the site runs on.
  Currently configured: `https://news-agent.atlair.app` and `http://localhost:8000`.
  Password-reset links only work for listed addresses.
- **Authentication → Providers → Email:** if "Confirm email" is on, new accounts must click the
  email link before signing in. The site says so after sign-up.

---

## Schedules (GitHub Actions)

GitHub cron is in **UTC**; India is UTC+5:30. All times below are India time.

| Workflow | When | Does |
|---|---|---|
| `ingest.yml` | every 4 hours (:37 past) | fetch feeds |
| `daily.yml` | every day 07:01, catch-up 09:01 | trends → ingest → triage → extract (800) → embed (1000) → score (up to 250) → cluster → threads → **`data.js`** (with pipeline health) → commit. The 09:01 run stops at once if 07:01 already refreshed the site. |
| `new-source.yml` | when `agent/sources.py` changes on `main` | ingest (new sources keep their last 24 hours) → score what was just fetched → **`data.js`** → commit, so a new source is on the site in about 10 minutes |
| `publish.yml` | Friday 12:01 | the same (score up to 150) → **`data.js`** → commit → Notion digest |
| `addendum.yml` | Saturday 08:00 | process Friday-afternoon news, Notion add-on |
| `retention.yml` | daily 03:00 | archive Notion pages older than 30 days |
| `keepalive.yml` | 1st of the month | tiny commit so GitHub doesn't pause the schedules. **Don't delete it.** |

Each workflow can also be run by hand: Actions tab → pick it → **Run workflow**. A failed daily run
shows on the website as "News is out of date" the next day; GitHub also emails the repo owner about
failed runs (GitHub → Settings → Notifications → Actions).

> **The website gets new stories every morning**, when `daily.yml` writes `data.js`. Feeds are
> fetched every 4 hours, but scoring runs once a day: Groq's free tier allows about 11 scoring calls
> a minute, and time spent waiting on it counts against the 2,000 free Actions minutes. To refresh
> sooner, run the daily workflow by hand, or locally: `python -m agent.pipeline --stage triage`.
> GitHub sometimes delays scheduled runs by hours or skips them when it's busy, which is why
> `daily.yml` fetches feeds itself and has a 09:01 catch-up.

### Deploying the website

**Current deployment:** <https://news-agent.atlair.app/> (hosted on Atlair)

`frontend/` is a plain static folder. Any static host works: Vercel, Netlify, Atlair, or GitHub
Pages. Because `daily.yml` and `publish.yml` commit `data.js`, a host that redeploys on push picks up new
stories automatically.

**Supabase URL Configuration** (already done):
- Site URL: `https://news-agent.atlair.app`
- Redirect URLs: `https://news-agent.atlair.app`, `http://localhost:8000`

---

## Common tasks

**Add a feed the pipeline should fetch.** Add a `Source(...)` line to `agent/sources.py` (unique
`id`, tier A–D, feed URL), then run `python scripts/selftest.py` and
`python -m agent.ingest --dry-run`. Check how many items a day it publishes first: scoring keeps
up with about 250 a day on the free tier, and about 210 already arrive. For a topic without a good
feed, use `_google_news("search words")` in `sources.py`. On its first fetch the source brings in
its last 24 hours, and pushing the change to `main` runs `new-source.yml`, so those stories are on the
site in about 10 minutes (only ones scoring 55+). For two days Settings → Sources marks it "Added …".
The Settings → Sources screen does *not* add feeds to the pipeline (see Known gaps).

**Make someone an admin.** Supabase → Table Editor → `profile` → set `role` to `admin`. After
that, admins can change roles from Settings → Users.

**Refresh the website's news now.** `python -m agent.publish_static`, then commit
`frontend/data.js` (or run the publish workflow by hand).

**Change how many stories Today shows.** Each person can choose 3, 5 or 7 in Settings →
Preferences. The default is `DAILY_COUNT_DEFAULT` in `frontend/js/config.js`.

**Change the score thresholds.** `agent/config.py` and `frontend/js/config.js`, together.

**Check everything still works.** `python scripts/selftest.py` and
`python -m agent.pipeline --dry-run`.

---

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| Website shows "No stories yet" | `data.js` is empty. Run `python -m agent.publish_static`. |
| Sign-in says the password doesn't match | Wrong password, or the account was never confirmed. Use "Forgot password?". |
| Reset link opens the wrong page or errors | The site's address isn't in Supabase Redirect URLs. |
| A feed always fails | See Settings → Sources → Pipeline health, or `sources.last_error` in Neon. Some sites block cloud servers (MIT News and Cambridge return 403 from GitHub but work from a laptop; VentureBeat only serves known feed readers). After 3 failures a feed is retried once a day. |
| `score` fails | Groq key missing or rate-limited. Add the Cerebras and/or Cloudflare keys as backups. |
| "The news pipeline needs a look" (admins) | Read Settings → Sources → Pipeline health. For Groq warnings: the daily calls ran low or out. Lower `--limit` on the score step in `daily.yml`, add `CEREBRAS_API_KEY`, or remove a busy feed. |
| First pipeline step is slow | Neon's free plan sleeps when idle and takes a few seconds to wake. `db.connect()` retries once. |
| Scheduled jobs stopped | GitHub pauses schedules after 60 days without commits. Keep `keepalive.yml`. |

---

## Security notes

- **Row Level Security is off in Supabase.** The website only shows each person their own notes,
  but anyone holding the public anon key (which is in `config.js`) could read every note and every
  profile email directly from the database. Before storing anything sensitive, turn RLS on for
  `note` and `profile` with "owner only" policies.
- News text from feeds is escaped before it is shown, so a malicious headline can't run code in
  the page. Pasted text in notes is inserted as plain text.
- `.env` holds the pipeline secrets and must never be committed.

---

## Known gaps and next steps

1. **Settings → Sources doesn't control the pipeline.** `agent/sources.py` (67 enabled feeds across
   AI, EVs, space, health, energy, chips, security, robotics, science, Indian tech, Legal India,
   market and competitors) is what gets fetched. The Supabase `source` list only hides stories by
   source name. Many feeds in it were tested on 21 Oct 2026 and don't work (LiveLaw, Mondaq, India
   Kanoon, Financial Express, Entrackr, VCCircle and others), and some publish too much to score
   for free (Business Today, CNBC TV18, Tax Guru), so they were left out.
2. **Older stories have no domain.** Stories scored before 21 Oct 2026 get a keyword guess (AI by
   default) until they leave the 30-day window.
3. **Source names differ** between the pipeline ("NVIDIA Technical Blog") and Settings
   ("NVIDIA Blog"), so a few on/off switches don't match their stories. Same fix as 1.
4. **Scoring is slow on the free tier.** Groq allows about 11 scoring calls a minute, so the daily
   run scores at most 250. With ~200 news items a day plus trend watches, older items can age out
   of the 14-day window unscored on busy days. `CEREBRAS_API_KEY` adds a second free model.
5. **Many sites block downloads from cloud servers** (The Information, OpenAI, The Robot Report,
   Google News links). Those stories are scored from their feed summary or headline.
6. **Eight feeds have no working RSS** (Anthropic, Meta AI, Stanford HAI and others, marked
   `enabled=False` in `sources.py`). They need RSSHub or a search-based monitor.
7. **Turn on Row Level Security** in Supabase (see Security notes).
