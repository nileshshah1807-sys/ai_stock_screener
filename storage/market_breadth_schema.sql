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

-- =====================================================================
-- Live breadth: today's counts from the five-minute quotes
-- =====================================================================
--
-- Per stock, the levels the next close is compared with: yesterday's EMAs
-- (a price is above today's EMA exactly when it is above yesterday's), the
-- prior year's high and low, and the close the six-month return runs from.
-- Written by tools/publish_market_breadth.py after each publish, as of the
-- session the charts end on (workers/market_breadth.live_levels).
--
-- Display only, like live_quotes: nothing scores on it. Stage 2 and RS rating
-- have no levels -- they are judged on completed sessions -- so their charts
-- stay on the last close.

create table if not exists market_breadth_levels (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    -- The session these levels follow; a quote from a later one is counted.
    as_of date not null,
    sector text,
    industry text,
    -- Null where the stock's history is too short for the measure, as the
    -- published count leaves it out of that denominator.
    e20 double precision,
    e50 double precision,
    e100 double precision,
    e200 double precision,
    hi double precision,
    lo double precision,
    base double precision,
    -- The benchmark's live quote row and its own base; the same on every row.
    bench_label text,
    bench_base double precision,
    published_at timestamptz not null default now(),

    primary key (market, symbol)
);

create index if not exists market_breadth_levels_published_idx
    on market_breadth_levels (market, published_at);

alter table market_breadth_levels enable row level security;

drop policy if exists market_breadth_levels_read on market_breadth_levels;
create policy market_breadth_levels_read
    on market_breadth_levels for select
    using (dashboard_has_access());

-- Today's breadth counts for the market, a sector or an industry, in the
-- same keys as market_breadth.series ("e50" of "e50d", "hi"/"lo" of "hld",
-- "bb" of "bbd"), so the page appends them to its charts as one more point.
--
-- A stock counts only with a quote from the newest session, later than its
-- levels, and with a day's change: a null change is a change of unit (a
-- split on its ex-date), whose price cannot be compared with yesterday's
-- levels. `counts` is null until a session after the levels has quotes.
--
-- Only levels as of the session the charts end on count, so neither a
-- publish that failed between its upsert and its delete nor one that wrote
-- the charts without the levels can count today against the wrong day.
create or replace function live_breadth(
    p_market text,
    p_scope text default 'market',
    p_name text default ''
)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
    with latest as (
        select max(session) as session, max(fetched_at) as fetched_at, max(traded_at) as traded_at
        from live_quotes
        where market = p_market and kind = 'stock'
    ),
    -- The session the published charts end on. Levels from any other session
    -- would count today against the wrong day -- a publish that wrote the
    -- rows but not the levels -- so then there are no live counts at all.
    charted as (
        select last_session
        from market_breadth
        where market = p_market and scope = 'market' and name = ''
    ),
    levels as (
        select l.*
        from market_breadth_levels l
        where l.market = p_market
          and l.as_of = (select last_session from charted)
          and (
              p_scope = 'market'
              or (p_scope = 'sector' and l.sector = p_name)
              or (p_scope = 'industry' and l.industry = p_name)
          )
    ),
    bench as (
        select q.price / b.bench_base as ratio
        from (
            select bench_label, bench_base
            from levels
            where bench_label is not null and bench_base > 0
            limit 1
        ) b
        join live_quotes q
            on q.market = p_market and q.kind = 'index' and q.symbol = b.bench_label
        where q.session = (select session from latest)
    ),
    traded as (
        select l.*, q.price::double precision as price
        from levels l
        join live_quotes q
            on q.market = l.market and q.symbol = l.symbol and q.kind = 'stock'
        where q.session = (select session from latest)
          and q.session > l.as_of
          and q.change_pct is not null
    )
    select jsonb_build_object(
        'session', (select session from latest),
        'fetched_at', (select fetched_at from latest),
        'traded_at', (select traded_at from latest),
        'as_of', (select max(as_of) from levels),
        'counts', (
            select case when count(*) = 0 then null else jsonb_build_object(
                'n', count(*),
                'e20', count(*) filter (where price > e20), 'e20d', count(e20),
                'e50', count(*) filter (where price > e50), 'e50d', count(e50),
                'e100', count(*) filter (where price > e100), 'e100d', count(e100),
                'e200', count(*) filter (where price > e200), 'e200d', count(e200),
                'hi', count(*) filter (where price > hi),
                'lo', count(*) filter (where price < lo),
                'hld', count(hi),
                -- price / base - 1 > benchmark / bench_base - 1, rearranged.
                'bb', count(*) filter (where price / base > (select ratio from bench)),
                'bbd', case
                    when (select ratio from bench) is null then 0
                    else count(base)
                end
            ) end
            from traded
        )
    )
$$;

grant execute on function live_breadth(text, text, text) to authenticated;
