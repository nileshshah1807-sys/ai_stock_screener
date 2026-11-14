/** Supabase views a reader names, as SQLite subqueries over their D1 tables (lib/db/market-repository.ts). */

// The Supabase view, as SQLite over its table (storage/quarterly_filings_schema.sql).
export const RESULT_FEED = `(SELECT market, symbol, period_end,
    coalesce(min(broadcast_at), min(filed_at)) AS announced_at,
    max(company) AS company,
    max(is_consolidated) AS has_consolidated,
    max(1 - is_consolidated) AS has_standalone,
    max(CAST(json_extract(lines, '$.period_days') AS INTEGER)) AS period_days
  FROM quarterly_filings
  WHERE json_extract(lines, '$.revenue') IS NOT NULL OR json_extract(lines, '$.net_profit') IS NOT NULL
     OR json_extract(lines, '$.cumulative.revenue') IS NOT NULL OR json_extract(lines, '$.cumulative.net_profit') IS NOT NULL
  GROUP BY market, symbol, period_end) AS "quarterly_result_feed"`;

/**
 * screener_snapshot's real columns in D1 (storage/d1/screener_snapshot.sql; its test holds the two equal).
 * Every other Supabase column is a key of the JSON text column "extra".
 */
export const SNAPSHOT_COLUMNS = `market run_date symbol company logo_domain sector industry investment_rank actionable_rank
  fundamental_score technical_score evidence_score decision_score final_score rating buy_eligible rating_capped
  rating_cap_reason decision_cap_reason fundamental_coverage technical_coverage current_price pct_change_1d
  pct_change_1m pct_change_3m pct_change_6m rsi_14 market_cap pe_ratio pb_ratio roe debt_to_equity revenue_growth
  earnings_growth dividend_yield dcf_status dcf_valuation_score dcf_base_case_upside dcf_assessment dcf_blend_eligible
  transcript_status transcript_score transcript_scoring_eligible transcript_guidance transcript_age_days
  red_flag_status red_flag_severity shadow_red_flag_would_change liquidity_grade portfolio_actionable
  median_turnover_20d_inr price_bar_as_of factor_model_applied research_score quality_score growth_score value_score
  momentum_score risk_score quality_percentile growth_percentile value_percentile momentum_percentile risk_percentile
  policy_eligible_rating eligibility_class gate_severity price_to_ma200_pct momentum_12_1_pct pct_change_12m
  rs_market_6m_pct volatility_ann_pct max_drawdown_1y_pct roic stage days_in_stage advance_age_days
  price_to_ma150_pct rs_rating rs_rating_change_1m entry_state breakdown_date breakdown_age_days breakdown_from
  stage2_entry_date stage2_entry_censored advance_age_censored pct_from_52w_high is_sme unrated_reason
  primary_gate`.split(/\s+/);
