export const RATINGS = [
  "STRONG BUY",
  "BUY",
  "HOLD",
  "REDUCE",
  "SELL",
] as const;

export type Rating = (typeof RATINGS)[number];

/**
 * Typed projection of `screener_snapshot`. The screener's full row (~370
 * columns in v4) lives in `payload`; these are the fields the grid sorts,
 * filters, and indexes on.
 */
export type SnapshotRow = {
  run_date: string;
  symbol: string;
  company: string | null;
  sector: string | null;
  industry: string | null;

  investment_rank: number | null;
  score_rank: number | null;
  recommendation_rank: number | null;
  actionable_rank: number | null;

  fundamental_score: number | null;
  technical_score: number | null;
  combined_score: number | null;
  score_after_dcf: number | null;
  evidence_score: number | null;
  decision_score_ceiling: number | null;
  decision_score: number | null;
  final_score: number | null;

  rating: Rating | string | null;
  investment_rating: string | null;
  evidence_rating: string | null;
  decision_rating: string | null;
  pre_dcf_rating: string | null;

  buy_eligible: boolean | null;
  strong_buy_eligible: boolean | null;
  trend_confirmed: boolean | null;
  coverage_eligible: boolean | null;
  rating_capped: boolean | null;
  rating_cap_reason: string | null;
  decision_cap_applied: boolean | null;
  decision_cap_reason: string | null;
  gate_failure_count: number | null;
  gate_failures: string | null;
  gate_borderline: boolean | null;
  decision_stability_status: string | null;
  data_quality: string | null;

  fundamental_coverage: number | null;
  technical_coverage: number | null;
  fund_fields_present: number | null;
  fund_fields_expected: number | null;
  fundamental_model: string | null;
  specialized_quality_eligible: boolean | null;
  fundamental_anomaly: boolean | null;

  current_price: number | null;
  pct_change_1m: number | null;
  pct_change_3m: number | null;
  pct_change_6m: number | null;
  rsi_14: number | null;
  adx_14: number | null;

  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  roe: number | null;
  debt_to_equity: number | null;
  revenue_growth: number | null;
  earnings_growth: number | null;
  dividend_yield: number | null;

  dcf_status: string | null;
  dcf_valuation_score: number | null;
  dcf_base_case_upside: number | null;
  dcf_assessment: string | null;
  dcf_blend_eligible: boolean | null;

  transcript_status: string | null;
  transcript_score: number | null;
  transcript_scoring_eligible: boolean | null;
  transcript_guidance: string | null;
  transcript_age_days: number | null;

  red_flag_status: string | null;
  red_flag_severity: number | null;
  red_flag_issuer_severity: number | null;
  red_flag_trading_severity: number | null;
  red_flag_count: number | null;
  shadow_red_flag_would_change: boolean | null;

  liquidity_grade: string | null;
  liquidity_status: string | null;
  portfolio_actionable: boolean | null;
  median_turnover_20d_inr: number | null;
  nse_impact_cost_pct: number | null;
  portfolio_estimated_build_days: number | null;

  price_bar_as_of: string | null;
  price_bar_aligned: boolean | null;
  fund_data_stale: boolean | null;
  news_sentiment: string | null;
};

/** Snapshot row including the complete source record, used by drill-down. */
export type SnapshotRowWithPayload = SnapshotRow & {
  payload: Record<string, unknown>;
};

export type ScreenerRun = {
  run_date: string;
  generated_at_utc: string;
  model_version: string | null;
  recommendation_policy_version: string | null;
  output_schema_version: string | null;
  model_validation_status: string | null;
  config_sha256: string | null;
  git_sha: string | null;
  git_dirty: boolean | null;
  market_calendar_version: string | null;
  price_bar_as_of: string | null;
  analysis_as_of: string | null;
  row_count: number;
  universe_selected_count: number | null;
  technical_requested_count: number | null;
  technical_collected_count: number | null;
  technical_failed_count: number | null;
  fundamental_missing_count: number | null;
  strong_buy_count: number;
  buy_count: number;
  hold_count: number;
  reduce_count: number;
  sell_count: number;
  manifest: Record<string, unknown> | null;
  ingested_at: string;
};

export type MoverRow = {
  observed_on: string;
  symbol: string;
  company: string | null;
  sector: string | null;
  investment_rank: number | null;
  prev_investment_rank: number | null;
  rank_change: number | null;
  rating: string | null;
  prev_rating: string | null;
  rating_changed: boolean | null;
  decision_score: number | null;
  prev_decision_score: number | null;
  score_change: number | null;
  prev_observed_on: string | null;
  is_new_entrant: boolean | null;
};

export type HistoryRow = {
  observed_on: string;
  symbol: string;
  investment_rank: number | null;
  decision_score: number | null;
  final_score: number | null;
  fundamental_score: number | null;
  technical_score: number | null;
  rating: string | null;
  current_price: number | null;
};

/** Slim record shipped to the browser for instant client-side search. */
export type SearchEntry = {
  s: string; // symbol
  c: string; // company
  r: number | null; // investment rank
  g: string | null; // rating
  d: number | null; // decision score
};

export type ScreenerFilters = {
  q?: string;
  rating?: string[];
  sector?: string[];
  minScore?: number;
  maxScore?: number;
  actionableOnly?: boolean;
  buyEligibleOnly?: boolean;
  excludeCapped?: boolean;
  hasTranscript?: boolean;
  redFlagsOnly?: boolean;
  sort?: string;
  dir?: "asc" | "desc";
  page?: number;
};
