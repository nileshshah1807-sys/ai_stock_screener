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

-- =====================================================================
-- Latest-session lists behind each breadth count
-- =====================================================================
--
-- Which stocks make up each metric's count on the most recent session: the
-- 94 behind "94 new 52-week highs". Only the latest session is kept -- the
-- page lists today's names, and a per-day history would be ~10k rows a day.
--
-- Whole market only. A sector or industry view narrows the same list by the
-- snapshot's own sector/industry columns, so per-group rows would duplicate it.
--
-- Written by tools/publish_market_breadth.py: rows are upserted with one
-- published_at stamp, then everything older is deleted.

create table if not exists market_breadth_members (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    -- e20 e50 e100 e200 s2 rs bb hi lo: the keys in market_breadth.series.
    metric text not null,
    symbol text not null,
    session date not null,
    published_at timestamptz not null default now(),

    primary key (market, metric, symbol)
);

create index if not exists market_breadth_members_published_idx
    on market_breadth_members (market, published_at);

alter table market_breadth_members enable row level security;

drop policy if exists market_breadth_members_read on market_breadth_members;
create policy market_breadth_members_read
    on market_breadth_members for select
    using (dashboard_has_access());

-- Snapshot rows whose symbol is on one breadth list, for the page's list view.
--
-- A function rather than `symbol=in.(...)`: the lists run to ~2,000 symbols,
-- and PostgREST puts an `in` filter in the URL, which the gateway refuses
-- somewhere past ~20 KB (measured: 1,500 symbols pass, 2,500 fail). PostgREST
-- applies select, filters, order, range and count to a set-returning function
-- exactly as it does to a table, so the dashboard's grid query runs unchanged
-- on top of this.
--
-- `returns setof screener_snapshot` tracks the table's columns, so a column
-- added to the snapshot later needs no change here. `security invoker` keeps
-- both tables' row-level security in force for the caller.
create or replace function breadth_snapshot(p_market text, p_metric text)
returns setof screener_snapshot
language sql
stable
security invoker
set search_path = public
as $$
    select s.*
    from screener_snapshot s
    where s.market = p_market
      and exists (
          select 1
          from market_breadth_members m
          where m.market = s.market
            and m.symbol = s.symbol
            and m.metric = p_metric
      )
$$;

grant execute on function breadth_snapshot(text, text) to authenticated;
