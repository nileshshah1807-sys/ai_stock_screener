-- =====================================================================
-- Daily price series for the stock-page chart
-- =====================================================================
--
-- One row per symbol, not one row per symbol-day. The only question these
-- tables answer is "draw this stock's chart", which reads a whole series and
-- never filters inside it. A row-per-day table for ~2,900 symbols across
-- ~2,100 sessions is 3-6M rows and 250-400 MB with its index; this shape is
-- ~25 MB, which matters on the Supabase free tier where `screener_history`
-- already grows ~146 MB/year. Cross-sectional questions ("what fell 20% this
-- month") belong to `screener_history`, which is row-per-day by design.
--
-- Values are delta-encoded compact JSON -- see `workers/price_series.py` for
-- the contract and `dashboard/lib/price-series.ts` for the reader. Prices are
-- corporate-action adjusted, so the chart cannot disagree with the prices the
-- model scored on.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/price_series_schema.sql
-- Safe to re-run.

-- The trading calendar, stored once. Each series indexes into it rather than
-- carrying its own dates, which would cost ~23 KB per symbol instead of ~23 KB
-- in total.
create table if not exists price_calendar (
    id smallint primary key default 1,
    sessions text not null,
    session_count integer not null,
    first_session date not null,
    last_session date not null,
    updated_at timestamptz not null default now(),
    constraint price_calendar_single_row check (id = 1)
);

create table if not exists price_series (
    symbol text primary key,
    -- Positions in price_calendar.sessions, delta-encoded. A gap here is a
    -- session the symbol did not trade; it is never forward-filled.
    session_deltas text not null,
    -- Adjusted close in paise, delta-encoded. Integers, so the deltas are
    -- small and no float drift can accumulate down the chain.
    closes text not null,
    volumes text not null,
    points integer not null,
    first_session date not null,
    last_session date not null,
    updated_at timestamptz not null default now()
);

-- The dashboard reads one symbol at a time; the primary key already serves
-- that. This index supports the freshness check the publisher runs.
create index if not exists price_series_last_session_idx
    on price_series (last_session desc);

alter table price_calendar enable row level security;
alter table price_series enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
-- Price history is not more sensitive than the scores beside it, but it is not
-- public either.
drop policy if exists price_calendar_read on price_calendar;
create policy price_calendar_read
    on price_calendar for select
    using (dashboard_has_access());

drop policy if exists price_series_read on price_series;
create policy price_series_read
    on price_series for select
    using (dashboard_has_access());
