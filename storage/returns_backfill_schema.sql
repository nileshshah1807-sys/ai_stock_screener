-- =====================================================================
-- Returns page: backtest rankings before the live record, and a daily
-- equal-weight universe index
-- =====================================================================
--
-- `screener_history` holds only rankings the dashboard actually published,
-- which begin on 2026-08-11 (NSE) and 2026-09-18 (US). The Returns page can
-- reach further back only by using rankings the point-in-time backtest
-- reconstructs, and those must never be confused with published ones:
--
-- * simulated_rankings -- one row per stock in a backtest ranking's top N,
--   written once by tools/backfill_returns_history.py and never by the daily
--   pipeline. The weights that produced them (Model 5.1) were fitted on this
--   same period, so every figure built from them is in-sample and the page
--   labels it as backtest. Symbols are each security's *current* ticker, so
--   they join to price_series across renames.
--
-- * universe_index -- the equal-weight daily return of every ranked stock,
--   one row per session. It is the page's "all ranked stocks" comparison for
--   any window, backfilled from the archive and then appended by the daily
--   publisher from each run's own one-day returns.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/returns_backfill_schema.sql
--   (or paste into the Supabase SQL editor). Safe to re-run.

create table if not exists simulated_rankings (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    observed_on date not null,
    symbol text not null,
    investment_rank integer not null,
    research_score numeric(6,2),
    stage text,
    model_version text not null,
    primary key (market, observed_on, symbol)
);

create index if not exists simulated_rankings_rank_idx
    on simulated_rankings (market, observed_on, investment_rank);

create table if not exists universe_index (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    observed_on date not null,
    -- Mean one-session return, in percent, of the stocks ranked that day.
    ew_return_pct numeric(10,4) not null,
    members integer not null,
    -- 'archive' (backtest price panel), 'history' (backfilled from published
    -- prices) or 'publisher' (appended by the daily run).
    source text not null,
    primary key (market, observed_on)
);

alter table simulated_rankings enable row level security;
alter table universe_index enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
drop policy if exists simulated_rankings_read on simulated_rankings;
create policy simulated_rankings_read
    on simulated_rankings for select
    using (dashboard_has_access());

drop policy if exists universe_index_read on universe_index;
create policy universe_index_read
    on universe_index for select
    using (dashboard_has_access());
