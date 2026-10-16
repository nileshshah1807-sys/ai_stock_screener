-- =====================================================================
-- Intraday quotes and index constituents
-- =====================================================================
--
-- Display only. No score, gate or rank reads either table: the model stays on
-- the last completed session's close. These hold what the market is trading
-- at now, for the grid's Price and 1D cells, the stock page's tiles and the
-- Market page's movers by index.
--
-- live_quotes: one row per (market, symbol), overwritten every five minutes
-- by workers/live_quotes.py during the session, so the table stays the size of
-- the universe. Index levels are rows too, with kind 'index' and the index's
-- label as the symbol.
--
-- index_members: the constituents of each index the Market page ranks within,
-- re-read once a day by the same worker.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/live_quotes_schema.sql
-- Safe to re-run.

create table if not exists live_quotes (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    kind text not null default 'stock' check (kind in ('stock', 'index')),
    price numeric not null,
    previous_close numeric,
    -- Null where the price over the previous close is a change of unit (a
    -- split on its ex-date) rather than a move; see the worker's docstring.
    change_pct numeric,
    day_high numeric,
    day_low numeric,
    volume bigint,
    -- The vendor's time of the last trade, and its exchange-local date.
    traded_at timestamptz not null,
    session date not null,
    -- When the run that wrote the row fetched it; the same for every row of a
    -- run, which is how the dashboard knows when the next one is due.
    fetched_at timestamptz not null default now(),

    primary key (market, symbol)
);

create index if not exists live_quotes_session_idx on live_quotes (market, kind, session);

alter table live_quotes enable row level security;

drop policy if exists live_quotes_read on live_quotes;
create policy live_quotes_read
    on live_quotes for select
    using (dashboard_has_access());

create table if not exists index_members (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    index_name text not null,
    -- Display order of the index on the Market page.
    position smallint not null,
    symbol text not null,
    -- As the index provider names it, for constituents the screener does not
    -- rate and so has no company name for.
    company text,
    refreshed_at timestamptz not null default now(),

    primary key (market, index_name, symbol)
);

alter table index_members enable row level security;

drop policy if exists index_members_read on index_members;
create policy index_members_read
    on index_members for select
    using (dashboard_has_access());

-- The Market page's "Today's movers", every index at once, as one JSON value.
--
-- One call rather than a query per index: switching index on the page is then
-- client state with no round trip, and the whole answer is ~15 KB. Only quotes
-- from the newest session count, so a stock that has not traded today is
-- neither a gainer nor a loser. Rank and rating come from the newest run in
-- screener_snapshot where the screener rates the stock.
--
-- `security invoker` keeps every table's row-level security in force for the
-- caller.
create or replace function live_market(p_market text, p_limit integer default 10)
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
    run as (
        select max(run_date) as run_date from screener_snapshot where market = p_market
    ),
    groups as (
        select index_name, min(position) as position, count(*) as members
        from index_members
        where market = p_market
        group by index_name
    ),
    quoted as (
        select m.index_name, m.symbol, m.company, q.price, q.change_pct
        from index_members m
        join live_quotes q
            on q.market = m.market and q.symbol = m.symbol and q.kind = 'stock'
        where m.market = p_market
          and q.session = (select session from latest)
          and q.change_pct is not null
    ),
    ranked as (
        select
            quoted.*,
            row_number() over (partition by index_name order by change_pct desc, symbol) as up,
            row_number() over (partition by index_name order by change_pct asc, symbol) as down
        from quoted
    ),
    picked as (
        select
            r.index_name, r.symbol, r.price, r.change_pct, r.up, r.down,
            coalesce(s.company, r.company) as company,
            s.investment_rank,
            s.rating
        from ranked r
        left join screener_snapshot s
            on s.market = p_market
           and s.run_date = (select run_date from run)
           and s.symbol = r.symbol
        where r.up <= p_limit or r.down <= p_limit
    ),
    counts as (
        select
            index_name,
            count(*) filter (where change_pct > 0) as advances,
            count(*) filter (where change_pct < 0) as declines,
            count(*) filter (where change_pct = 0) as unchanged
        from quoted
        group by index_name
    )
    select jsonb_build_object(
        'session', (select session from latest),
        'fetched_at', (select fetched_at from latest),
        'traded_at', (select traded_at from latest),
        'indices', coalesce((
            select jsonb_agg(
                jsonb_build_object(
                    'name', g.index_name,
                    'members', g.members,
                    'level', iq.price,
                    'change_pct', iq.change_pct,
                    'advances', coalesce(c.advances, 0),
                    'declines', coalesce(c.declines, 0),
                    'unchanged', coalesce(c.unchanged, 0),
                    'gainers', coalesce((
                        select jsonb_agg(
                            jsonb_build_object(
                                'symbol', p.symbol, 'company', p.company,
                                'price', p.price, 'change_pct', p.change_pct,
                                'investment_rank', p.investment_rank, 'rating', p.rating
                            ) order by p.up
                        )
                        from picked p
                        where p.index_name = g.index_name and p.up <= p_limit and p.change_pct > 0
                    ), '[]'::jsonb),
                    'losers', coalesce((
                        select jsonb_agg(
                            jsonb_build_object(
                                'symbol', p.symbol, 'company', p.company,
                                'price', p.price, 'change_pct', p.change_pct,
                                'investment_rank', p.investment_rank, 'rating', p.rating
                            ) order by p.down
                        )
                        from picked p
                        where p.index_name = g.index_name and p.down <= p_limit and p.change_pct < 0
                    ), '[]'::jsonb)
                ) order by g.position
            )
            from groups g
            left join counts c on c.index_name = g.index_name
            left join live_quotes iq
                on iq.market = p_market
               and iq.kind = 'index'
               and iq.symbol = g.index_name
               and iq.session = (select session from latest)
        ), '[]'::jsonb)
    )
$$;

grant execute on function live_market(text, integer) to authenticated;
