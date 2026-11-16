# Supabase → Cloudflare D1: migration plan (phase 1)

_14 Nov 2026, Kevin. Status: plan only. Nothing has been written to Supabase, D1 or R2._

## Why

The Supabase free plan is over quota: database 534/500 MB on the usage page, egress
5.68/5 GB. The project is restricted from **14 Dec 2026**. Every data table moves to
Cloudflare D1, on the **Workers Free** plan. Login stays on Supabase Auth, and so does
everything the access-token hook reads.

## 1. What fills the database (read-only psql, 14 Nov 08:30 UTC)

`pg_database_size` = **495 MB**. The usage page shows 534 MB, probably counting
WAL and system files as well. Counters are cumulative since the statistics were last
reset (no reset date is recorded), so they rank writers rather than give daily rates. A
second sample tonight will turn them into rates. The first sample is kept in the session
scratchpad.

| table | MB | rows | inserts | updates | deletes | note |
|---|---:|---:|---:|---:|---:|---|
| screener_history | 92 | 303,160 | 107,280 | 0 | 0 | grows by every row of every published run, about 2.6 MB a day |
| shareholding_patterns | 57 | 39,398 | 3,626 | 1 | 0 | 1.27 bn index tuples fetched: heavy reader |
| bulk_block_deals | 52 | 102,142 | 1,649 | **3,067,394** | 0 | the whole history is re-upserted every run |
| storage.objects | 42 | 23,293 | 250,234 | 194,025 | 145,838 | Storage metadata; it counts toward the DB |
| red_flag_snapshot_history | 37 | 26,445 | 26,445 | 0 | 0 | **never read** (0 scans) |
| quarterly_filings | 33 | 50,129 | 25,757 | 28,104 | 0 | 1.46 bn index tuples fetched |
| screener_snapshot | 32 | 8,653 | 111,997 | 0 | 111,748 | a delete and an insert per run |
| financial_statements | 24 | 9,062 | 2,890 | 99,709 | 0 | |
| concall_feed | 15 | 3,193 | 888 | **777,560** | 36 | every row rewritten each run |
| transcript_sentiments | 14 | 3,958 | 1,473 | 0 | 576 | |
| simulated_rankings | 12 | **0** | 0 | 0 | 0 | empty table, 12 MB of dead space |
| company_documents | 10 | 23,431 | 25,416 | 0 | 1,868 | |
| transcript_outlooks | 8 | 3,433 | 1,720 | 2,473 | 669 | |
| simulated_states | 6 | **0** | 0 | 0 | 0 | empty, 6 MB dead |
| red_flag_snapshots, estimate_history, market_breadth | 5 each | | | | | |
| live_quotes | 2 | 8,290 | 2,658 | **8,283,168** | 154 | every symbol every 5 min |
| valuation_basis | 2 | 8,543 | 2,791 | **1,190,378** | 0 | every symbol every publish |
| market_breadth_members / _levels | 2 / 1 | 16,210 / 5,711 | | 167,800 / 83,138 | | |
| everything else | < 1 each | | | | | auth, billing, watchlists: tiny |

Storage bucket `market-data`: 23,293 objects, 181 MB. This counts against Storage
quota, not the 500 MB database limit; its metadata rows are the 42 MB above.

**Egress.** Supabase does not tell us per table how egress splits. The likely sources
are, in order:
1. Storage downloads: price series and snapshot payloads. Since #328 (13 Nov) the
   dashboard reads these from R2 first. The Python writers in `dual` mode still read from Supabase.
2. REST reads of wide JSON rows: quarterly_filings `lines` and shareholding patterns.
3. The every-5-minutes live-quote reads.

**Ask the human for the Supabase usage page's database/storage egress split** to confirm the order.

## 2. D1 Free limits (Cloudflare docs, read 14 Nov 2026)

