-- Upcoming results dates and earnings calls, one row per stock.
--
-- Written by workers/upcoming_events.py (a step of the Quarterly filings
-- workflow), read by the dashboard's calendar as the signed-in viewer. Apply
-- by hand, after storage/dashboard_schema.sql (dashboard_has_access()).
--
-- A reschedule overwrites the row. The worker also clears a date once it has
-- passed, so a reader needs no date test and the indexes below hold only what
-- is still ahead. About 2,000 rows at most (one per NSE stock the worker has
-- looked at); nothing prunes them.

create table if not exists upcoming_events (
    market text not null check (market in ('NSE', 'US')),
    symbol text not null,
    company text,
    -- The board meeting that approves financial results: a date, no time of day.
    next_result_date date,
    -- The meeting's stated purpose, e.g. 'Financial Results/Dividend'.
    result_purpose text,
    -- An earnings call (not an investor meet) the company has announced:
    -- next_call_at when its notice gives a date and a time (India time), and
    -- next_call_date alone when it gives a date only. Never both.
    next_call_at timestamptz,
    next_call_date date,
    -- The notice (a PDF on NSE's archive) the call was read from. Kept on a
    -- row with no call too, only as the sign the worker has read it.
    call_source_url text,
    -- When the worker last looked at this stock's notices; a notice filed
    -- later than this is new to it.
    updated_at timestamptz not null default now(),

    primary key (market, symbol),
    constraint upcoming_events_one_call_time check (next_call_at is null or next_call_date is null)
);

-- The two lists: results by date, calls by date (a call with a time is in
-- next_call_at, one without in next_call_date).
create index if not exists upcoming_events_result_idx
    on upcoming_events (market, next_result_date) where next_result_date is not null;
create index if not exists upcoming_events_call_at_idx
    on upcoming_events (market, next_call_at) where next_call_at is not null;
create index if not exists upcoming_events_call_date_idx
    on upcoming_events (market, next_call_date) where next_call_date is not null;

alter table upcoming_events enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
-- No write policy: only the service role, which bypasses RLS, writes here.
drop policy if exists upcoming_events_read on upcoming_events;
create policy upcoming_events_read
    on upcoming_events for select
    using (dashboard_has_access());

revoke all on upcoming_events from anon;
grant select on upcoming_events to authenticated;
