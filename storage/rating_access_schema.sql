-- =====================================================================
-- Buy/sell ratings and the Returns data are readable by admins only
-- =====================================================================
--
-- A paid reader of an Indian screener that publishes ratings is buying
-- research, which needs SEBI registration (docs/commercialisation_readiness.md).
-- Until that is settled a viewer sees the evidence -- scores, ranks, stages --
-- and not the label drawn from it. The dashboard already hides the label
-- (dashboard/lib/ratings.mjs); this file makes the database refuse it too, so
-- a signed-in viewer calling the REST API with their own session cannot read
-- it either.
--
-- How: each table that carries a rating gets a `<table>_visible` view, the
-- table's own columns in the table's own order, with every rating column null
-- for a non-admin and the rating keys dropped from `payload`. The dashboard
-- reads the views; storage/rating_access_lockdown.sql then takes the base
-- tables away from `authenticated`. The publisher writes the base tables with
-- the service role and is unaffected.
--
-- The views run with their owner's rights (the owner is exempt from the base
-- tables' RLS), so each carries the access check itself, and is a
-- security_barrier view so no caller-supplied filter is evaluated before it.
--
-- APPLY ORDER
--   1. this file
--   2. storage/market_breadth_schema.sql and storage/live_quotes_schema.sql,
--      whose breadth_snapshot() and live_market() now read the views, and
--      storage/returns_backfill_schema.sql, whose simulated rankings behind
--      the Returns page are now admin-only
--   3. deploy the dashboard that reads the views
--   4. storage/rating_access_lockdown.sql
--
-- RE-APPLY this file after adding a column to screener_snapshot,
-- screener_history or screener_runs: a view lists the columns the table had
-- when it was built, so a new column reaches the dashboard only after a rebuild.
-- New columns are appended, which `create or replace view` allows; dropping or
-- retyping a column needs the view dropped first.

-- The one rule for what counts as a rating field. Kept identical to RATING_KEY
-- in dashboard/lib/ratings.mjs; dashboard/lib/ratings.test.mjs fails if they
-- drift. RS_Rating is relative strength, not a buy/sell call.
create or replace function is_rating_field(p_key text)
returns boolean
language sql
immutable
as $$
    select lower(p_key) ~ 'rating|(^|_)buy(_|$)|(^|_)capped|cap_reason|(^|_)(hold|reduce|sell)_count$|gate_warning|(^|_)gate_failures$'
       and lower(p_key) !~ '^rs_rating'
$$;

-- `payload` with its rating keys removed. Top-level keys only, which is where
-- the publisher writes them (one key per export column).
create or replace function without_ratings(p jsonb)
returns jsonb
language sql
immutable
as $$
    select case
        when p is null or jsonb_typeof(p) <> 'object' then p
        else coalesce(
            (select jsonb_object_agg(key, value) from jsonb_each(p) where not is_rating_field(key)),
            '{}'::jsonb
        )
    end
$$;

-- Builds `<p_table>_visible` from the table's current columns.
create or replace function rebuild_rating_gated_view(p_table text)
returns void
language plpgsql
set search_path = public
as $$
declare
    columns text;
    gated text := p_table || '_visible';
begin
    select string_agg(
        case
            when column_name = 'payload' then
                'case when (select dashboard_is_admin()) then t.payload else without_ratings(t.payload) end as payload'
            -- The run manifest is an archival record the dashboard never reads,
            -- and its nesting is not known here, so it is admin-only whole.
            when column_name = 'manifest' or is_rating_field(column_name) then
                format('case when (select dashboard_is_admin()) then t.%1$I end as %1$I', column_name)
            else format('t.%I', column_name)
        end,
        ', ' order by ordinal_position
    )
    into columns
    from information_schema.columns
    where table_schema = 'public' and table_name = p_table;

    if columns is null then
        raise exception 'rebuild_rating_gated_view: no table public.%', p_table;
    end if;

    execute format(
        'create or replace view %I with (security_barrier = true) as '
        'select %s from %I t where (select dashboard_has_access())',
        gated, columns, p_table
    );
    execute format('revoke all on %I from public, anon', gated);
    execute format('grant select on %I to authenticated, service_role', gated);
end
$$;

revoke all on function rebuild_rating_gated_view(text) from public;

select rebuild_rating_gated_view('screener_snapshot');
select rebuild_rating_gated_view('screener_history');
select rebuild_rating_gated_view('screener_runs');

-- Day-over-day movers: each row joined to the same symbol's previous available
-- observation. Built like the *_visible views (it replaces the earlier lag()
-- over the whole history, which read every row of screener_history on each
-- request and grew each day): it runs with its owner's rights, reads the base
-- table, and so carries the access check and the rating redaction itself. For a
-- viewer the ratings are null, so `rating_changed` is false and no upgrade or
-- downgrade shows. Same columns as storage/multi_market_migration.sql, so it is
-- replaced in place.
create or replace view screener_movers with (security_barrier = true) as
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
from (
    select
        t.market,
        t.observed_on,
        t.symbol,
        t.company,
        t.sector,
        t.investment_rank,
        p.investment_rank as prev_investment_rank,
        case when (select dashboard_is_admin()) then t.rating end as rating,
        case when (select dashboard_is_admin()) then p.rating end as prev_rating,
        t.decision_score,
        p.decision_score as prev_decision_score,
        p.observed_on as prev_observed_on
    from screener_history t
    left join lateral (
        select q.observed_on, q.investment_rank, q.rating, q.decision_score
        from screener_history q
        where q.market = t.market and q.symbol = t.symbol and q.observed_on < t.observed_on
        order by q.observed_on desc
        limit 1
    ) p on true
    where (select dashboard_has_access())
) m;

-- It no longer runs as the caller (the base table is closed to them).
alter view screener_movers reset (security_invoker);
revoke all on screener_movers from public;
revoke all on screener_movers from anon;
grant select on screener_movers to authenticated;
grant select on screener_movers to service_role;
