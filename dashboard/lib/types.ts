import type { ColumnId, Density } from "@/lib/columns";

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
  logo_domain: string | null;
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
  pct_change_1d: number | null;
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

  /**
   * Model 5.0 factor architecture.
   *
   * Null on every row produced by the 4.x model, which is still the default.
   * Branch on `factor_model_applied` rather than treating a missing score as
   * zero -- a 4.x run has no factor evidence at all, which is different from a
   * factor run that scored zero.
   */
  factor_model_applied: boolean | null;
  research_score: number | null;
  research_score_raw: number | null;
  research_score_basis: string | null;

  quality_score: number | null;
  growth_score: number | null;
  value_score: number | null;
  momentum_score: number | null;
  risk_score: number | null;
  quality_percentile: number | null;
  growth_percentile: number | null;
  value_percentile: number | null;
  momentum_percentile: number | null;
  risk_percentile: number | null;
  quality_coverage: number | null;
  growth_coverage: number | null;
  value_coverage: number | null;
  momentum_coverage: number | null;
  risk_coverage: number | null;
  factor_coverage: number | null;
  value_score_uncapped: number | null;
  value_quality_cap_applied: boolean | null;

  research_rating: string | null;
  policy_eligible_rating: string | null;
  execution_status: string | null;
  eligibility_class: number | null;
  primary_gate: string | null;
  gate_severity: number | null;
  market_regime: string | null;

  ma200: number | null;
  ma200_slope_pct: number | null;
  price_to_ma200_pct: number | null;
  ma50_to_ma200_pct: number | null;
  below_ma200_streak: number | null;
  momentum_12_1_pct: number | null;
  momentum_6_1_pct: number | null;
  pct_change_12m: number | null;
  rs_market_6m_pct: number | null;
  rs_market_12m_pct: number | null;
  rs_sector_6m_pct: number | null;
  trend_quality_r2: number | null;

  volatility_ann_pct: number | null;
  max_drawdown_1y_pct: number | null;
  downside_deviation_pct: number | null;
  roic: number | null;
};

/** Model 5.0 eligibility classes, in the order they rank. */
export const ELIGIBILITY_CLASSES = [
  { value: 0, label: "Clears every gate" },
  { value: 1, label: "BUY eligible" },
  { value: 2, label: "Policy capped" },
  { value: 3, label: "Unscorable" },
] as const;

/**
 * The five factor blocks. Weights are intentionally not declared here: the
 * runtime normalizes configurable weights and publishes the actual values in
 * each row's payload, which is the only truthful source for the dashboard.
 */
export const FACTOR_BLOCKS = [
  { key: "quality", label: "Quality", weightPayloadKey: "Quality_Weight" },
  { key: "momentum", label: "Momentum", weightPayloadKey: "Momentum_Weight" },
  { key: "growth", label: "Growth", weightPayloadKey: "Growth_Weight" },
  { key: "value", label: "Value", weightPayloadKey: "Value_Weight" },
  { key: "risk", label: "Risk", weightPayloadKey: "Risk_Weight" },
] as const;

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
  /**
   * Run-wide facts the publisher records so the dashboard need not rederive
   * them. Null on runs published before these columns existed, in which case
   * the screener falls back to querying for them.
   */
  sectors: string[] | null;
  factor_model_applied: boolean | null;
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
  /** Model 5.0 filters. Ignored by a 4.x run, whose factor columns are null. */
  minQuality?: number;
  minMomentum?: number;
  eligibility?: string[];
  aboveMa200?: boolean;
  sort?: string;
  dir?: "asc" | "desc";
  page?: number;
  /**
   * Presentation, not filtering. In the URL beside the filters for one reason:
   * it makes a hidden-column set and a row density part of a saved view, so
   * "the screen I look at every morning" is one link rather than a link plus
   * two settings to re-apply.
   */
  hiddenColumns?: ColumnId[];
  density?: Density;
};
