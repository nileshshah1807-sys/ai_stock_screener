-- =====================================================================
-- Exchange holidays and special sessions
-- =====================================================================
--
-- Display and scheduling only: nothing scores on it. One row per market and
-- exchange-local day that differs from the ordinary weekday timetable:
--   holiday          a weekday on which the exchange is shut (`reason`: why)
--   special_session  a session on a day that would otherwise be shut, with its
--                    own hours (Muhurat trading on a Sunday)
-- Ordinary weekends are not rows. `session_open` / `session_close` are
-- 'HH:MM' in the exchange's own time, null for a holiday.
--
-- Written by workers/live_quotes.py (screener/market_calendar.py builds the
-- rows: NSE's trading-holiday list plus a checked-in list of special sessions,
-- NYSE's static list); read by the same worker and by the dashboard notice.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/market_calendar_schema.sql
-- Safe to re-run.

create table if not exists market_calendar (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    day date not null,
    kind text not null check (kind in ('holiday', 'special_session')),
    reason text not null,
    session_open text check (session_open ~ '^[0-2][0-9]:[0-5][0-9]$'),
    session_close text check (session_close ~ '^[0-2][0-9]:[0-5][0-9]$'),
    refreshed_at timestamptz not null default now(),

    primary key (market, day),
    check ((kind = 'special_session') = (session_open is not null and session_close is not null))
);

alter table market_calendar enable row level security;

drop policy if exists market_calendar_read on market_calendar;
create policy market_calendar_read
    on market_calendar for select
    using (dashboard_has_access());

revoke all on market_calendar from public, anon;
grant select on market_calendar to authenticated;
grant select, insert, update, delete on market_calendar to service_role;
