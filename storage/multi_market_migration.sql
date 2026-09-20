-- =====================================================================
-- Multi-market migration: NSE + US in one read model
-- =====================================================================
--
-- Every table in the read model was keyed on the assumption that a symbol
-- identifies a company. Across two markets it does not: TCS is Tata
-- Consultancy on the NSE and The Container Store in the US, and MMM, BF-B and
-- a long tail of others collide the same way. So `market` joins the key of
-- everything the screener publishes.
--
-- The backfill is free. Every row that exists today was published by the NSE
-- pipeline, so `default 'NSE'` is not a guess -- it is the fact.
--
-- Run this in the Supabase SQL Editor after storage/dashboard_schema.sql and
-- storage/price_series_schema.sql. It is idempotent and safe to re-run. The
-- same columns are also folded into those two files, so a fresh deployment is
-- correct without running this at all.
--
--   psql "$SUPABASE_DB_URL" -f storage/multi_market_migration.sql

-- Markets the read model accepts are enforced with a per-table check
-- constraint rather than a shared domain or a lookup table: the set is
-- consulted on every insert, changes about once a year, and a typo'd market
-- code must fail loudly instead of quietly creating a third universe.

-- =====================================================================
-- Run metadata
-- =====================================================================

alter table screener_runs
    add column if not exists market text not null default 'NSE';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'screener_runs_market_known'
    ) then
        alter table screener_runs
            add constraint screener_runs_market_known
            check (market in ('NSE', 'US'));
    end if;
end
$$;

-- The snapshot's foreign key points at the runs primary key, so it has to come
-- off before that key can be widened, and go back on afterwards pointing at
-- both columns. Both names are dropped: the original auto-generated one on a
-- first run, and the one this file creates on a re-run -- without the second,
-- re-running fails because the primary key below still has a dependant.
alter table screener_snapshot
    drop constraint if exists screener_snapshot_run_date_fkey;
alter table screener_snapshot
    drop constraint if exists screener_snapshot_run_fkey;

alter table screener_runs
    drop constraint if exists screener_runs_pkey;
alter table screener_runs
    add constraint screener_runs_pkey primary key (market, run_date);

create index if not exists screener_runs_market_generated_idx
    on screener_runs (market, generated_at_utc desc);

-- =====================================================================
-- Snapshot
-- =====================================================================

alter table screener_snapshot
    add column if not exists market text not null default 'NSE';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'screener_snapshot_market_known'
    ) then
        alter table screener_snapshot
            add constraint screener_snapshot_market_known
            check (market in ('NSE', 'US'));
    end if;
end
$$;

alter table screener_snapshot
    drop constraint if exists screener_snapshot_pkey;
alter table screener_snapshot
    add constraint screener_snapshot_pkey primary key (market, run_date, symbol);

-- Dropped above rather than guarded here, so the reference is rebuilt against
-- the widened key every time this file runs.
alter table screener_snapshot
    add constraint screener_snapshot_run_fkey
    foreign key (market, run_date)
    references screener_runs (market, run_date) on delete cascade;

-- Every per-run index gains `market` as its leading column. Without it the
-- grid's default ordering scans both markets' rows for a date and discards
-- half. At a few thousand rows a day that is cheap, but these indexes exist
-- precisely so the grid never pays for rows it will not show.
drop index if exists screener_snapshot_rank_idx;
drop index if exists screener_snapshot_rating_idx;
drop index if exists screener_snapshot_sector_idx;
drop index if exists screener_snapshot_score_idx;
drop index if exists screener_snapshot_eligibility_idx;
drop index if exists screener_snapshot_research_score_idx;
drop index if exists screener_snapshot_primary_gate_idx;
drop index if exists screener_snapshot_quality_pct_idx;
drop index if exists screener_snapshot_momentum_pct_idx;
drop index if exists screener_snapshot_action_rank_idx;
drop index if exists screener_snapshot_stage_idx;
drop index if exists screener_snapshot_rs_rating_idx;
drop index if exists screener_snapshot_symbol_idx;

