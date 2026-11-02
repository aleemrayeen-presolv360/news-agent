# News Intel security review

**Last updated:** 2 November 2026
**Covers:** the website (`frontend/`), the Supabase database, the news pipeline (`agent/`), GitHub Actions and the git history.
**Why now:** since 30 October anyone can create an account (by email or Google), so everything a signed-in member can do had to be safe for a stranger to do too.

## Summary

- **No secret has ever been committed.** I checked every commit up to 2 November. The only key in the website is Supabase's public "anon" key. It is meant to be public: the database rules protect the data, not the key.
- **I found one real hole and fixed it:** a member could send a source request whose link was `javascript:`. If an admin clicked that link, the member's code would run as the admin.
- **There were seven smaller gaps.** All are fixed in code. The database part needs one SQL file run in Supabase (step 1 below).
- **The biggest risk now is your accounts, not the code.** Turn on two-factor sign-in (step 3).

Key: ✅ done · 👤 needs you · ➖ not needed (with the reason)

---

## What you need to do

| # | What | Where | Time |
|---|---|---|---|
| 1 | Run [sql/hardening.sql](sql/hardening.sql) | Supabase → SQL Editor → New query → paste the whole file → **Run**. Expect "Success. No rows returned". | 1 min |
| 2 | Three Supabase settings: **(a)** Minimum password length **8**. **(b)** Turn on **CAPTCHA** (Cloudflare Turnstile is free; tell me before you switch it on, because the sign-in form needs a small change). **(c)** Under **Redirect URLs**, keep only `https://news-agent.atlair.app` and `http://localhost:8000`. | **(a)** Authentication → Providers → Email (in some dashboard versions: Authentication → Policies) **(b)** Authentication → Attack Protection **(c)** Authentication → URL Configuration | 5 min |
| 3 | Turn on **two-factor sign-in** | GitHub, Supabase, Google Cloud, Neon, Atlair | 15 min |
| 4 | Make the repo **private** | GitHub → Settings → General → Danger Zone. Check that Atlair still deploys afterwards. | 2 min |
| 5 | Decide on `ANALYSIS.md` (an old notes file that was never committed) and the empty `TELEGRAM_*` lines in your local `.env` | Delete both if you don't need them. I left them alone because they are your files. | 1 min |

**If something breaks after step 1:** run [sql/hardening_rollback.sql](sql/hardening_rollback.sql) the same way. It removes only this batch and deletes no data.

---

## Every point, decided

