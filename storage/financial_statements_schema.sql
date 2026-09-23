-- =====================================================================
-- Reported financial statements for the stock page's Financials tab
-- =====================================================================
--
-- One row per symbol, like price_series, and for the same reason: the only
-- question this answers is "draw this company's statements", which reads the
-- whole history of one symbol at once and never filters inside it.
--
-- `statements` holds the annual income statement, balance sheet and cash flow
-- plus the quarterly income statement, each as aligned period and line-item
-- arrays -- see workers/financial_statements.py for the contract. Values are in
-- the market's reporting currency, in whole units (EPS to two places). A value
-- the source did not report is null, never zero.
--
-- This is display evidence, not model input. The scoring path derives its own
-- statement factors in screener/statements.py and never reads this table, so
-- refreshing it cannot change a score or the run manifest.
--
-- Stored rather than fetched per page view: a live vendor fetch costs 1-3 s
-- per stock and is rate limited, while statements change once a quarter. The
-- worker refreshes a row only when it is stale (see its --max-age-days) or
-- when the latest reported quarter implies new results are due.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/financial_statements_schema.sql
-- Safe to re-run.

create table if not exists financial_statements (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    statements jsonb not null,
    -- False when the vendor returned nothing usable. Kept as a row so the
    -- worker does not re-ask every day, and so the page can say "not reported"
    -- rather than implying the fetch never happened.
    has_data boolean not null default false,
    currency text not null,
    source text not null,
    latest_annual date,
    latest_quarter date,
    fetched_at timestamptz not null default now(),

    primary key (market, symbol)
);

-- Serves the worker's staleness scan, which reads every row's age once a run.
create index if not exists financial_statements_fetched_idx
    on financial_statements (market, fetched_at);

alter table financial_statements enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
drop policy if exists financial_statements_read on financial_statements;
create policy financial_statements_read
    on financial_statements for select
    using (dashboard_has_access());