create index if not exists screener_snapshot_rank_idx
    on screener_snapshot (market, run_date, investment_rank);
create index if not exists screener_snapshot_rating_idx
    on screener_snapshot (market, run_date, rating);
create index if not exists screener_snapshot_sector_idx
    on screener_snapshot (market, run_date, sector);
create index if not exists screener_snapshot_score_idx
    on screener_snapshot (market, run_date, decision_score desc);
create index if not exists screener_snapshot_eligibility_idx
    on screener_snapshot (market, run_date, eligibility_class, research_score desc);
create index if not exists screener_snapshot_research_score_idx
    on screener_snapshot (market, run_date, research_score desc);
create index if not exists screener_snapshot_primary_gate_idx
    on screener_snapshot (market, run_date, primary_gate);
create index if not exists screener_snapshot_quality_pct_idx
    on screener_snapshot (market, run_date, quality_percentile desc);
create index if not exists screener_snapshot_momentum_pct_idx
    on screener_snapshot (market, run_date, momentum_percentile desc);
create index if not exists screener_snapshot_action_rank_idx
    on screener_snapshot (market, run_date, action_rank);
create index if not exists screener_snapshot_stage_idx
    on screener_snapshot (market, run_date, stage);
create index if not exists screener_snapshot_rs_rating_idx
    on screener_snapshot (market, run_date, rs_rating desc);

-- Drill-down by URL is always scoped to the market segment in the path.
create index if not exists screener_snapshot_symbol_idx
    on screener_snapshot (market, symbol);

-- The trigram indexes stay market-blind. A GIN trigram index cannot lead with
-- an equality column, and search is filtered by market in the query anyway.

-- =====================================================================
-- History
-- =====================================================================

alter table screener_history
    add column if not exists market text not null default 'NSE';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'screener_history_market_known'
    ) then
        alter table screener_history
            add constraint screener_history_market_known
            check (market in ('NSE', 'US'));
    end if;
end
$$;

alter table screener_history
    drop constraint if exists screener_history_pkey;
alter table screener_history
    add constraint screener_history_pkey primary key (market, observed_on, symbol);

drop index if exists screener_history_symbol_date_idx;
drop index if exists screener_history_date_idx;
create index if not exists screener_history_symbol_date_idx
    on screener_history (market, symbol, observed_on desc);
create index if not exists screener_history_date_idx
    on screener_history (market, observed_on desc);

-- =====================================================================
-- Movers
-- =====================================================================
--
-- The window must partition by (market, symbol). Partitioned by symbol alone,
-- an NSE TCS row and a US TCS row would interleave by date and every
-- "rank change" between them would be fiction.

-- `create or replace view` can only append columns to the end of an existing
-- view; `market` belongs at the front, so the view is dropped and rebuilt.
-- Everything a drop takes with it is re-applied below: the grants, and
-- crucially `security_invoker`, without which the rebuilt view would run with
-- its owner's rights and bypass row-level security entirely.
drop view if exists screener_movers;

create view screener_movers as
with ordered as (
    select
        h.*,
        lag(h.investment_rank) over w as prev_investment_rank,
        lag(h.rating) over w as prev_rating,
        lag(h.decision_score) over w as prev_decision_score,
        lag(h.observed_on) over w as prev_observed_on
    from screener_history h
    window w as (partition by h.market, h.symbol order by h.observed_on)
)
select
    market,
    observed_on,
    symbol,
    company,
    sector,
    investment_rank,
    prev_investment_rank,
    -- Positive means the stock climbed (rank 40 -> 12 reads as +28).
    prev_investment_rank - investment_rank as rank_change,
    rating,
    prev_rating,
    rating is distinct from prev_rating as rating_changed,
    decision_score,
    prev_decision_score,
    decision_score - prev_decision_score as score_change,
    prev_observed_on,
    prev_observed_on is null as is_new_entrant
from ordered;

alter view screener_movers set (security_invoker = true);