| limit | Free |
|---|---|
| database size | **500 MB each** |
| databases | **10** |
| storage per account | 5 GB |
| rows written | **100,000 a day**, account-wide, reset 00:00 UTC; each index on a written column adds a row |
| rows read | **5,000,000 a day**; a scan counts every row it reads, not the rows it returns |
| queries per Worker invocation | 50; one `batch()` counts as one |
| bound parameters per query | 100 |
| SQL statement length | 100 KB |
| row or string size | 2 MB |
| REST API | the global Cloudflare API limit (1,200 requests per 5 minutes); "best suited for administrative use" |
| egress | free |

The Worker itself is on the Free plan too. It has 10 ms of CPU per request, and cupel.in
already fails with `exceededCpu` under a burst (memory note of 14 Nov). Every read
design below keeps CPU in D1 and out of the Worker.

### What breaks the limits as things are today

| writer | rows written a day today (estimated from schedule × rows) | verdict | fix |
|---|---:|---|---|
| live_quotes (5 min × ~75 runs × ~8,300 symbols) | ~600,000 | **breaks** (6× the whole budget) | **R2 object** `live/{MARKET}/quotes.json` written each run (~150 Class A writes a day). The Worker reads it through the existing `MARKET_DATA` binding |
| screener_snapshot (delete + insert per run) + indexes | ~45,000 | tight | keep one row per (market, symbol) and **upsert in place**; at most 2 indexes |
| screener_history (+ index) | ~17,000 | fits; size grows 2.6 MB a day | **its own D1 database**, slimmed to the columns the pages read; runs older than 12 months archived to R2 as one gz per run |
| valuation_basis (all symbols every publish) | ~8,500+ | waste | write **only changed rows** (compare with the stored basis) |
| bulk_block_deals (whole history re-upserted) | tens of thousands | waste | `ignore-duplicates`: new deals only |
| concall_feed (every row every run) | ~3,000 × runs | waste | write changed rows only |
| market_breadth_members / levels, index_members | ~20,000 | tight | **R2 objects** per market; they are read whole anyway |
| quarterly_filings, financial_statements, events, documents, transcripts | hundreds a day; thousands in results season | fits | unchanged |
| a `PARSER_VERSION` bump (re-reads 50k filings) | 50,000 at once | **breaks** for a day | the worker caps rows per run (an env setting) and resumes; do pending bumps (v5) on Supabase before cutover |
| the one-off backfill (~600k rows) | — | ~8 days at 75k a day | after the pruning in section 5; history goes in last, newest first |

Target after the fixes: **≤ 60,000 rows a day** in normal operation, leaving room for results season.

**Reads (5M a day).** The pages that would scan:
- **The grid (`getSnapshotPage`).** A filter plus a sort over 8,600 rows is a full scan
  per query if the sort column has no index: about 580 page views a day uses the whole
  budget. Fix: an index on the default sort and on (market, sector). The page result
  is cached in the Next cache (the existing `NEXT_INC_CACHE_R2_BUCKET`), keyed by run id,
  so a run is queried once per filter and page, not once per view.
- **`quarterly_result_feed`** is a GROUP BY over 50k filings on every view. Fix: a
  real table `result_feed`, written by `workers/quarterly_filings.py` when it stores a
  filing (one row per symbol and quarter).
- **"Your score" / movers** read a whole run (8,600 or 17,000 rows). Fix: the
  publisher writes the movers and the per-run summary as an R2 object once per run.
- **`live_valuation`, `live_market`, `live_breadth`** join quotes to the stored basis. They
  become Worker code over the R2 quotes object plus D1 rows for the page's own symbols only.

## 3. Write route

**The D1 REST API, called from Python.** A Worker endpoint is not chosen: on the
Free plan it would spend its 10 ms of CPU parsing large write bodies and use up the
100k Worker requests a day the site needs.
- Endpoint: `POST /client/v4/accounts/{acct}/d1/database/{id}/query`. The token has
  only `D1:Edit` on the three databases. It is a repository secret
  (`D1_API_TOKEN`) with `D1_ACCOUNT_ID` and one id per database.
- A bulk upsert is **one statement with one parameter**: `INSERT ... SELECT
  json_extract(value,'$.col') ... FROM json_each(?1) ON CONFLICT (...) DO UPDATE ...`.
  The parameter is a JSON array of up to ~1,000 rows (under the 2 MB string limit). That
  stays inside the 100-parameter and 100 KB statement limits, and a full NSE publish
  needs about 10 requests. Each response reports `meta.rows_written`, which the
  backend logs per writer and adds to a daily total. **A write that would take the day
  past a set ceiling (default 90k) fails loudly instead of being cut off part-way.**
