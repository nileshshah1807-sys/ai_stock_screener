-- Dashboard read model.
--
-- The screener publishes a wide, evolving CSV (v4 emits ~370 columns and the
-- count changes whenever an evidence stage adds audit fields). Mirroring every
-- column as a typed Postgres column would break this schema on each model
-- revision, so the read model splits the row in two:
--
--   * typed columns for the fields the dashboard sorts, filters, or indexes on
--   * `payload` jsonb for the complete row, so drill-down never loses a field
--
-- A new audit column therefore appears in drill-down with no migration; only a
-- new *filterable* field needs one.
--
-- Storage follows the retention decision: `screener_snapshot` keeps the most
-- recent runs in full, while `screener_history` keeps a slim daily row forever
-- so rank/rating movement survives snapshot pruning.
--
-- Run this in the Supabase SQL Editor. It is idempotent and safe to re-run
-- after pulling updates. It does not touch the transcript or red-flag tables
-- created by storage/supabase_schema.sql.

create extension if not exists pg_trgm;

-- =====================================================================
-- Access control
-- =====================================================================

-- Invite-only: a Supabase Auth user can read nothing until their email is
-- listed here. Seed the first entry from the SQL Editor, which runs as owner:
--   insert into dashboard_allowlist (email, role) values ('you@example.com', 'admin');
create table if not exists dashboard_allowlist (
    email text primary key,
    role text not null default 'viewer' check (role in ('viewer', 'admin')),
    created_at timestamptz not null default now()
);

alter table dashboard_allowlist enable row level security;

-- Lower-cased comparison: Supabase stores the verified email as entered, and a
-- case-mismatched invite would otherwise silently deny a legitimate user.
create or replace function dashboard_has_access()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from dashboard_allowlist a
        where lower(a.email) = lower(coalesce(auth.jwt() ->> 'email', ''))
    );
$$;

create or replace function dashboard_is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from dashboard_allowlist a
        where lower(a.email) = lower(coalesce(auth.jwt() ->> 'email', ''))
          and a.role = 'admin'
    );
$$;

