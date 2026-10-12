-- =====================================================================
-- Notifications: what happened to a company since the viewer last looked
-- =====================================================================
--
-- The dashboard showed the state of each company and nothing about change. A
-- result filed this morning or a call transcript published last night looked
-- exactly like one from last quarter unless the reader opened the stock page
-- and compared dates. `market_events` records each such thing once, when a
-- worker first sees it; the bell in the header counts the ones newer than the
-- viewer's last visit.
--
-- Written by workers/market_events.py, which derives every event from data
-- the other jobs already collect:
--
--   results     NSE: a results filing in the exchange's index.
--               US:  the stored statements gaining a later quarter, which is
--                    when Yahoo published it -- there is no filing index.
--   transcript  an earnings-call transcript stored by the transcript worker.
--
-- An event is evidence about the world, not a decision: no score, rating or
-- rank is read from this table, and recommendation.py stays the only writer
-- of those.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/notifications_schema.sql
-- Safe to re-run. Until it is applied the workers warn and write nothing, and
-- the dashboard shows an empty bell.

create table if not exists market_events (
    id bigint generated always as identity primary key,
    market text not null check (market in ('NSE', 'US')),
    symbol text not null,
    company text,
    -- results | transcript
    kind text not null,
    -- What makes the event itself, within (market, kind, symbol): the quarter
    -- end for a result, the call date for a transcript. A worker that sees
    -- the same thing again writes nothing.
    event_key text not null,
    -- When it happened at the source (the filing's broadcast time), or when
    -- it was first seen where the source gives no time.
    occurred_at timestamptz not null,
    -- When this row was written. Unread is measured against this, not
    -- occurred_at: a filing found a day late is still new to the reader.
    detected_at timestamptz not null default now(),
    -- Kind-specific facts for display: {"period": "2026-09-30"}.
    detail jsonb not null default '{}'::jsonb,
    -- A row recorded only so the next change can be told from the first
    -- sighting (see market_events.py). Never shown.
    baseline boolean not null default false,

    constraint market_events_identity unique (market, kind, symbol, event_key)
);

-- The feed: one market, newest first, baselines excluded.
create index if not exists market_events_feed_idx
    on market_events (market, detected_at desc)
    where not baseline;
create index if not exists market_events_symbol_idx
    on market_events (market, symbol, detected_at desc);

alter table market_events enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
-- No write policy: only the service role, which bypasses RLS, writes here.
drop policy if exists market_events_read on market_events;
create policy market_events_read
    on market_events for select
    using (dashboard_has_access());

revoke all on market_events from anon;
grant select on market_events to authenticated;

-- ---------------------------------------------------------------------
-- When each viewer last opened the feed, per market
-- ---------------------------------------------------------------------
--
-- One timestamp rather than a row per (viewer, event). The feed is a stream
-- read newest-first, so "everything after this moment is new" is the whole
-- of the read state, and it costs one row per viewer per market however many
-- events are written.

create table if not exists notification_reads (
    -- auth.uid() as the default, so the browser never supplies the owner;
    -- the with-check below refuses the row if it somehow did.
    user_id uuid not null default auth.uid()
        references auth.users(id) on delete cascade,
    market text not null check (market in ('NSE', 'US')),
    seen_at timestamptz not null default now(),

    primary key (user_id, market)
);

alter table notification_reads enable row level security;

drop policy if exists notification_reads_owner_all on notification_reads;
create policy notification_reads_owner_all
    on notification_reads for all
    to authenticated
    using (user_id = (select auth.uid()) and (select dashboard_has_access()))
    with check (user_id = (select auth.uid()) and (select dashboard_has_access()));

revoke all on notification_reads from anon;
grant select, insert, update on notification_reads to authenticated;
