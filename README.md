# News Intel

**A daily news briefing for the Presolv360 team.** Each morning it reads about 70 news sites,
ranks every story, and shows the team only the ones that matter, each with one line on why it
matters to Presolv360.

**Live site:** <https://news-agent.atlair.app/>
**Owner:** Aleem Rayeen

---

## The problem it solves

The team needs to follow four kinds of news: **tech and science**, **Indian legal news**,
**market and business news**, and **what competitors are doing**. That news is spread over dozens of
websites, and most of what they publish doesn't matter to an online dispute resolution company.
Reading them all would take hours every day.

News Intel does that reading for you. You open it in the morning and get a short list of what
actually matters.

---

## What a team member sees

### 1. Today (the home page)

The 5 most important stories you haven't read yet (you can choose 3, 5 or 7). You read them one at a
time, like a morning briefing, and it ends with **"Up to date"**. Each story shows:

- **what happened** (the headline and the outlet),
- **why it matters**, in one sentence written for Presolv360,
- **every outlet that covered it**, so you see one story once, not five times.

### 2. All stories

Everything from the last 30 days, laid out like an email inbox: a list on one side and the story on
the other. You can filter by importance, topic or date, and search with **Ctrl K**.

### 3. Saved and Notes

Press **S** to save a story for later. Press **N** to add a story to a private note. Notes save as you
type, and nobody else can see them.

### 4. Settings

Choose which topics you follow, hide sources you don't care about (only for you), and **ask for a new
source** by typing a website's address.

### What admins also get

Approve or reject source requests, switch a source off for everyone, make someone an admin, see a log
of every admin change, and see whether the news system is healthy.

---

## How stories are ranked

An AI model reads every story and gives it a hidden score out of 100, based on:

- **how trustworthy the source is** (a university lab counts more than a press release),
- **how new** the news is,
- **how big its impact** is,
- **how relevant** it is to Presolv360 (ODR, lending, Indian law, legal tech).

Readers never see the number. They see a label instead:

| Label | Meaning |
|---|---|
| **Breaking** (red) | Read this today. A bar at the top of the site shows it until you read it. |
| **Major** | Important this week. |
| **Notable** | Worth a look if it's your area. |

Anything scoring below "Notable" never reaches the site. That's how the noise is cut.

The "why it matters" line is written by the AI and labelled **"AI summary, may contain mistakes"**.

---

## How it works, in plain terms

```
  1. Collect            2. Clean up             3. Rank                 4. Publish
  ──────────            ──────────              ──────                  ─────────
  Read ~70 news   ──▶   Drop junk (job    ──▶   AI scores each    ──▶   The website gets
  sites every           posts, ads, lists)      story, groups           the new list every
  4 hours               and duplicates          the same event          morning at 7:01
```

- **Collecting** happens every 4 hours, all day.
- **Ranking and publishing** happen once a day, at **7:01 am India time**, with a backup run at
  9:01 am in case the first one is late.
- Everything runs on its own on GitHub's servers. Nobody has to press a button.

### How a new source gets added

1. A team member types a website's address in Settings → Request a source, and says why.
2. An admin approves or rejects it (a rejection needs a reason).
3. Once approved, the system finds that site's news feed by itself and starts reading it for
   **everyone**. Its stories appear after the next morning update.
4. Anyone who doesn't want it can hide it for themselves.

---

## How you're told about problems

**Only on the website.** There are no Telegram, email or chat alerts, by design.

- **"News is out of date"** appears if the morning update didn't happen. That's the failure alert.
- **Admins** see "The news pipeline needs a look" when something went wrong, with details in
  Settings → Sources → Pipeline health.

---

## What it costs to run

**Nothing so far.** Every service is on a free plan:

| Service | What it does for us |
|---|---|
| **GitHub** | Stores the code and runs the daily jobs |
| **Atlair** | Hosts the website |
| **Groq** (backup: **Google Gemini**) | The AI that ranks stories |
| **Neon** | Stores all the news articles |
| **Supabase** | Handles sign-in, notes and settings |

The one limit to know about: the free AI allows about **200 stories ranked a day**. On very busy news
days, some lower-priority stories may not get ranked.

---

## Is it safe?

Yes, for an internal tool. In short:

- Anyone can create an account (email or Google), but **each person sees only their own notes,
  saves and settings**. This is enforced by the database itself, not just the website.
- **Only admins** can approve sources or change roles.
- **No secret keys are in the code.**
- The site protects itself against harmful links or code hidden in a news headline or note.

The full list of every security decision is in [SECURITY.md](SECURITY.md).

**Still open (your call):** two-factor sign-in on the service accounts, and three Supabase settings.
Both were put off on 2 Nov 2026.

---

## Where things stand (2 November 2026)

**Working and live:** Today, All stories, Saved, Notes, Settings, source requests, admin tools,
Google sign-in, the privacy page, the security work, the new font (Geist) and the favicon.

**Before public launch, still needed:**

| Item | Waiting on |
|---|---|
| Terms and conditions page | Company name, city for governing law, contact email, start date; then a legal review |
| Custom domain (instead of `atlair.app`) | Buying the domain |
| Private code repository | Your decision on timing |

**Next improvement:** sharper "why it matters" lines. 10 real before/after examples will be shown for
approval first.

The full, up-to-date list is in [docs/tasks.md](docs/tasks.md).

---

## Design rules we keep

The site is meant to look like a serious reading tool, not a marketing page. So there are **no**
purple gradients, round pill buttons, emoji icons, fake numbers or reviews, flashy animations,
AI-made photos, or vague slogans. Every number on the site is real. More in
[docs/design.md](docs/design.md).

---

## Glossary

| Word | Meaning |
|---|---|
| **Source** | A news website we read (for example Bar & Bench, Economic Times). |
| **Feed** | The machine-readable list of new articles a website publishes. The system reads these. |
| **Pipeline** | The automatic process that collects, cleans, ranks and publishes the news. |
| **Score** | The hidden 0 to 100 importance rating the AI gives each story. |
| **Domain** | The topic of a story, such as AI, Fintech, Space or Legal India. |
| **Category** | One of the four big groups: Tech and science, Legal India, Market, Competitors. |
| **Trending** | A story many of our sources are carrying, or a topic that's trending on Google. |
| **ODR** | Online dispute resolution, Presolv360's business. |

---

## More detail

| Document | For | What's in it |
|---|---|---|
| [docs/prd.md](docs/prd.md) | Product | Requirements, features, launch checklist |
| [docs/tasks.md](docs/tasks.md) | Everyone | What's done, what's next, what's waiting on whom |
| [docs/design.md](docs/design.md) | Design | Colours, fonts, design rules |
| [docs/memory.md](docs/memory.md) | Everyone | Key decisions and why they were made |
| [SECURITY.md](SECURITY.md) | Everyone | Every security decision |
| [docs/tech-guide.md](docs/tech-guide.md) | PM, anyone curious | The whole system explained with real code: backend, APIs, databases, website |
| [docs/architecture.md](docs/architecture.md) | Engineers | How the system is built |
| [docs/rules.md](docs/rules.md) | Engineers | Coding rules |
| [docs/developer-guide.md](docs/developer-guide.md) | Engineers | Setup, commands, troubleshooting |
