-- =====================================================================
-- Filings the quarterly worker could not store, and why
-- =====================================================================
--
-- Written by workers/quarterly_filings.py on every run. The worker keeps no
-- row for a filing it never stored, so without this there is no way to tell
-- "not filed" from "filed, fetch refused" from "filed in a format we do not
-- read". One row per (market, symbol, quarter, basis), only for a filing the
-- worker could not store on its last attempt:
--
--   fetch_failed        the document could not be fetched; http_code is the
--                       archive's last answer (403 a throttle, 404 missing,
--                       0 no answer or not the document)
--   unsupported_format  the index names a file whose taxonomy the parser does
--                       not read (e.g. an insurer's IF_INS_COM_IND_AS file)
--
-- A filing that is stored is deleted from here; unsupported_format rows are written by the daily full run only; a row no run repeats for 14
-- days is pruned. Server-side only: no policy, so only the service role reads it.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/quarterly_filing_attempts_schema.sql
-- Safe to re-run. Until applied, the worker logs a warning and carries on.
--
--   select symbol, period_end, status, http_code, tried_at
--   from quarterly_filing_attempts where market = 'NSE' order by tried_at desc;

create table if not exists quarterly_filing_attempts (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    period_end date not null,
    is_consolidated boolean not null,
    seq_id text not null,
    status text not null check (status in ('fetch_failed', 'unsupported_format')),
    http_code integer,
    taxonomy text,
    document_url text not null,
    tried_at timestamptz not null default now(),

    primary key (market, symbol, period_end, is_consolidated)
);

alter table quarterly_filing_attempts enable row level security;
revoke all on quarterly_filing_attempts from anon, authenticated;

create index if not exists quarterly_filing_attempts_tried_idx
    on quarterly_filing_attempts (market, tried_at);
