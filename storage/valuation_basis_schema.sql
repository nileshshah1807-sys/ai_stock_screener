-- =====================================================================
-- What each price ratio divides the price by, and the ratios at the live price
-- =====================================================================
--
-- valuation_basis: one row per (market, symbol), the company's side of every
-- price ratio as company totals -- trailing profit, book equity, trailing
-- EBITDA, debt, cash, shares, the dividend per share -- with where the
-- trailing lines came from. See screener/valuation_basis.py.
--
-- Two writers, both upserts on the primary key, so a symbol never has two
-- rows:
--   * the dashboard publisher, every symbol of the evening run, from the same
--     frame the run scored (every column);
--   * workers/quarterly_filings.py, the trailing-year lines alone, for each
--     company it stored a filing for, minutes after the company files.
--
-- live_valuation: the live quote of each stock with its ratios at that price.
-- Display only, like live_quotes: the screen's P/E, P/B and market cap
-- during the session. Scoring stays on the completed close, worked out by
-- screener.valuation_basis.price_ratios; tests/test_valuation_basis.py holds
-- the arithmetic here equal to it.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/valuation_basis_schema.sql
-- Safe to re-run.

create table if not exists valuation_basis (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    shares_outstanding numeric,
    net_profit_ttm numeric,
    book_equity numeric,
    ebitda_ttm numeric,
    revenue_ttm numeric,
    total_debt numeric,
    total_cash numeric,
    dividend_per_share numeric,
    -- The latest quarter in the trailing year, and its basis, where filings
    -- supplied it; null where the vendor's figures stand.
    period_end date,
    statement_basis text check (statement_basis in ('consolidated', 'standalone')),
    source text,
    -- The evening run that last wrote the full row.
    run_date date,
    updated_at timestamptz not null default now(),

    primary key (market, symbol)
);

alter table valuation_basis enable row level security;

drop policy if exists valuation_basis_read on valuation_basis;
create policy valuation_basis_read
    on valuation_basis for select
    using (dashboard_has_access());

-- A quote whose change is withheld as a change of unit (a split on its
-- ex-date) is priced in the new unit against the old share count, so it has
-- no ratios. Plain SQL from `with` to the end: tests/test_valuation_basis.py
-- runs that text on SQLite against the Python arithmetic.
create or replace view live_valuation with (security_invoker = true) as
with priced as (
    select
        q.market,
        q.symbol,
        q.price,
        q.change_pct,
        q.volume,
        q.traded_at,
        q.session,
        q.fetched_at,
        case when q.change_pct is not null and q.price > 0 then q.price end as unit_price,
        b.shares_outstanding,
        b.net_profit_ttm,
        b.book_equity,
        b.ebitda_ttm,
        b.total_debt,
        b.total_cash,
        b.dividend_per_share,
        b.period_end,
        b.statement_basis,
        b.source,
        b.updated_at
    from live_quotes q
    left join valuation_basis b on b.market = q.market and b.symbol = q.symbol
    where q.kind = 'stock'
), capped as (
    select
        priced.*,
        case when shares_outstanding > 0 then unit_price * shares_outstanding end as market_cap
    from priced
)
select
    market,
    symbol,
    price,
    change_pct,
    volume,
    traded_at,
    session,
    fetched_at,
    market_cap,
    market_cap / nullif(net_profit_ttm, 0) as pe_ratio,
    market_cap / nullif(book_equity, 0) as pb_ratio,
    (market_cap + total_debt - total_cash) / nullif(ebitda_ttm, 0) as ev_ebitda,
    dividend_per_share / unit_price * 100 as dividend_yield,
    period_end as basis_period_end,
    statement_basis,
    source as basis_source,
    updated_at as basis_updated_at
from capped;
