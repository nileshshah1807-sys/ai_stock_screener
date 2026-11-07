-- =====================================================================
-- Live calls: a call's text as it is spoken (prototype, test/live-concalls)
-- =====================================================================
--
-- workers/live_calls.py listens to a call's audio, transcribes it in short
-- chunks and appends one row per passage to live_call_lines. While a call's
-- tab is open the dashboard polls two views:
--
--   select * from live_call_feed  where call_id = :id and seq > :cursor order by seq
--   select * from live_call_state where call_id = :id      -- live -> ended, even with no new lines
--
-- It holds the text of a call in progress only. The filed transcript, or the
-- recording the evening workflow transcribes, remains the record the screener
-- reads; nothing here is scored.
--
--   state = 'upcoming'   announced, not started
--   state = 'live'       the worker is listening; lines are arriving
--   state = 'ended'      the audio finished; no more lines
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/live_calls_schema.sql
-- Safe to re-run. NOT applied to production: apply to a preview project only.

create table if not exists live_calls (
    -- Stable id the dashboard links by: '{market}:{symbol}:{call date}'.
    call_id text primary key,
    market text not null check (market in ('NSE', 'US')),
    symbol text not null,
    state text not null default 'upcoming' check (state in ('upcoming', 'live', 'ended')),
    started_at timestamptz,
    ended_at timestamptz,
    -- The audio the worker listens to (webcast, HLS playlist or file). Null for
    -- a call announced as dial-in only. Server-side detail; the view omits it.
    source_url text,
    updated_at timestamptz not null default now()
);

create index if not exists live_calls_state_idx on live_calls (market, state);

create table if not exists live_call_lines (
    call_id text not null references live_calls (call_id) on delete cascade,
    -- 1, 2, 3 ... in the order spoken: the cursor a client resumes from.
    seq integer not null,
    -- Seconds from the start of the call to the start of the passage.
    start_seconds numeric(9,2) not null,
    text text not null,
    created_at timestamptz not null default now(),

    primary key (call_id, seq)
);

alter table live_calls enable row level security;
alter table live_call_lines enable row level security;

-- Same access rule as the rest of the read model. No write policy: only the
-- service role, which bypasses RLS, writes here. live_calls is closed to
-- `authenticated` because it holds source_url; viewers read the view.
drop policy if exists live_call_lines_read on live_call_lines;
create policy live_call_lines_read
    on live_call_lines for select
    using ((select dashboard_has_access()));

revoke all on live_calls, live_call_lines from anon;
revoke all on live_calls from authenticated;
grant select on live_call_lines to authenticated;

-- What the page reads. Both views run as their owner (deliberately not
-- security_invoker, unlike quarterly_result_feed) so they can read live_calls,
-- which is closed to `authenticated` because it holds source_url. Each applies
-- the access rule itself; dashboard_has_access() reads the caller's JWT.
create or replace view live_call_state as
select call_id, market, symbol, state, started_at, ended_at, updated_at
from live_calls
where (select dashboard_has_access());

create or replace view live_call_feed as
select c.call_id, c.market, c.symbol, c.state, l.seq, l.start_seconds, l.text, l.created_at
from live_call_lines l
join live_calls c using (call_id)
where (select dashboard_has_access());

revoke all on live_call_state, live_call_feed from anon;
grant select on live_call_state, live_call_feed to authenticated;

create or replace function set_live_calls_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists live_calls_updated_at on live_calls;
create trigger live_calls_updated_at
before update on live_calls
for each row execute function set_live_calls_updated_at();
