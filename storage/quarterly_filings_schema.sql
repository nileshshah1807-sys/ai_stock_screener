-- =====================================================================
-- Quarterly results as filed with the exchange, parsed once
-- =====================================================================
--
-- One row per (market, symbol, quarter, basis): the latest filing of that
-- quarter on that basis, standalone or consolidated. A revision is filed
-- under a new seq_id and replaces the row, as it replaces the original for
-- anyone reading the exchange today.
--
-- Written by workers/quarterly_filings.py, which runs through the evening as
-- companies file (the Quarterly filings workflow). It reads the exchange's
-- filing index, fetches only documents it has not stored, and parses each
-- one. Two readers, and neither fetches anything itself:
--
--   * the stock page's quarterly results (workers/financial_statements.py
--     builds them from these rows, with the vendor's figures only for a
--     quarter that has no filing);
--   * the screener's latest-quarter growth (screener/quarterly_results.py),
--     through `lines->revenue` and `lines->pat`.
--
-- `lines` is the quarter's own income statement in whole units of the
-- market's currency (EPS in currency per share):
--   revenue, other_income, interest, depreciation, pbt, tax, net_profit, eps,
--   operating_profit (pbt + interest + depreciation), pat (profit as the
--   growth arithmetic measures it)
-- A line the filing did not report is null, never zero.
--
-- Banks and insurers file a different statement altogether and are not
-- stored (see SUPPORTED_TAXONOMIES in screener/quarterly_results.py).
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/quarterly_filings_schema.sql
-- Safe to re-run.

create table if not exists quarterly_filings (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    period_end date not null,
    is_consolidated boolean not null,
    -- The exchange's id for the filing this row was parsed from.
    seq_id text not null,
    -- When this filing was made: the broadcast, or for a revision the time it
    -- was revised. The screener reads a filing from this date onward.
    filed_at timestamptz not null,
    -- When the company first announced the quarter, on either basis. What the
    -- notification bell times a result by; a revision does not move it.
    broadcast_at timestamptz,
    taxonomy text not null,
    document_url text not null,
    lines jsonb not null,
    -- screener.quarterly_results.PARSER_VERSION at the time of parsing. A
    -- row parsed by an older version is read again.
    parser_version integer not null,
    parsed_at timestamptz not null default now(),

    primary key (market, symbol, period_end, is_consolidated)
);

-- Serves the notification bell's "filed in the last few days" scan.
create index if not exists quarterly_filings_broadcast_idx
    on quarterly_filings (market, broadcast_at);

-- Serves the screener's read of every quarter since a date.
create index if not exists quarterly_filings_period_idx
    on quarterly_filings (market, period_end);

-- Read by the workers and the screener with the service role only; the
-- dashboard draws the stock page from financial_statements.
alter table quarterly_filings enable row level security;