| # | Point | Status | Decision and reason |
|---|---|---|---|
| 1 | Hide API keys | ✅ | Every commit is clean. Pipeline keys (Groq, Gemini, Neon, Cloudflare, Notion) live only in GitHub Secrets and your local `.env`. The Supabase anon key in `config.js` is public by design. |
| 2 | Check env variables | ✅ 👤 | `.env` has never been committed and git ignores it. `.env.example` holds placeholders only. Left for you: the empty `TELEGRAM_*` lines (step 5). |
| 3 | Protect admin routes | ✅ | Admin pages are hidden on the site, but the real lock is in the database: every admin action is checked against your role there. Typing an admin page's address gets a member nothing. The `javascript:` hole that could have hijacked an admin session is fixed (#8). |
| 4 | Proper authentication | ✅ 👤 | Supabase handles sign-in: secure tokens, email confirmation and Google. **Fixed:** if the sign-in service failed to load, the live site used to fall back to a pretend "demo" sign-in. Demo mode now works only on `localhost`; elsewhere you see "Can't reach the sign-in service". **Left for you:** password length 8 and CAPTCHA (step 2). |
| 5 | Users only reach their own data | ✅ | Tested on 29 October: signed-out visitors get nothing, and members see only their own notes, saves and settings. **Fixed** (in `hardening.sql`): members could change the email on their profile, or fake the "requested by" email on a request and in the audit log. Emails now always come from the sign-in token. Members can also no longer write fake admin entries ("approved", "changed a role") into the audit log. |
| 6 | Sanitise forms | ✅ | The forms already checked input, but someone calling the database directly could skip those checks. The database now refuses links that aren't `http(s)`, and text over the limits: name 200, link 2,000, reason 1,000, note 10 MB. The forms have matching length limits. |
| 7 | Protect against XSS | ✅ | **The real hole, now closed in three layers:** (1) every link built from feed or user data passes `Util.safeUrl`, so only `http(s)` links work; (2) the database refuses other links; (3) the page's security policy blocks injected scripts. **Also:** note HTML is now cleaned before it is shown, keeping only editor formatting, links and pasted images. Feed text was already escaped everywhere. |
| 8 | Rate limiting | ✅ | Supabase already limits sign-in and sign-up attempts. **Added:** limits on database writes per person: 100 new notes an hour and 2,000 in total, 10 source requests a day (admins unlimited), and 200 audit entries an hour. One account can no longer fill the free 500 MB database. |
| 9 | Secure API endpoints | ✅ | We have no server of our own. The browser talks straight to Supabase, where every request passes the database rules. The one public function, `approved_source_feeds()`, returns only approved feed names and links. Pipeline jobs use secrets that exist only in GitHub. |
| 10 | CORS settings | ➖ 👤 | No change needed: any site may call Supabase, but every call still needs a sign-in token and passes the rules. Do check the Redirect URLs list (step 2c), because that is what stops a sign-in being redirected to someone else's site. |
| 11 | Security headers | ✅ partly | **Added inside the page**, because Atlair sends no security headers and supports no headers file (`_headers` returns 404): a **Content-Security-Policy** (scripts only from our site, the pinned Supabase library and our one inline script; data only to our Supabase project; no plugins, frames or outside form posts), a **referrer policy**, and an **anti-framing check** (the page hides itself inside another site's frame). **Can't be done from the page:** HSTS and the real `frame-ancestors` header must come from the host. Plain `http://` currently errors instead of redirecting. Ask Atlair whether they can add these, or move hosting later (see "Later" below). |
| 12 | Turn off debug mode | ➖ | There is no debug mode, debug flag or stray `console.log`. Only real errors go to the console. |
| 13 | Update dependencies | ✅ | Everything is pinned to exact versions, and the Supabase script carries an integrity hash. Pillow, pulled in by `fastembed`, has known flaws. None can be triggered, because we never open images, and Pillow can't be upgraded until `fastembed` allows it. Check again when `fastembed` releases a new version. **Fixed:** three GitHub workflows (`ingest`, `addendum`, `retention`) didn't state their permissions; they are now read-only. The four that push data keep write access. |
| 14 | Remove what's not needed | 👤 | The code cleanup was done on 30 October. Left for you: `ANALYSIS.md` and the Telegram lines (step 5). |
| 15 | Exposed files | ✅ | Only the `frontend/` folder is online. `.env`, `.git`, the Python code, the SQL files, `README.md` and `ANALYSIS.md` all return 404 on the live site (checked 2 November). `data.js` (the stories) is public by design. |
| 16 | Secure the database | ✅ 👤 | Row Level Security is on for all 6 tables (`security.sql`), and `hardening.sql` adds the checks above. The news database (Neon) can only be reached with its secret. **Left for you:** two-factor sign-in on every account (step 3). |
| 17 | Hash passwords properly | ➖ | Supabase stores passwords hashed with bcrypt. Our code never sees or stores a password. |
| 18 | Git history for leaked secrets | ✅ | All clean (checked 30 October and again on 2 November for the commits since). Making the repo private is about keeping the code private, not about cleaning up a leak. |
| 19 | Full security audit | ✅ | This document. |

---

## What changed, file by file

| File | Change |
|---|---|
| [frontend/js/util.js](frontend/js/util.js) | New `safeUrl` (only `http(s)` links) and `cleanHtml` (allow-list cleaner for note HTML; uses an inert parser, so nothing runs while it cleans). |
| [frontend/js/settings.js](frontend/js/settings.js), [stories.js](frontend/js/stories.js), [notes.js](frontend/js/notes.js) | Every link from feed or user data goes through `safeUrl`. Notes are cleaned before they are shown. Clear messages when the database refuses a write. Length limits on inputs. |
| [frontend/js/supabase.js](frontend/js/supabase.js), [auth.js](frontend/js/auth.js) | Demo mode only on `localhost`. |
| [frontend/index.html](frontend/index.html), [privacy.html](frontend/privacy.html) | Content-Security-Policy, referrer policy, anti-framing check, input length limits. |
| [agent/publish_static.py](agent/publish_static.py) | The existing `--stamp-only` step now also writes the inline script's hash into the policy, and always writes LF line endings. |
| [scripts/selftest.py](scripts/selftest.py) | 2 new tests: the policy hash is refreshed and matches the page. 110 tests pass. |
| [sql/hardening.sql](sql/hardening.sql), [hardening_rollback.sql](sql/hardening_rollback.sql) | New database checks, real emails, write limits; and their undo. |
| `.github/workflows/ingest.yml`, `addendum.yml`, `retention.yml` | `permissions: contents: read`. |

## How it was tested

- **Self-test:** 110 passed, 0 failed.
- **Real browser (Chrome), 17 checks, all passed:**
  - No security-policy violations on the sign-in page, Today, Stories, Notes, Settings or the privacy page.
  - The Supabase library and Google button still work under the policy.
  - A note planted with a script-carrying image and a `javascript:` link opens clean in the editor, and nothing runs even when the link is clicked.
  - `safeUrl` refuses `javascript:`, `data:` and `//` links.
  - Demo sign-in works on localhost and is refused on any other address.
  - Inside another site's frame, the page hides itself.
- **Live site after the push (`7d58743`), all passed:**
  - the policy is in place;
  - Supabase and Google sign-in work, and a password sign-in reaches Supabase;
  - no pretend demo sign-in;
  - no errors from our own code.

  The only reported violations are the two Cloudflare scripts above, blocked on purpose.
- **The SQL has not been run yet.** I wrote a test that runs `supabase.sql`, `security.sql` and `hardening.sql` on a throwaway copy of Postgres and tries each attack (26 checks). This laptop couldn't run it: Docker Desktop wouldn't start, and running downloaded Postgres programs was blocked. The SQL was checked by reading it instead. It is written to be safe:
  - existing rows are not re-checked (`NOT VALID`);
  - the SQL Editor and the pipeline skip every new rule;
  - one rollback file undoes all of it.

  After you run it, I'll do a live check (step 1 above).

## Trade-offs I chose

- **The policy blocks two scripts our host adds to every page.** Atlair serves the site through Cloudflare, which injects:
  - a bot-detection inline script ("challenge-platform") with a new token on every request, so it can't be allowed by hash;
  - the Cloudflare Web Analytics beacon (`static.cloudflareinsights.com`).

  Nothing of ours uses either. Allowing the first would need `'unsafe-inline'`, which turns off the protection against injected scripts. The second tracks visitors, and [privacy.html](frontend/privacy.html) says we don't. Both stay blocked. The only side effect is two "Content Security Policy" lines in the browser console on each page load, and they are expected. Checked live on 2 November: sign-in, Supabase, Google sign-in and the privacy page all work.
- **`style-src 'unsafe-inline'` stays in the policy.** A few layout widths are set inline. Allowing inline styles can't run code, and the script rules are what stop XSS.
- **Referrer policy is `strict-origin-when-cross-origin`**, not `no-referrer`. Outlets see only `news-agent.atlair.app`, never the page or story you came from.
- **Note limit is 10 MB**, because notes hold pasted images as text (one 2 MB image is about 2.7 MB).
- **Admins have no source-request limit.** They are trusted, and the "Add source" button files its sources as approved requests.
- **Old rows are not re-checked.** Nothing existing is refused, but an old row only passes the new checks again once it is edited.
- **Source categories have no fixed list in the database,** only a length limit. Older rows may use other names, and a strict list could stop an admin toggling them.

## Later, not urgent

- **Hosting with real headers.** If Atlair can't add HSTS, `frame-ancestors` and an http→https redirect, Cloudflare Pages and Netlify both do this for free with a `_headers` file.
- **Custom email sender (SMTP).** Supabase's built-in email sends only a few messages an hour, which caps sign-ups and password resets. Resend or Brevo have free plans.
- **Recheck Pillow** whenever `fastembed` releases a new version.
- **Review this file** whenever a new kind of user input is added (new form, new table, new public page).
