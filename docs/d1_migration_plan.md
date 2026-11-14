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

## 6. Table by table

| table | target | write route | read route | budget (rows written a day) | order |
|---|---|---|---|---:|---|
| live_quotes | R2 `live/{MARKET}/quotes.json` | object store (r2) | Worker via MARKET_DATA | 0 | 1 |
| market_breadth_members, _levels, index_members | R2 objects per market | object store | Worker | 0 | 1 |
| bulk_block_deals | D1 `cupel-evidence` | REST, new deals only | Worker | < 500 | 2 |
| concall_feed | D1 `cupel-core` | REST, changed rows | Worker | < 500 | 2 |
| valuation_basis | D1 `cupel-core` | REST, changed rows | Worker | < 2,000 | 2 |
| quarterly_filings + result_feed | D1 `cupel-core` | REST | Worker | < 3,000 (season) | 3 |
| financial_statements, upcoming_events, market_events, new_listings, universe_index, market_breadth | D1 `cupel-core` | REST | Worker | < 3,000 | 3 |
| shareholding_patterns, company_documents, transcripts*, estimate_history, red_flag_snapshots | D1 `cupel-evidence` | REST | Worker | < 3,000 | 3 |
| screener_snapshot, screener_runs | D1 `cupel-core` | REST, upsert in place | Worker, select list by viewer | ~20,000 | 4 |
| screener_history | D1 `cupel-history` | REST | Worker | ~17,000 | 5 |
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

## Open

- The egress split (human, Supabase usage page).
- Which `screener_history` columns the pages read, so it can be slimmed (Pam).
- D1 query latency from Mumbai for the grid's first uncached load: to measure in phase 4.
