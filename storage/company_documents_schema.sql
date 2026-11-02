-- Links to a company's documents on the exchange's archive, one row per document.
--
-- Written by workers/company_documents.py (a step of the Quarterly filings
-- workflow, fed by the announcements fetch workers/upcoming_events.py already
-- makes), read by the dashboard's Documents tab as the signed-in viewer. Apply
-- by hand, after storage/dashboard_schema.sql (dashboard_has_access()).
--
-- Links only: no file, no text. kind is one of presentation, transcript,
-- recording (the notice that a call's recording is available), rating,
-- annual_report. Retention: a year by announced_at, except annual reports,
-- the latest three per company. About 18,000 rows and 8 MB in steady state
-- (measured 2 Nov 2026: ~420 B a row with indexes, ~8 documents a company a year).

create table if not exists company_documents (
    market text not null check (market in ('NSE', 'US')),
    symbol text not null,
    kind text not null check (kind in ('presentation', 'transcript', 'recording', 'rating', 'annual_report')),
    -- When the exchange published it (the announcement time; for an annual
    -- report its broadcast time, else the financial year end).
    announced_at timestamptz not null,
    title text not null,
    -- The document on the exchange's archive. Opens in a browser as served.
    url text not null,
    -- Annual reports: the financial year, e.g. '2025-26'. Null otherwise.
    period text,

    primary key (market, symbol, kind, url)
);

-- A company's documents, newest first; the Results card's presentation is the
-- newest of its kind within -1..+7 days of the result's broadcast time.
create index if not exists company_documents_symbol_idx
    on company_documents (market, symbol, announced_at desc);

alter table company_documents enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
-- No write policy: only the service role, which bypasses RLS, writes here.
drop policy if exists company_documents_read on company_documents;
create policy company_documents_read
    on company_documents for select
    using (dashboard_has_access());

revoke all on company_documents from anon;
grant select on company_documents to authenticated;
