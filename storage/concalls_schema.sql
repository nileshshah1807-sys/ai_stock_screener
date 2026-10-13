-- =====================================================================
-- Concalls: one row per earnings call, for the dashboard's Concalls page
-- =====================================================================
--
-- The transcript tables hold each call's full text and are readable by the
-- service role only. The page needs none of the text, so workers/concall_feed.py
-- derives this table from them: when the call was held, where its text came
-- from, how it scored, and the statements that moved its outlook most.
--
--   source = 'recording'    the text was transcribed from the recording the
--                           company filed the evening of the call
--                           (workers/call_recordings.py)
--   source = 'vendor'       the text is a vendor's transcript of the call,
--                           taken where the recording could not be fetched
--                           (transcripts/vendor_transcripts.py)
--   source = 'transcript'   the text is the transcript the company filed
--
-- A row starts as one of the first two and becomes the third when the
-- transcript is filed; call_date stays the day the call was held.
--
-- Display evidence only. No score, rating or rank is read from this table:
-- the screener reads transcript_sentiments and transcript_outlooks, and
-- recommendation.py stays the only writer of decisions.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/concalls_schema.sql
-- Safe to re-run. Until it is applied the worker warns and writes nothing, and
-- the page says no calls are available.

create table if not exists concall_feed (
    market text not null check (market in ('NSE', 'US')),
    symbol text not null,
    -- The reporting period the call explains: its quarter end.
    quarter date not null,
    company text,
    call_date date not null,
    source text not null check (source in ('recording', 'transcript', 'vendor')),
    -- Null until the call is scored. A call with no score has no standing;
    -- it is not the lowest.
    tone_score numeric(5,2),
    -- Where tone_score stands among the feed's scored calls, 0-100.
    tone_percentile numeric(5,2),
    guidance_direction text,
    outlook_score numeric(5,2),
    -- Management's overall stance as the outlook step read it: bullish,
    -- optimistic, neutral, cautious or bearish, with the sentence behind it.
    -- Null for a call read before the question was asked, or one the model
    -- could not place. Shown, never scored.
    management_stance text,
    management_stance_quote text,
    -- The call's outlook under the names a screener run publishes it by
    -- (Transcript_Outlook_Score, _Points, _Previous_Score, ...), so the stock
    -- page's "What management said" can show a call before a run has scored
    -- it. Null where the outlook verified nothing.
    outlook_detail jsonb,
    -- Up to three of [{"text", "tone": "positive"|"negative", "quote"}].
    highlights jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now(),

    primary key (market, symbol, quarter)
);

-- `create table if not exists` above is a no-op on an existing deployment, so
-- columns added since the table first shipped are added here.
alter table concall_feed add column if not exists management_stance text;
alter table concall_feed add column if not exists management_stance_quote text;
alter table concall_feed add column if not exists outlook_detail jsonb;

-- 'vendor' joined the sources after the table first shipped.
alter table concall_feed drop constraint if exists concall_feed_source_check;
alter table concall_feed add constraint concall_feed_source_check
    check (source in ('recording', 'transcript', 'vendor'));

create index if not exists concall_feed_recent_idx
    on concall_feed (market, call_date desc);

create or replace function set_concall_feed_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists concall_feed_updated_at on concall_feed;
create trigger concall_feed_updated_at
before update on concall_feed
for each row execute function set_concall_feed_updated_at();

alter table concall_feed enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
-- No write policy: only the service role, which bypasses RLS, writes here.
drop policy if exists concall_feed_read on concall_feed;
create policy concall_feed_read
    on concall_feed for select
    using ((select dashboard_has_access()));

revoke all on concall_feed from anon;
grant select on concall_feed to authenticated;
