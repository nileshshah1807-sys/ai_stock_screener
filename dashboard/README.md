# Winnow Dashboard

Private web dashboard for the daily screener. Replaces the emailed spreadsheet
and the static `dashboard_*.html` report with a searchable, filterable view of
the full scored universe.

Every view is nested under a market segment — `/ind` (India: NSE and the
companies listed on BSE alone) and `/us` — and the market switch beside the
brand moves between them, keeping the destination. `/` redirects to `/ind`, so
links saved before markets existed still resolve, and `/nse/...`, India's
segment until BSE joined it, redirects to the same page under `/ind`.

Next.js 16 (App Router) · TypeScript · Tailwind v4 · shadcn/ui (Base UI) ·
Supabase (Postgres + Auth).

## How data gets here

```text
GitHub Actions: daily-stock-screener.yml  (16:30 IST, 18:30 IST recovery)
        │
        ├─ python app.py                    → advanced_analysis_YYYYMMDD.csv
        ├─ upload report artifact
        ├─ save market-data cache
        └─ python -m workers.dashboard_publisher --csv <that CSV>
                    │
                    ▼
        Supabase: screener_runs
                  screener_snapshot   (latest runs, full row in `payload`)
                  screener_history    (slim, retained indefinitely)
                    │
                    ▼
        This app (Vercel), reading as the signed-in user under RLS
```

The publish step is the **last** step in the workflow. If Supabase is
unreachable, the report artifact and the warm cache are already saved, and the
dashboard keeps serving the previous run behind its staleness banner.

## Storage model

The screener emits a wide, evolving CSV — v4 is ~370 columns and grows whenever
an evidence stage adds audit fields. Mirroring each column as a typed Postgres
column would break the schema on every model revision, so each row is split:

- **typed columns** for the ~80 fields the grid sorts, filters, and indexes on
- **`payload` jsonb** for the complete row, powering drill-down

A new audit column therefore appears in drill-down with no migration. Only a new
*filterable* field needs one.

Full snapshots are pruned to the latest run per market (`prune_screener_snapshots`,
publisher default: keep 1 -- each is ~90 MB against the free plan's 500 MB). `screener_history` keeps 15 fields per stock per day forever
at roughly 0.4 MB/day, which is what makes the movers view work after snapshot
pruning. It is also the Returns page's record of every published ranking: that
page prices a past day's top N forward from it, from the first day this table
was written (2026-08-11 for NSE, 2026-09-18 for US). Before that date the page
reads `simulated_rankings`, weekly point-in-time backtest rankings from November
2018 written once by `tools/backfill_returns_history.py`, and labels every
figure built on them as backtest. Its "all ranked stocks" comparison is
`universe_index`, a daily equal-weight index the publisher appends to each run.
Both tables are in `storage/returns_backfill_schema.sql`.

## Notifications

The bell in the header's account capsule, and `/[market]/notifications`.

```text
GitHub Actions: financial-statements.yml  (03:00, 09:00, 15:00 UTC)
        └─ python -m workers.market_events --market NSE|US
                    │   results     NSE: the exchange's results-filing index
                    │               US:  the stored statements gaining a quarter
                    │   transcript  a call transcript stored in the last week
                    ▼
        Supabase: market_events        (shared; one row per event, written once)
                  notification_reads   (per viewer and market: when they last looked)
```

Unread is everything recorded after the viewer's `seen_at`; opening the bell or
the page moves it to now. Both are scoped to the viewer's watchlists when they
have any, with the whole market one filter away on the page: in a results
season the market files hundreds of results a day, and a badge that is always
full says nothing.

The bell's state is read in the market layout, so it costs three small reads
per market visit, not per page. Every read degrades to "nothing" if the tables
are missing, so this code can deploy before `storage/notifications_schema.sql`
is applied; the bell is simply empty until it is.

Wording, the unread rule and day grouping live in `lib/notifications.mjs`
(tested in `lib/notifications.test.mjs`). A kind that file does not know still
renders, by its name.

## Search and indices

The header's magnifier (and the screener toolbar's field, and ⌘K) opens one
dialog over the market's stocks and indices (`components/global-search.tsx`,
the shared `StockPicker`). The indices arrive in the same cached
`/api/search-index` answer as the stocks, so the dialog costs one request a
tab. A page with a picker of its own -- the watchlist's "Add stocks" -- keeps
⌘K; the header's button still searches there.