revoke all on screener_movers from public;
revoke all on screener_movers from anon;
grant select on screener_movers to authenticated;
grant select on screener_movers to service_role;

-- =====================================================================
-- Price series
-- =====================================================================

alter table price_series
    add column if not exists market text not null default 'NSE';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'price_series_market_known'
    ) then
        alter table price_series
            add constraint price_series_market_known
            check (market in ('NSE', 'US'));
    end if;
end
$$;

alter table price_series
    drop constraint if exists price_series_pkey;
alter table price_series
    add constraint price_series_pkey primary key (market, symbol);

drop index if exists price_series_last_session_idx;
create index if not exists price_series_last_session_idx
    on price_series (market, last_session desc);

-- The calendar was a deliberate single row: one trading calendar, stored once,
-- that every series indexes into. With two markets it is one row per market --
-- NSE and NYSE do not share sessions -- so the single-row check becomes a
-- per-market primary key.
alter table price_calendar
    add column if not exists market text not null default 'NSE';

alter table price_calendar
    drop constraint if exists price_calendar_single_row;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'price_calendar_market_known'
    ) then
        alter table price_calendar
            add constraint price_calendar_market_known
            check (market in ('NSE', 'US'));
    end if;
end
$$;

alter table price_calendar
    drop constraint if exists price_calendar_pkey;
alter table price_calendar
    add constraint price_calendar_pkey primary key (market);

-- `id` is left in place, nullable and unused, so an older publisher that still
-- sends it does not fail. It can be dropped once nothing writes it.
alter table price_calendar
    alter column id drop not null,
    alter column id drop default;

-- =====================================================================
-- Watchlists
-- =====================================================================
--
-- A watchlist belongs to one market and appears only on that market's tab.
-- Existing lists are NSE lists, which is what the default records.

alter table watchlists
    add column if not exists market text not null default 'NSE';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'watchlists_market_known'
    ) then
        alter table watchlists
            add constraint watchlists_market_known
            check (market in ('NSE', 'US'));
    end if;
end
$$;

-- Per-owner name uniqueness becomes per-owner-per-market, so the same reader
-- can keep a "Core holdings" list on each tab without one rejecting the other.
drop index if exists watchlists_owner_name_idx;
create unique index if not exists watchlists_owner_name_idx
    on watchlists (owner_id, market, lower(name));

drop index if exists watchlists_owner_idx;
create index if not exists watchlists_owner_idx
    on watchlists (owner_id, market, updated_at desc);

-- watchlist_items needs no market column: it inherits one from its parent
-- list, and adding a second copy would create two places for them to disagree.

-- =====================================================================
-- Transcripts
-- =====================================================================
--
-- transcript_filings already namespaced itself by exchange; only the accepted
-- values widen. `transcripts` did not, and its symbol is what the screener
-- joins sentiment on -- so without a market here, a US transcript would attach
-- itself to the NSE row that shares its ticker.

alter table transcript_filings
    drop constraint if exists transcript_filings_exchange_check;
alter table transcript_filings
    add constraint transcript_filings_exchange_check
    check (exchange in ('NSE', 'US'));

alter table transcripts
    add column if not exists market text not null default 'NSE';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'transcripts_market_known'
    ) then
        alter table transcripts
            add constraint transcripts_market_known
            check (market in ('NSE', 'US'));
    end if;
end
$$;

drop index if exists transcripts_symbol_call_date_idx;
create index if not exists transcripts_symbol_call_date_idx
    on transcripts (market, symbol, call_date desc);

-- The sentiment views window by symbol, which would interleave two markets'
-- calls into one series. Both are rebuilt here rather than replaced, for the
-- same reason as screener_movers: `market` belongs at the front of the column
-- list. `latest_transcript_sentiment` reads the other, so it is dropped first.
drop view if exists latest_transcript_sentiment;
drop view if exists transcript_sentiment_history;