- **The seam.** Both repositories already funnel every call through one method,
  `_request(method, path, **kwargs)`, in `storage/dashboard_repository.py` and
  `storage/supabase_repository.py`. The PostgREST features they use are a small set:
  `select`, `eq/in/gte/gt/lt/is/like/neq/not.is`, `order`, `limit`, `offset`,
  `on_conflict` with merge or ignore duplicates, delete, and 2 RPCs. A new
  `storage/d1_backend.py` turns that set into SQL. `TABLE_BACKEND`, read like
  `OBJECT_STORE_BACKEND`, picks the backend:
  - `supabase` (also unset or `""`): the backend as today.
  - `dual`: write Supabase, then D1; read Supabase; log any D1 error without failing the run.
  - `d1`: D1 only.

  No repository method changes, and the workflows switch by variable. The two RPCs
  (`pending_transcripts_for_analysis`, `prune_screener_snapshots`) become SQL
  in the backend. Tests run the translator against SQLite in memory, as
  `tests/test_valuation_basis.py` already does for the view.
- Schema: `storage/d1/*.sql`, one file per database. `jsonb` becomes TEXT holding JSON
  (read with `json_extract`), `timestamptz` becomes ISO text, and `bool` becomes 0/1.

## 4. Views, RPCs and access rules to replace

| Supabase object | replacement |
|---|---|
| `screener_snapshot_visible`, `screener_history_visible`, `screener_runs_visible` (they null rating fields for non-admins) | **Do not copy the views.** D1 is reachable only from the Worker (server), never from the browser. One function in the dashboard's D1 read module chooses the select list from the viewer: rating fields, and Rank and score per `feat/hide-rank-nonadmin`, are selected only when `isAdmin()`. The rule stays in `dashboard/lib/ratings.mjs` with its test. A non-admin query never fetches the columns, so nothing can leak to the client (the SEBI rule). |
| RLS on every public table | Not needed for market data (server-only binding). User-owned tables stay on Supabase with their RLS. |
| `live_valuation` | Worker: the quote from the R2 object, the basis from D1 for the page's symbols, arithmetic in one shared function (held equal to `price_ratios` by the existing test, ported) |
| `quarterly_result_feed` | table `result_feed`, written by the filings worker |
| `live_market`, `live_breadth` (RPC) | Worker over the R2 quotes and levels objects |
| `screener_movers`, `breadth_snapshot` | written by the publisher (R2 object or a small D1 table) |
| `latest_transcript_sentiment`, `transcript_sentiment_history` | plain SQL (window function) in the backend's query |
| `pending_transcripts_for_analysis`, `prune_screener_snapshots` | SQL in `d1_backend.py` |
| notifications (`market_events` in D1, `notification_reads` on Supabase) | the bell counts D1 events after the viewer's `seen_at`, read from Supabase; two queries, joined in the Worker |

**Stays on Supabase** (all tiny, user-owned or read by the token hook): `auth.*`,
`plans`, `subscriptions`, `dashboard_allowlist`, `trial_signals`, `app_settings`,
`admin_actions`, `customer_emails`, `watchlists`, `watchlist_items`,
`notification_reads`, `billing_*` and `custom_access_token_hook`. Together they are
under 1 MB with negligible egress. Moving them off would mean rebuilding the token hook
and RLS, which is not worth it.

## 5. Stopgap to stay under 500 MB until cutover (proposal only; each needs the human's yes)

