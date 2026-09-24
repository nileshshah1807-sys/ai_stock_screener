-- =====================================================================
-- Market breadth for the Market page
-- =====================================================================
--
-- One row per (market, scope, name): the whole market, each sector, each
-- industry with at least five members, and each headline index. A row holds
-- its full daily history as delta-encoded integer arrays -- the same shape as
-- price_series, for the same reason: the page reads a whole series and never
-- filters inside it, and ~2,100 sessions x ~120 groups as one row per day
-- would be a quarter-million rows to answer "draw this group's chart".
--
-- `series` is compact JSON: {metric: [delta-encoded ints]}. Breadth metrics are
-- counts with their own denominators ("e50" stocks above EMA 50 of "e50d" with
-- a full 50-day window), so the page can show either the count or the share.
-- Index rows carry one metric, "c", the level in hundredths.
--
-- Written by tools/publish_market_breadth.py; see workers/market_breadth.py
-- for every definition. The row set is replaced on each publish, so a sector
-- that leaves the universe leaves this table too.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/market_breadth_schema.sql
-- Safe to re-run.

create table if not exists market_breadth (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    scope text not null check (scope in ('market', 'sector', 'industry', 'index')),
    -- '' for the market row; the sector, industry or index label otherwise.
    name text not null,
    -- The sector an industry belongs to, so the filter can group them.
    parent text,
    -- Stocks in the group on the latest run; null for an index.
    members integer,
    -- Display order for index rows; null otherwise.
    position smallint,
    points integer not null,
    first_session date not null,
    last_session date not null,
    -- Delta-encoded days since 1970-01-01. Each row carries its own sessions
    -- because an index and the stock universe need not share a calendar.
    sessions text not null,
    series text not null,
    updated_at timestamptz not null default now(),

    primary key (market, scope, name)
);

alter table market_breadth enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
drop policy if exists market_breadth_read on market_breadth;
create policy market_breadth_read
    on market_breadth for select
    using (dashboard_has_access());
