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
-- one. Its readers fetch nothing themselves:
--
--   * the stock page's quarterly results (workers/financial_statements.py
--     builds them from these rows, with the vendor's figures only for a
--     quarter that has no filing);
--   * the screener's latest-quarter growth (screener/quarterly_results.py),
--     through `lines->revenue` and `lines->pat`;
--   * the notification bell's results events (workers/market_events.py);
--   * the dashboard's Results page, which reads this table as the signed-in
--     viewer, through `quarterly_result_feed` below.
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
-- Safe to re-run. Re-apply it before deploying a worker that writes a column
-- added here: PostgREST rejects a row naming a column the table lacks.

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
    -- The exchange's rendering of the filing for a person to read, where the
    -- index gives one; document_url is the XBRL a machine reads.
    viewer_url text,
    -- The company's name as the exchange lists it.
    company text,
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

-- `create table if not exists` above is a no-op on an existing deployment, so
-- columns added since the table first shipped are added here. Rows stored
-- before them are filled when the worker reads them again (PARSER_VERSION 2).
alter table quarterly_filings add column if not exists viewer_url text;
alter table quarterly_filings add column if not exists company text;

-- Serves the Results page: one quarter's filings, newest first.
create index if not exists quarterly_filings_quarter_idx
    on quarterly_filings (market, period_end, broadcast_at desc);

-- Written by the service role only, which bypasses RLS. Read by the
-- dashboard's Results page under the same rule as the rest of the read
-- model: signed in and allowlisted (dashboard_has_access(), from
-- dashboard_schema.sql, which must be applied first).
alter table quarterly_filings enable row level security;

drop policy if exists quarterly_filings_read on quarterly_filings;
create policy quarterly_filings_read
    on quarterly_filings for select
    using ((select dashboard_has_access()));

revoke all on quarterly_filings from anon;
grant select on quarterly_filings to authenticated;

-- One row per company and quarter, for the Results page to page through:
-- when the result was first announced, and on which bases it was filed. The
-- figures are read from quarterly_filings for the page's companies only. A
-- filing that reported neither revenue nor profit is not a result to show,
-- as the bell does not announce it.
--
-- security_invoker, so the policy above is evaluated for the viewer rather
-- than for the view's owner.
create or replace view quarterly_result_feed with (security_invoker = true) as
select
    market,
    symbol,
    period_end,
    coalesce(min(broadcast_at), min(filed_at)) as announced_at,
    max(company) as company,
    bool_or(is_consolidated) as has_consolidated,
    bool_or(not is_consolidated) as has_standalone
from quarterly_filings
where lines->>'revenue' is not null or lines->>'net_profit' is not null
group by market, symbol, period_end;

revoke all on quarterly_result_feed from public;
revoke all on quarterly_result_feed from anon;
grant select on quarterly_result_feed to authenticated;
grant select on quarterly_result_feed to service_role;