create view transcript_sentiment_history as
with latest_analysis_per_transcript as (
    select
        s.*,
        row_number() over (
            partition by s.transcript_id order by s.created_at desc
        ) as analysis_rank
    from transcript_sentiments s
)
select
    t.market,
    t.symbol,
    t.call_date,
    s.overall_score,
    s.optimism_score,
    s.guidance_score,
    s.risk_score,
    s.management_confidence,
    s.guidance_direction,
    s.created_at,
    -- Every window partitions by (market, symbol). Partitioned by symbol
    -- alone, a US TCS call and an NSE TCS call would sit in one series and
    -- each quarter-on-quarter delta between them would be meaningless.
    lag(s.optimism_score) over (
        partition by t.market, t.symbol order by t.call_date nulls last, s.created_at
    ) as previous_optimism_score,
    row_number() over (
        partition by t.market, t.symbol
        order by t.call_date desc nulls last, s.created_at desc
    ) as sentiment_rank,
    s.structured_output,
    nullif(s.structured_output ->> 'uncertainty_density', '')::numeric as uncertainty_density,
    lag(nullif(s.structured_output ->> 'uncertainty_density', '')::numeric) over (
        partition by t.market, t.symbol order by t.call_date nulls last, s.created_at
    ) as previous_uncertainty_density,
    lag(s.guidance_direction) over (
        partition by t.market, t.symbol order by t.call_date nulls last, s.created_at
    ) as previous_guidance_direction
from transcripts t
join latest_analysis_per_transcript s on s.transcript_id = t.id
where s.analysis_rank = 1;

create view latest_transcript_sentiment as
select
    market,
    symbol,
    call_date,
    overall_score,
    optimism_score,
    guidance_score,
    risk_score,
    management_confidence,
    guidance_direction,
    optimism_score - previous_optimism_score as optimism_qoq_delta,
    structured_output,
    uncertainty_density - previous_uncertainty_density as uncertainty_qoq_delta,
    previous_guidance_direction
from transcript_sentiment_history
where sentiment_rank = 1;

-- These views carry the full cleaned transcript text through their joins, so
-- the grants the drop removed are restored exactly as storage/supabase_schema.sql
-- declares them. Only the service role reads them.
revoke all on transcript_sentiment_history from public;
revoke all on transcript_sentiment_history from anon, authenticated;
grant select on transcript_sentiment_history to service_role;

revoke all on latest_transcript_sentiment from public;
revoke all on latest_transcript_sentiment from anon, authenticated;
grant select on latest_transcript_sentiment to service_role;

-- Red-flag evidence is NSE/SEBI-sourced and has no US equivalent, so
-- red_flag_snapshots keeps its (source, symbol) key. Its `source` column
-- already records provenance; if a US provider is ever added it becomes a
-- second source value rather than a market column.


-- =====================================================================
-- Retention
-- =====================================================================
--
-- Adding a parameter creates an overload rather than replacing the function,
-- so the single-argument version is dropped first. It ranked runs globally,
-- which with two markets publishing the same dates would turn "keep the last
-- two runs" into "keep the last one day".

drop function if exists prune_screener_snapshots(integer);

create or replace function prune_screener_snapshots(
    keep_runs integer default 2,
    p_market text default null
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    removed integer;
begin
    -- Retention is per market. Ranking globally would let the US run's rows
    -- count against the NSE run's allowance, so "keep the last two runs" would
    -- silently become "keep the last one day" once both markets publish.
    with ranked as (
        select
            market,
            run_date,
            row_number() over (partition by market order by run_date desc) as position
        from screener_runs
        where p_market is null or market = p_market
    ),
    doomed as (
        select market, run_date
        from ranked
        where position > greatest(1, keep_runs)
    )
    delete from screener_runs r
    using doomed d
    where r.market = d.market and r.run_date = d.run_date;

    get diagnostics removed = row_count;
    return removed;
end;
$$;

revoke all on function prune_screener_snapshots(integer, text) from public;
revoke all on function prune_screener_snapshots(integer, text) from anon, authenticated;
grant execute on function prune_screener_snapshots(integer, text) to service_role;
