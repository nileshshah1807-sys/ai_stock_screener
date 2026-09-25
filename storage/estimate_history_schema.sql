-- =====================================================================
-- Analyst-estimate observations, kept as a revision history
-- =====================================================================
--
-- The model scores only backward-looking evidence. Earnings-estimate
-- revisions are among the best-documented forward signals, but there is no
-- free point-in-time history of them: a vendor serves today's consensus and
-- silently overwrites yesterday's. The only way to have that history later is
-- to record each observation now. This table does that and nothing else --
-- no score, rating or rank reads it, and `docs/model_methodology.md` keeps
-- consensus out of the score until the recorded history is long enough to
-- test.
--
-- One row per symbol per vendor fetch. Fundamentals are cached for seven days,
-- so the same fetch reaches several daily runs; keying on `fetched_at` records
-- each real observation once, and the publisher's ignore-duplicates upsert
-- keeps the first `observed_on` a fetch was published under. A revision is a
-- change between two consecutive rows of the same symbol.
--
-- `fetched_at` is when this pipeline read the vendor, not when the vendor
-- updated its consensus: a revision can be up to one cache period late.
--
-- Written by workers/dashboard_publisher.py. Until this file is applied the
-- publisher logs a warning and publishes the run without estimates.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/estimate_history_schema.sql
-- Safe to re-run.

create table if not exists estimate_history (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    fetched_at timestamptz not null,
    -- The run date this observation was first published under.
    observed_on date not null,

    forward_eps numeric,
    forward_pe numeric,
    trailing_eps numeric,
    analyst_count integer,
    target_mean_price numeric,
    -- Vendor scale: 1 = strong buy ... 5 = sell.
    recommendation_mean numeric,
    -- The completed close the run priced on, so an estimate can be read
    -- against the price it was observed beside.
    price numeric,

    updated_at timestamptz not null default now(),

    primary key (market, symbol, fetched_at)
);

create index if not exists estimate_history_observed_idx
    on estimate_history (market, observed_on desc);

alter table estimate_history enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
drop policy if exists estimate_history_read on estimate_history;
create policy estimate_history_read
    on estimate_history for select
    using (dashboard_has_access());