-- A signed-in user may confirm their own membership (the app needs this to
-- distinguish "not invited" from "query failed"), but may not enumerate the
-- allowlist or discover who else has access.
drop policy if exists dashboard_allowlist_self_read on dashboard_allowlist;
create policy dashboard_allowlist_self_read
    on dashboard_allowlist for select
    to authenticated
    using (lower(email) = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists dashboard_allowlist_admin_read on dashboard_allowlist;
create policy dashboard_allowlist_admin_read
    on dashboard_allowlist for select
    to authenticated
    using (dashboard_is_admin());

-- =====================================================================
-- Run metadata
-- =====================================================================

-- One row per screener run. Everything the freshness banner and run-health
-- panel need is here, so neither has to scan the snapshot table.
create table if not exists screener_runs (
    run_date date primary key,
    generated_at_utc timestamptz not null,
    -- Model identity is deliberately three separate fields: the screener bumps
    -- MODEL_VERSION for a ranking change but OUTPUT_SCHEMA_VERSION for an
    -- additive audit column, and conflating them would misreport a data-only
    -- change as a model change.
    model_version text,
    recommendation_policy_version text,
    output_schema_version text,
    model_validation_status text,
    config_sha256 text,
    git_sha text,
    git_dirty boolean,
    market_calendar_version text,
    -- Snapshot alignment: the whole cross-section must share one completed bar.
    price_bar_as_of date,
    analysis_as_of timestamptz,
    row_count integer not null default 0,
    universe_selected_count integer,
    technical_requested_count integer,
    technical_collected_count integer,
    technical_failed_count integer,
    fundamental_missing_count integer,
    -- Rating mix, precomputed so the summary tiles are a single-row read.
    strong_buy_count integer not null default 0,
    buy_count integer not null default 0,
    hold_count integer not null default 0,
    reduce_count integer not null default 0,
    sell_count integer not null default 0,
    manifest jsonb,
    ingested_at timestamptz not null default now()
);

create index if not exists screener_runs_generated_idx
    on screener_runs (generated_at_utc desc);

-- =====================================================================
-- Latest full snapshot
-- =====================================================================

create table if not exists screener_snapshot (
    run_date date not null references screener_runs(run_date) on delete cascade,
    symbol text not null,
    company text,
    sector text,
    industry text,

    -- Four rank views, kept distinct because they answer different questions.
    -- investment_rank is the primary Rank used by the top-stock report.
    investment_rank integer,
    score_rank integer,
    recommendation_rank integer,
    actionable_rank integer,

    -- The v4 score chain, in the order the finalizer computes it. Storing every
    -- stage (not just the final number) is what makes the drill-down waterfall
    -- reconstructable without re-deriving policy in the UI.
    fundamental_score numeric(6,2),
    technical_score numeric(6,2),
    combined_score numeric(6,2),
    score_after_dcf numeric(6,2),
    evidence_score numeric(6,2),
    decision_score_ceiling numeric(6,2),
    decision_score numeric(6,2),
    final_score numeric(6,2),

    rating text,
    investment_rating text,
    evidence_rating text,
    decision_rating text,
    pre_dcf_rating text,

    -- Gates and caps. A capped row is published but cannot hold conviction, so
    -- the reason has to be visible next to the score, not buried in payload.
    buy_eligible boolean,
    strong_buy_eligible boolean,
    trend_confirmed boolean,
    coverage_eligible boolean,
    rating_capped boolean,
    rating_cap_reason text,
    decision_cap_applied boolean,
    decision_cap_reason text,
    gate_failure_count integer,
    gate_failures text,
    gate_borderline boolean,
    decision_stability_status text,
    data_quality text,

    -- Coverage drives the BUY/STRONG BUY minimums, so it is filterable.
    -- These are the screener's own published shares (0-1), not a ratio derived
    -- from the field counts: the model shrinks the technical score toward
    -- neutral by exactly this factor, so the two must not disagree.
    fundamental_coverage numeric(6,4),
    technical_coverage numeric(6,4),
    fund_fields_present integer,
    fund_fields_expected integer,
    fundamental_model text,
    specialized_quality_eligible boolean,
    fundamental_anomaly boolean,

    -- Price and momentum, all on the same completed bar.
    current_price numeric(14,2),
    pct_change_1m numeric(10,2),
    pct_change_3m numeric(10,2),
    pct_change_6m numeric(10,2),
    rsi_14 numeric(8,2),
    adx_14 numeric(8,2),

    -- Headline fundamentals.
    market_cap numeric(20,2),
    pe_ratio numeric(12,2),
    pb_ratio numeric(12,2),
    roe numeric(12,4),
    debt_to_equity numeric(12,2),
    revenue_growth numeric(12,4),
    earnings_growth numeric(12,4),
    dividend_yield numeric(12,4),

    -- Reverse DCF evidence.
    dcf_status text,
    dcf_valuation_score numeric(6,2),
    dcf_base_case_upside numeric(12,4),
    dcf_assessment text,
    dcf_blend_eligible boolean,

    -- Transcript evidence. eligibility is separate from availability: an
    -- expired or prior-cycle call is visible but must not affect the score.
    transcript_status text,
    transcript_score numeric(6,2),
    transcript_scoring_eligible boolean,
    transcript_guidance text,
    transcript_age_days integer,

    -- Shadow red flags: counterfactual only, never applied to live score.
    red_flag_status text,
    red_flag_severity smallint,
    red_flag_issuer_severity smallint,
    red_flag_trading_severity smallint,
    red_flag_count integer,
    shadow_red_flag_would_change boolean,

    -- Execution overlay, which never changes score or rating.
    liquidity_grade text,
    liquidity_status text,
    portfolio_actionable boolean,
    median_turnover_20d_inr numeric(20,2),
    nse_impact_cost_pct numeric(10,4),
    portfolio_estimated_build_days numeric(12,2),

    -- Bar alignment for this specific row.
    price_bar_as_of date,
    price_bar_aligned boolean,
    fund_data_stale boolean,
    news_sentiment text,

    -- ---------------------------------------------------------------
    -- Model 5.0 factor architecture.
    -- Null on every 4.x row, so the UI must treat absence as "this run
    -- did not use the factor model" rather than as a missing value.
    -- factor_model_applied is the flag to branch on.
    -- ---------------------------------------------------------------
    factor_model_applied boolean,
    research_score numeric(6,2),
    research_score_raw numeric(6,2),
    research_score_basis text,

    -- The five blocks. Score is the coverage-shrunk composite actually
    -- blended; percentile is that block's cross-sectional rank, which is
    -- what the STRONG BUY gates are written against; coverage is how much
    -- of the block was observed at all.
    quality_score numeric(6,2),
    growth_score numeric(6,2),
    value_score numeric(6,2),
    momentum_score numeric(6,2),
    risk_score numeric(6,2),
    quality_percentile numeric(6,2),
    growth_percentile numeric(6,2),
    value_percentile numeric(6,2),
    momentum_percentile numeric(6,2),
    risk_percentile numeric(6,2),
    quality_coverage numeric(6,4),
    growth_coverage numeric(6,4),
    value_coverage numeric(6,4),
    momentum_coverage numeric(6,4),
    risk_coverage numeric(6,4),
    factor_coverage numeric(6,4),
    value_score_uncapped numeric(6,2),
    value_quality_cap_applied boolean,

    -- Separated decision views. research_rating is uncapped evidence;
    -- policy_eligible_rating is the published label; execution_status is
    -- the liquidity view. eligibility_class drives the primary ordering:
    -- 0 clears every gate, 1 BUY-eligible, 2 capped, 3 unscorable.
    research_rating text,
    policy_eligible_rating text,
    execution_status text,
    eligibility_class smallint,
    primary_gate text,
    gate_severity integer,
    market_regime text,

    -- Long-trend structure and medium-term momentum.
    ma200 numeric(14,2),
    ma200_slope_pct numeric(10,4),
    price_to_ma200_pct numeric(10,3),
    ma50_to_ma200_pct numeric(10,3),
    below_ma200_streak integer,
    momentum_12_1_pct numeric(10,2),
    momentum_6_1_pct numeric(10,2),
    pct_change_12m numeric(10,2),
    rs_market_6m_pct numeric(10,3),
    rs_market_12m_pct numeric(10,3),
    rs_sector_6m_pct numeric(10,3),
    trend_quality_r2 numeric(8,4),

    -- Downside risk and one statement-derived quality headline.
    volatility_ann_pct numeric(10,3),
    max_drawdown_1y_pct numeric(10,3),
    downside_deviation_pct numeric(10,3),
    roic numeric(12,4),

    -- Complete source row. Every column above also appears here; the typed
    -- copies exist for indexing, not as the record of truth.
    payload jsonb not null,

    primary key (run_date, symbol)
);

-- =====================================================================
-- Model 5.0 migration for already-deployed databases
-- =====================================================================
-- `create table if not exists` above is a no-op on an existing deployment, so
-- the Model 5.0 columns would never appear there. Re-running this whole file
-- is the documented upgrade path, so the additions are repeated here as
-- idempotent ALTERs. `add column if not exists` makes each line safe to run
-- any number of times, and adding a nullable column takes no table rewrite.
--
-- Every column is nullable on purpose: rows written by the 4.x model have no
-- factor evidence, and null is the honest representation of that. Consumers
-- must branch on factor_model_applied rather than assume a missing score is a
-- zero.
alter table screener_snapshot
    add column if not exists factor_model_applied boolean,
    add column if not exists research_score numeric(6,2),
    add column if not exists research_score_raw numeric(6,2),
    add column if not exists research_score_basis text,
    add column if not exists quality_score numeric(6,2),
    add column if not exists growth_score numeric(6,2),
    add column if not exists value_score numeric(6,2),
    add column if not exists momentum_score numeric(6,2),
    add column if not exists risk_score numeric(6,2),
    add column if not exists quality_percentile numeric(6,2),
    add column if not exists growth_percentile numeric(6,2),
    add column if not exists value_percentile numeric(6,2),
    add column if not exists momentum_percentile numeric(6,2),
    add column if not exists risk_percentile numeric(6,2),
    add column if not exists quality_coverage numeric(6,4),
    add column if not exists growth_coverage numeric(6,4),
    add column if not exists value_coverage numeric(6,4),
    add column if not exists momentum_coverage numeric(6,4),
    add column if not exists risk_coverage numeric(6,4),
    add column if not exists factor_coverage numeric(6,4),
    add column if not exists value_score_uncapped numeric(6,2),
    add column if not exists value_quality_cap_applied boolean,
    add column if not exists research_rating text,
    add column if not exists policy_eligible_rating text,
    add column if not exists execution_status text,
    add column if not exists eligibility_class smallint,
    add column if not exists primary_gate text,
    add column if not exists gate_severity integer,
    add column if not exists market_regime text,
    add column if not exists ma200 numeric(14,2),
    add column if not exists ma200_slope_pct numeric(10,4),
    add column if not exists price_to_ma200_pct numeric(10,3),
    add column if not exists ma50_to_ma200_pct numeric(10,3),
    add column if not exists below_ma200_streak integer,
    add column if not exists momentum_12_1_pct numeric(10,2),
    add column if not exists momentum_6_1_pct numeric(10,2),
    add column if not exists pct_change_12m numeric(10,2),
    add column if not exists rs_market_6m_pct numeric(10,3),
    add column if not exists rs_market_12m_pct numeric(10,3),
    add column if not exists rs_sector_6m_pct numeric(10,3),
    add column if not exists trend_quality_r2 numeric(8,4),
    add column if not exists volatility_ann_pct numeric(10,3),
    add column if not exists max_drawdown_1y_pct numeric(10,3),
    add column if not exists downside_deviation_pct numeric(10,3),
    add column if not exists roic numeric(12,4);

-- Grid default ordering.
create index if not exists screener_snapshot_rank_idx
    on screener_snapshot (run_date, investment_rank);

-- Filter surfaces used by the sidebar.
create index if not exists screener_snapshot_rating_idx
    on screener_snapshot (run_date, rating);
create index if not exists screener_snapshot_sector_idx
    on screener_snapshot (run_date, sector);
create index if not exists screener_snapshot_score_idx
    on screener_snapshot (run_date, decision_score desc);

-- Model 5.0 filter and ordering surfaces. The primary Model 5.0 ordering is
-- eligibility class first, then research score, which is what the eligibility
-- index serves; the others back the sidebar's factor and regime filters.
create index if not exists screener_snapshot_eligibility_idx
    on screener_snapshot (run_date, eligibility_class, research_score desc);
create index if not exists screener_snapshot_research_score_idx
    on screener_snapshot (run_date, research_score desc);
create index if not exists screener_snapshot_primary_gate_idx
    on screener_snapshot (run_date, primary_gate);
create index if not exists screener_snapshot_quality_pct_idx
    on screener_snapshot (run_date, quality_percentile desc);
create index if not exists screener_snapshot_momentum_pct_idx
    on screener_snapshot (run_date, momentum_percentile desc);

-- Symbol lookup for drill-down by URL.
create index if not exists screener_snapshot_symbol_idx
    on screener_snapshot (symbol);

-- Substring search on ticker and company name. Trigram indexes serve
-- `ilike '%query%'`, which a btree cannot, and matter once the universe grows
-- past what is practical to filter client-side.
create index if not exists screener_snapshot_symbol_trgm_idx
    on screener_snapshot using gin (symbol gin_trgm_ops);
create index if not exists screener_snapshot_company_trgm_idx
    on screener_snapshot using gin (company gin_trgm_ops);

-- =====================================================================
-- Slim daily history
-- =====================================================================

-- Retained indefinitely. Deliberately narrow: this exists to answer "what
-- moved and what changed rating", not to reproduce a full past run. Roughly
-- 0.4 MB/day at the current universe size, so multi-year history stays well
-- inside the free tier while full snapshots are pruned.
create table if not exists screener_history (
    observed_on date not null,
    symbol text not null,
    company text,
    sector text,
    investment_rank integer,
    actionable_rank integer,
    decision_score numeric(6,2),
    evidence_score numeric(6,2),
    final_score numeric(6,2),
    fundamental_score numeric(6,2),
    technical_score numeric(6,2),
    rating text,
    current_price numeric(14,2),
    buy_eligible boolean,
    strong_buy_eligible boolean,
    rating_capped boolean,
    primary key (observed_on, symbol)
);

-- Model 5.0 migration for already-deployed databases; see the note above.
alter table screener_history
    add column if not exists research_score numeric(6,2),
    add column if not exists eligibility_class smallint,
    add column if not exists primary_gate text;

create index if not exists screener_history_symbol_date_idx
    on screener_history (symbol, observed_on desc);
create index if not exists screener_history_date_idx
    on screener_history (observed_on desc);

-- =====================================================================
-- Movers
-- =====================================================================

-- Day-over-day change, computed against the previous *available* observation
-- rather than `observed_on - 1`, so weekends and exchange holidays do not
-- register as a universe-wide exit and re-entry.
create or replace view screener_movers as
with ordered as (
    select
        h.*,
        lag(h.investment_rank) over w as prev_investment_rank,
        lag(h.rating) over w as prev_rating,
        lag(h.decision_score) over w as prev_decision_score,
        lag(h.observed_on) over w as prev_observed_on
    from screener_history h
    window w as (partition by h.symbol order by h.observed_on)
)
select
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

-- =====================================================================
-- Row level security
-- =====================================================================

-- The ingestion job and the Next.js server use the service role, which bypasses
-- RLS. These policies govern browser sessions, where the anon key is public by
-- design and RLS is the only thing standing between a visitor and the data.
alter table screener_runs enable row level security;
alter table screener_snapshot enable row level security;
alter table screener_history enable row level security;

drop policy if exists screener_runs_read on screener_runs;
create policy screener_runs_read
    on screener_runs for select
    to authenticated
    using (dashboard_has_access());

drop policy if exists screener_snapshot_read on screener_snapshot;
create policy screener_snapshot_read
    on screener_snapshot for select
    to authenticated
    using (dashboard_has_access());

drop policy if exists screener_history_read on screener_history;
create policy screener_history_read
    on screener_history for select
    to authenticated
    using (dashboard_has_access());

-- No policy is defined for `anon`, so an un-authenticated request reads nothing
-- even though the anon key ships to the browser. This is the invite-only gate.

-- Views do not carry their own RLS; they run with the privileges of their
-- owner. Granting select to `authenticated` is only safe because the underlying
-- screener_history policy is re-evaluated for the querying user under
-- security_invoker, which Postgres 15+ / Supabase supports.
alter view screener_movers set (security_invoker = true);

revoke all on screener_movers from public;
revoke all on screener_movers from anon;
grant select on screener_movers to authenticated;
grant select on screener_movers to service_role;

-- =====================================================================
-- Retention
-- =====================================================================

-- Full snapshots are the storage cost driver (~12-18 MB/day). History is not.
-- Called by the ingestion job after a successful load; the default keeps the
-- current run plus one prior run so a bad load can be inspected against its
-- predecessor before being overwritten.
create or replace function prune_screener_snapshots(keep_runs integer default 2)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    removed integer;
begin
    with doomed as (
        select run_date
        from screener_runs
        order by run_date desc
        offset greatest(1, keep_runs)
    )
    delete from screener_runs r
    using doomed d
    where r.run_date = d.run_date;

    get diagnostics removed = row_count;
    return removed;
end;
$$;

revoke all on function prune_screener_snapshots(integer) from public;
revoke all on function prune_screener_snapshots(integer) from anon, authenticated;
grant execute on function prune_screener_snapshots(integer) to service_role;

revoke all on function dashboard_has_access() from public;
revoke all on function dashboard_is_admin() from public;
grant execute on function dashboard_has_access() to authenticated, service_role;
grant execute on function dashboard_is_admin() to authenticated, service_role;
