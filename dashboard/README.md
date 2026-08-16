# Screener Dashboard

Private web dashboard for the daily NSE screener. Replaces the emailed
spreadsheet and the static `dashboard_*.html` report with a searchable,
filterable view of the full scored universe.

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

Full snapshots are pruned to the most recent runs (`prune_screener_snapshots`,
default: keep 2). `screener_history` keeps 15 fields per stock per day forever
at roughly 0.4 MB/day, which is what makes the movers view work after snapshot
pruning.

## Access control

Invite-only, enforced at three layers:

1. `shouldCreateUser: false` on sign-in — Supabase will not provision an account
   for an unknown address.
2. `dashboard_allowlist` + `requireAccess()` in the app.
3. **RLS policies** — the authoritative gate. Every browser read runs as the
   signed-in user; `anon` has no policy and reads nothing.

The service-role key never reaches the browser or this app's environment. It is
used only by the ingestion job, from GitHub Actions secrets.

`proxy.ts` (Next.js 16 renamed Middleware to Proxy) only refreshes the auth
token and does an optimistic redirect for sessionless requests. Per the Next.js
guidance it is *not* the authorization solution — `requireAccess()` and RLS are.

## Setup

### 1. Database

Run both files in the Supabase SQL Editor, in order:

```text
storage/supabase_schema.sql     # transcripts + red flags (may already be applied)
storage/dashboard_schema.sql    # this dashboard's tables, views, and RLS
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