Each index has a page, `/[market]/indices/[slug]` (the slug is the label,
`lib/indices.mjs`), with its level chart where `market_breadth` holds one and
its constituents from `index_members` in the screener's own table: the same
`getSnapshotPage`, columns, sorts and live Price and 1D. Constituents the run
does not rate are named under the table. `/[market]/indices` lists them all.
US indices have charts and no constituent lists yet.

Disclosures open with motion: every `<details>` through one delegated
listener (`SmoothDetails` in `components/motion.tsx`), and lists that grow --
the movers' expand bar, the results' margin rows -- through `useExpand`. Both
are GSAP, already in the bundle, and both do nothing under reduced motion.

## Live prices

The grid's Price and 1D cells, the stock page's tiles, and the Market page's
"Today's movers" by index, refreshed every five minutes during the session.

```text
cron-job.org, every 5 min on weekdays  ->  live-quotes.yml (workflow_dispatch)
        └─ python -m workers.live_quotes --market NSE
                    │   one Yahoo quote request per 500 symbols (~15 s a run)
                    │   index constituents re-read once a day
                    ▼
        Supabase: live_quotes     (one row per market and symbol, overwritten)
                  index_members   (constituents of each index on the Market page)
                  live_market()   (every index's movers as one JSON value)
```

Display only: sorting, filters, rank and rating stay on the last close. Pages
render exactly as before and read the quotes in the browser afterwards
(`lib/use-live-quotes.ts`, one store per tab, so a sort or a step back shows
the live figures with no new request). A quote replaces a row's close only
when it is from a later session than the row's bar, so after the evening
publish the close stands again. Each viewer polls once per worker run, aligned
to when the next one lands, and not at all while the tab is hidden; the rules
are in `lib/live-quotes.mjs` (tested in `lib/live-quotes.test.mjs`). Every read
degrades to the close if the tables are missing, and the Market page leaves the
section out.

## Access control

Invite-only, enforced at three layers:

1. `shouldCreateUser: false` on sign-in — Supabase will not provision an account
   for an unknown address.
2. `dashboard_allowlist` + `requireAccess()` in the app. A user invited from
   Supabase → Authentication → Users is added as a viewer when they accept
   (`storage/dashboard_invites_schema.sql`); anyone else is listed by hand.
3. **RLS policies** — the authoritative gate. Every browser read runs as the
   signed-in user; `anon` has no policy and reads nothing.

The service-role key never reaches the browser or this app's environment. It is
used only by the ingestion job, from GitHub Actions secrets.

The weekly audit signs in with a password instead of an email code
(`scripts/smoke-check.mjs`, read-only GETs; the account is a viewer on the
allowlist). Run it with `CREED_DASHBOARD_PASSWORD`, `NEXT_PUBLIC_SUPABASE_URL`
and `NEXT_PUBLIC_SUPABASE_ANON_KEY` set; it prints status, run date and any
empty section for every page of `/ind` and `/us`. `CREED_DASHBOARD_EMAIL`
(default `creed.audit@example.com`) and `DASHBOARD_URL` (default
`https://win-now.vercel.app`, or pass it as the first argument) override the
account and site. "Nothing measured in this range" and "No stocks on this list
today" print as `WARN` and do not fail the run.

`proxy.ts` (Next.js 16 renamed Middleware to Proxy) only refreshes the auth
token and does an optimistic redirect for sessionless requests. Per the Next.js
guidance it is *not* the authorization solution — `requireAccess()` and RLS are.

## Setup

### 1. Database

Run both files in the Supabase SQL Editor, in order:

```text
storage/supabase_schema.sql     # transcripts + red flags (may already be applied)
storage/dashboard_schema.sql    # this dashboard's tables, views, and RLS
storage/concalls_schema.sql     # the Concalls page's feed (after dashboard_schema.sql)
storage/live_quotes_schema.sql  # live prices and index movers (after dashboard_schema.sql)
storage/dashboard_invites_schema.sql  # invited users join the allowlist on accepting
```

Then invite yourself (the SQL Editor runs as owner, bypassing RLS):

```sql
insert into dashboard_allowlist (email, role)
values ('you@example.com', 'admin');
```

### 2. Auth

In Supabase → Authentication → URL Configuration, add the callback URLs:

```text
http://localhost:3000/auth/callback
https://<your-vercel-domain>/auth/callback
```

Supabase's built-in SMTP is rate-limited (a few messages per hour). That is
workable for a small invite list; configure a custom SMTP provider if you add
more people.