| step | frees | deletes data? |
|---|---:|---|
| `VACUUM FULL` simulated_rankings, simulated_states (0 live rows) | ~18 MB | no |
| `VACUUM FULL` bulk_block_deals after the ignore-duplicates fix | ~10-25 MB | no |
| archive `red_flag_snapshot_history` to R2 (one gz), then drop it | 37 MB | yes; never read |
| storage objects R2-only (`OBJECT_STORE_BACKEND=r2` once WNN-122's copy is verified), then empty the bucket | 42 MB of DB plus most storage egress | yes, after the copy is checked |
| prune `screener_history` older than N months (archived to R2 first) | ~7.5 MB a month pruned | yes |

The first two need no decision about data and buy about a month of growth.

**Done 14 Nov 2026 (the human's yes):** red_flag_snapshot_history archived to
`market-data/archive/supabase/red_flag_snapshot_history_2026-11-14.csv.gz` (26,445 rows,
sha256 `80c1cb59...`, checked by reading it back) and dropped. VACUUM FULL of bulk_block_deals
(52 to 22 MB) and simulated_rankings / simulated_states (18 to 11 MB). Database **494 to 419 MB**.
The human said **keep all screener_history**; how it fits D1's 500 MB is with god (slim columns
in D1 plus a full archive per run in R2, or one history database per year).

## 6. Table by table

| table | target | write route | read route | budget (rows written a day) | order |
|---|---|---|---|---:|---|
| live_quotes | R2 `live/{MARKET}/quotes.json` | object store (r2) | Worker via MARKET_DATA | 0 | 1 |
| market_calendar | R2 `live/{MARKET}/calendar.json` (1 row per market, read on every page) | live quotes worker | Worker, 5 min shared cache | 0 | 1 |
| market_breadth_members, _levels, index_members | R2 `live/{MARKET}/breadth-members.json`, `breadth-levels.json`, `index-members.json` | the table's writer, beside the table | Worker | 0 | 1 |
| search index (new) | R2 `search-index/{MARKET}/{run_date}.json`: symbol, company, logo_domain, sector, largest first, no rating | dashboard publisher | Worker, per run | 0 | 1 |
| bulk_block_deals | D1 `cupel-evidence` | REST, new deals only | Worker | < 500 | 2 |
| concall_feed | D1 `cupel-core` | REST, changed rows | Worker | < 500 | 2 |
| valuation_basis | D1 `cupel-core` | REST, changed rows | Worker | < 2,000 | 2 |
| quarterly_filings + result_feed | D1 `cupel-core` | REST | Worker | < 3,000 (season) | 3 |
| financial_statements, upcoming_events, market_events, new_listings, universe_index, market_breadth | D1 `cupel-core` | REST | Worker | < 3,000 | 3 |
| shareholding_patterns, company_documents, transcripts*, estimate_history, red_flag_snapshots | D1 `cupel-evidence` | REST | Worker | < 3,000 | 3 |
| screener_snapshot, screener_runs | D1 `cupel-core` | REST, upsert in place | Worker, select list by viewer | ~20,000 | 4 |
| screener_history | D1 `cupel-history`: the 12 columns the pages read (observed_on, symbol, company, current_price, volume, stage, investment_rank, rating, decision_score, final_score, fundamental_score, technical_score); every full run kept whole in R2 `archive/screener-history/{MARKET}/{run_date}.json.gz`, checked by reading it back (human, 14 Nov: option a) | REST | Worker | ~17,000 | 5 |
| red_flag_snapshot_history, simulated_* | dropped / R2 archive | — | — | 0 | stopgap |
| auth, billing, watchlists, notification_reads | stay on Supabase | as today | as today | — | — |

Size check: `cupel-core` ≈ 120 MB, `cupel-evidence` ≈ 155 MB, `cupel-history` ≈ 95 MB,
plus about 1 MB a day slimmed. That is three of the ten databases, each well under 500 MB.

## 7. Phases (on `feat/d1-migration`; Angela reviews each with ponytail:ponytail-review)

1. **This plan.** Then god's yes and the human's yes on section 5.
2. **Write amplification fixed on Supabase** (deals, concall_feed, valuation_basis):
   smaller writes and less egress straight away, and the same code is needed for D1.
3. **Live quotes and breadth members/levels to R2** (writer: Kevin; Worker reads: Pam).
4. **`storage/d1_backend.py` + `TABLE_BACKEND` + `storage/d1/*.sql`**, tested on
   SQLite. The human creates the three databases and the token (no spend: Free plan).
5. **`dual` writes, table group by table group**, in section 6's order. Compare row counts
   Supabase vs D1 daily; the backfill runs after the stopgap, ≤ 75k rows a day.
6. **Dashboard reads switch per table** (Pam, behind a flag), server-side select-list rule first.
7. **Cutover to `d1`**, then a week of Supabase read-only, then prune its data tables.

## Live objects (phase 3, written beside the tables)

Each object is plain JSON `{"market", "written_at", "rows": [...]}`, rows shaped as the
table's rows, written by the same method that replaces the table, to R2 only, when the
run has the R2 secrets. An R2 failure is logged and never fails the table write.
`quotes.json` is merged with the previous object by symbol and drops a quote no run
refreshed in 7 days, as `prune_live_quotes` does for the table.

**Access rule for the reader (Angela, review of #342).** These objects bypass Postgres
row-level security: the tables behind them are readable only under `dashboard_has_access()`,
an R2 object has no such rule. So: the Worker route that reads `live/*` or `search-index/*`
checks the viewer's access before returning anything; the bucket has no public access and no
r2.dev URL; `archive/*` holds full history rows, ratings and ranks included, and has no route
at all. The reader PR is reviewed against this.

## D1 databases

Created 14 Nov 2026 on the Workers Free plan, account `32fab729dc9211a0da0708de846a23af`,
location hint APAC:

| database | id |
|---|---|
| cupel-core | `48893af3-d137-4320-bea3-450ae9908d7f` |
| cupel-evidence | `40bd952e-00dd-4377-87c5-f336c1032ef2` |
| cupel-history | `4ba446d5-d2c0-4c0d-b0a8-603cb6a0351e` |

`CLOUDFLARE_API_TOKEN` (the user token, with D1 Edit added 14 Nov) reaches them.

## Open

- The egress split (human, Supabase usage page).
- D1 query latency from Mumbai for the grid's first uncached load: to measure in phase 4.
- A browser reader to move: the Your score preview (`dashboard/lib/use-score-preview.ts`) reads `screener_snapshot_visible` (about 6.5k rows, 7 pages) and `concall_feed` straight from Supabase each time a viewer opens the builder. With `TABLE_BACKEND` naming those tables it still reads Supabase, so it saves no egress until it moves to an `/api` route on the same cache.

## Backfill (tools/d1_tables.py, workflow "D1 backfill")

- Schema generated from Supabase's own table description into `storage/d1/{core,evidence,history}.sql`,
  one `WITHOUT ROWID` table per Supabase table, keyed in Postgres's key order (`KEY_ORDER`, from
  `pg_index`; a drifted key is refused). `screener_history` carries the 12 read columns plus `market`,
  keyed (market, observed_on, symbol) with one index (market, symbol, observed_on) for one stock's days.
- **D1 allows 100 columns a table.** `screener_snapshot` (156) is laid out by hand
  (`storage/d1/screener_snapshot.sql`, Dwight): 91 real columns, the rest in one `extra` JSON column,
  `payload` not carried. The backfill packs `extra`; the dual writer must do the same.
- Progress is a row in cupel-core (`d1_backfill_state`), so the dispatch-only workflow resumes on a fresh
  runner. The day's budget is `D1_BACKFILL_ROWS_PER_DAY` (default 75,000); at it the run stops, warns and
  stays green. **D1's 100k a day is per account**: lower the variable by the dual writes' share as
  tables are mirrored (plan section 6: about 45k a day once all are).
- A table that finishes is counted against Supabase; D1 short means a row moved behind the paging offset,
  so the table is read again (at most 3 passes; unchanged rows write nothing). **Verify every table's
  counts before cutover.**
- Day 1 (14 Nov): concall_feed 3,193/3,193, valuation_basis 8,543/8,543, bulk_block_deals 63,500 of
  102,142; 75,236 rows written. Re-sending 50 unchanged rows wrote 0 in D1 (meta.rows_written); one
  earlier re-send of 500 wrote 469, cause not found (the rows compared equal afterwards).
- Length: about 11 daily runs at 75k. Left after day 1 ~530k rows, plus screener_history's index
  (one more row written per row: 303,160 rows -> ~606k writes, ~8 days alone; copied last). The index
  stays: without it one stock's history scans all 303k rows, and 5M rows read a day would cover only
  ~16 uncached stock pages.
- Copied rows go stale until that table is mirrored (`dual`), which needs a per-table list first.
- For `dual`, a writer's `on_conflict` columns must be the D1 primary key (no unique indexes are copied).
  True for the phase-2 tables; `market_events` and the transcript tables upsert on a natural key behind
  an id key and need a unique index first.

**Access rule for every D1 reader (Angela, review of #344).** D1 has no row-level security and no
`*_visible` views. The Worker must strip ratings for non-admins (`withoutRatings`) and the verdict fields
for everyone (`withoutVerdict`), as `lib/queries.ts` `forViewer` does, after merging `extra` into the
row; and the tables that sit behind `dashboard_has_access()` today (concall_feed, quarterly_filings,
market_breadth, ...) need the same access check in the Worker. The reader PR is reviewed against this.

## Phase 2: every job off Supabase before 14 Dec (human, 16 Nov 2026)

Supabase keeps login and what the token hook reads; every other table moves to D1 (or is
already an R2 object). Counts read 16 Nov ~17:00 UTC (Supabase `reltuples`, D1 `count(*)`).

### What stays on Supabase (god decides)

| table | why it must stay |
|---|---|
| `auth.*` | login |
| `plans`, `subscriptions`, `dashboard_allowlist` | `custom_access_token_hook` reads them to put `plan` and `access_until` in the token |
| `app_settings` | `trial_days()` and the signup trigger `billing_start_trial` read `trial_days` from it |
| `trial_signals` | written by the signup trial guard, in the same transaction as the trial row |
| `admin_actions`, `customer_emails` | written by `billing_refund_end_access` / `billing_apply_event` (SQL functions) and the webhook beside a subscription change; must commit with it |

All are under 1 MB with negligible egress. **Moved, though user-owned:** `watchlists`, `watchlist_items`,
`notification_reads`, `saved_views` (its 50-view cap trigger becomes a check in the Worker route).
Caveat for Pam (WNN-134): the browser reads these today through RLS; on D1 every read and write is a
Worker request, which costs Worker CPU on the Free plan (section "Boundaries" of CLAUDE.md).

### One switch per table, four steps

`TABLE_BACKEND` today is one value for a whole run. **PR D1-1** makes it per table, in the backend
(`storage/d1_backend.py`), without changing a repository method:

| mode | writes | reads |
|---|---|---|
| `supabase` | Supabase | Supabase |
| `dual` | Supabase, then D1 (a D1 error is logged) | Supabase |
| `dual_d1` | Supabase, then D1 | **D1** (the jobs' egress stops here) |
| `d1` | D1 | D1 |

Set as `TABLE_BACKEND_DUAL`, `TABLE_BACKEND_DUAL_D1`, `TABLE_BACKEND_D1` (comma lists of tables; a table
in none is `supabase`), one repository variable each so every workflow follows one setting. Same PR: the
unique indexes `dual` needs where a writer upserts on a natural key behind an id (`market_events`,
`transcripts`, `transcript_documents`, `transcript_sentiments`, `transcript_outlooks`), and D1 tables
for the four user tables and `transcript_filings`, `transcript_filing_documents`.

Per table: **dual** (and backfill) → counts equal Supabase on two days running → **dual_d1** (jobs read
D1) → dashboard reads D1 (Pam) → **d1** → Supabase table frozen → dropped only after D1 reads are
verified, god's go and the human's yes.

### Write budget (100k rows a day, account-wide)

Steady-state dual writes, estimated from each writer's rows a run × runs a day, plus one row per index:

| group | tables | rows written a day |
|---|---|---:|
| A filings set | quarterly_filings, shareholding_patterns, valuation_basis, financial_statements, market_events, upcoming_events, company_documents, new_listings, universe_index | ~10,000 (season), ~3,000 otherwise |
| B publish set | screener_snapshot (+2 indexes), screener_runs, market_breadth, concall_feed, bulk_block_deals, transcripts ×4, estimate_history, red_flag_snapshots | ~25,000 |
| C history | screener_history (+1 index), ~8,600 rows a publish day × 2 | ~17,000 |
| D user tables | watchlists, items, reads, saved views | < 100 |

~52,000 a day once everything is dual, so the backfill runs at `D1_BACKFILL_ROWS_PER_DAY` = 75,000 until
group B is dual, then 40,000. `meta.rows_written` is logged per writer; a writer that runs over its
estimate by 2× is the first thing to fix.

### Backfill left (rows to copy, 16 Nov)

| table | Supabase | D1 | left |
|---|---:|---:|---:|
| concall_feed, valuation_basis, bulk_block_deals | 3,225 / 8,543 / 102,142 | done | 0 |
| quarterly_filings | 46,841 | 36,500 | 10,341 |
| shareholding_patterns | 39,396 | 0 | 39,396 |
| financial_statements, market_events, upcoming_events, company_documents, new_listings, universe_index | 9,062 / 12,163 / 4,570 / 24,076 / 93 / 1,949 | 0 | 51,913 |
| screener_snapshot, screener_runs, market_breadth | 8,653 / 2 / 245 | 0 | 8,900 |
| transcripts ×4 + filings ×2, estimate_history, red_flag_snapshots | 14,376 + 8,355 / 32,792 / 2,340 | 0 | 57,863 |
| **subtotal before history** | | | **~168,000** (3 days at 75k, with the index rows) |
| screener_history (+ its index) | 289,412 | 0 | ~580,000 writes (~11 days at ~50k) |

History rows never change once written, so its dual starts on 23 Nov and the backfill copies the days
before it, newest first.

### Sequence (target dates; each PR: Angela reviews, god merges)

| when | step | egress removed (raw, WNN-133 measures) |
|---|---|---|
| 17 Nov | **PR D1-1**: per-table modes, unique indexes, D1 tables for the user and transcript-filing tables. Tests on SQLite | — |
| 17-19 Nov | backfill group A (≈113k rows incl. index rows), then B | — |
| 18 Nov | **group A `dual`** (filings, shareholding, basis, statements, events, documents) | — |
| 20 Nov | counts equal two days → **group A `dual_d1`**. Biggest job egress: the filings/shareholding/basis readers | ~1.4 GB/d raw before #360/#361; what remains of it |
| 20 Nov | **group B `dual`** (screener publish: snapshot, runs, breadth, concall, deals, transcripts, estimates, red flags) | — |
| 23 Nov | **group B `dual_d1`**; **group C `dual`** (history), history backfill 23 Nov - 3 Dec | publisher reads (~100 MB/d raw) |
| by 25 Nov | dashboard reads group A from D1 (Pam, WNN-134) → group A **`d1`** | browser reads of A |
| by 1 Dec | dashboard reads group B (Pam) → group B **`d1`**; live_quotes, index_members, market_calendar, breadth members/levels: tables stop being written once the dashboard reads the R2 objects | browser reads of B, live reads |
| 4 Dec | history backfill verified → group C **`dual_d1`**, dashboard reads history (Pam) → **`d1`** | — |
| 7 Dec | group D (user tables) dual → d1 with Pam's Worker routes | — |
| 8-13 Dec | a week with every job on `d1`, Supabase data tables read-only and frozen | all job egress |
| after 14 Dec | god's go + human's yes per table → drop from Supabase (archive to R2 first) | size back under 50 MB |

**Off the table:** `simulated_rankings`, `simulated_states` (no live rows): archive to R2 and drop with the
human's yes; not copied. A `PARSER_VERSION` bump between 18 Nov and cutover is written twice (dual) and
must be capped per run (an env setting) so it cannot take the day past 100k.

**Risks.** (1) D1 rows read (5M a day): the jobs' whole-table reads were cut by #360/#361; any other
whole-table read of a moved table counts every row each run. (2) A dual write that fails on D1 is logged,
not retried: the daily count check catches drift before `dual_d1`. (3) Worker CPU on the Free plan for
reads Pam moves server-side (WNN-134).