**Sign-in email.** Supabase sends it, so the template cannot be deployed from
this repo: `emails/magic-link.html` is the source of record. After editing it,
paste the whole file into Authentication → Email Templates → Magic Link and set
the subject to `Sign in to Winnow`. The template loads the brand mark from
`{{ .SiteURL }}/email/winnow-mark.png`, so the project's Site URL (URL
Configuration) must be the deployed dashboard's origin. The sender name is the
one configured under SMTP Settings.

**Session lifetime.** A sign-in lasts seven days from the moment the link was
used, however recently the dashboard was opened; after that `proxy.ts` revokes
the session and sends the next request to the login page. Set
`SESSION_MAX_AGE_HOURS` to change it. The rule is in `lib/session-policy.mjs`
and reads the signed `amr` claim, so it cannot be extended from the browser.
It is enforced by this app, not by Supabase: a refresh token copied out of a
browser stays exchangeable at the Supabase API until this app next sees that
session. Closing that gap is Supabase's own "Time-box user sessions" setting
(Authentication → Sessions), which needs a paid plan.

### 3. Load a run

```powershell
python -m workers.dashboard_publisher --csv reports_advanced\advanced_analysis_20260812.csv --dry-run
python -m workers.dashboard_publisher --csv reports_advanced\advanced_analysis_20260812.csv
```

`--dry-run` parses, maps, and reports coercion and column drift without
contacting Supabase. Always worth running first against an unfamiliar export.
Scheduled publishing also passes `--if-exists skip`, which treats an already
published trading date as a successful no-op. The CLI default remains `error`
so an operator cannot accidentally replace a completed snapshot.

### 4. Local development

```powershell
cd dashboard
copy .env.example .env.local   # then fill in Supabase and Brandfetch values
npm install
npm run dev
```

### 5. Deploy

Vercel, with **Root Directory** set to `dashboard`. Environment variables:

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://YOUR_PROJECT.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | project anon key |
| `NEXT_PUBLIC_SITE_URL` | deployed origin, no trailing slash |
| `NEXT_PUBLIC_BRANDFETCH_CLIENT_ID` | public client ID from the Brandfetch developer portal |

The Brandfetch client ID is intentionally browser-visible: Brandfetch requires
it in each Logo API image URL. Put the real value in Vercel and in the ignored
local `dashboard/.env.local`; commit only the placeholder in `.env.example`.
After changing a `NEXT_PUBLIC_` value in Vercel, redeploy because Next.js
inlines public environment variables at build time.

**Function region.** `vercel.json` pins the server functions to `hnd1`
(Tokyo) because the Supabase project is in `ap-northeast-1` (Tokyo). Every
page waits on one or two Supabase reads before it can answer, so the function
belongs next to the database: from another region each read crosses an ocean,
and a page pays that once per read rather than once per page. If the Supabase
project ever moves, move this with it -- the region is in the database host's
address (`db.<project>.supabase.co`).

Company logo domains come from Yahoo's issuer `website` metadata and are
published as `screener_snapshot.logo_domain`. Re-run
`storage/dashboard_schema.sql` before the first logo-enabled publish. Existing
fundamental caches intentionally refresh once to backfill this new field; a
missing domain or failed Logo API response falls back to a ticker initial.

The repository already holds `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` as
Actions secrets for the transcript and red-flag workers; the publish step reuses
them.

## Design notes

**Rating colours are a diverging ramp, not a categorical palette.** It runs
teal → slate → amber/orange → rose rather than the conventional green → red,
because red/green is the most common confusion pair and separating BUY from SELL
is this grid's entire job. Every badge also renders its text label, so hue is
never the sole carrier of meaning. All ten badge colour pairs were measured for
contrast; the lowest is 4.55:1 against its own tint, above the 4.5:1 floor.
`REDUCE` is orange-800 rather than amber-700 specifically because amber measured
4.25:1 and failed.

**Absent evidence is drawn as absent.** The model treats a missing transcript,
an unsupported DCF, or an uncovered red-flag symbol as *neutral* — not as bad
news. The evidence chips therefore distinguish three states, not two: applied,
present-but-ineligible, and absent. Collapsing the middle state would misreport
the model.

**Capped scores show both numbers.** When a policy ceiling holds a row below its
evidence score, the grid shows the decision score with the evidence score behind
it. Showing only the published number would hide the most important fact about
that row.
