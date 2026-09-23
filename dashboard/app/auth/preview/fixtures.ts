import type {
  ScreenerRun,
  SnapshotRow,
  SnapshotRowWithPayload,
} from "@/lib/types";
import type { FinancialStatementsRow, NewListingRow } from "@/lib/queries";

/**
 * Fixture data for the development-only design preview.
 *
 * SnapshotRow declares ~200 nullable columns. Spelling every one of them out
 * here would bury the handful of values the preview actually exercises, so the
 * rows below are written as partials and asserted. That assertion is safe
 * *only* because nothing outside the preview route reads these objects -- the
 * real grid gets its rows from Supabase with the full projection. Do not lift
 * this pattern into application code.
 */
function row(values: Partial<SnapshotRow>): SnapshotRow {
  return {
    run_date: "2026-08-14",
    company: null,
    logo_domain: null,
    sector: "Capital Goods",
    industry: "Non Electrical Equipment",
    ...values,
  } as SnapshotRow;
}

export const previewRun: ScreenerRun = {
  run_date: "2026-08-14",
  generated_at_utc: "2026-08-14T11:00:00Z",
  model_version: "5.0",
  recommendation_policy_version: "5.0",
  output_schema_version: "5",
  model_validation_status:
    "Research model; point-in-time out-of-sample validation pending.",
  config_sha256: null,
  git_sha: null,
  git_dirty: null,
  market_calendar_version: null,
  price_bar_as_of: "2026-08-13",
  analysis_as_of: "2026-08-13",
  row_count: 1847,
  universe_selected_count: 1847,
  technical_requested_count: null,
  technical_collected_count: null,
  technical_failed_count: null,
  fundamental_missing_count: null,
  strong_buy_count: 18,
  buy_count: 42,
  hold_count: 1245,
  reduce_count: 380,
  sell_count: 162,
  sectors: ["Capital Goods", "Financials", "IT Services", "Energy"],
  factor_model_applied: true,
  manifest: null,
  ingested_at: "2026-08-14T11:05:00Z",
};

export const previewRows: SnapshotRow[] = [
  row({
    symbol: "DIFFNKG",
    company: "Diffusion Engineers Ltd",
    investment_rank: 1,
    rating: "STRONG BUY",
    decision_score: 78.4,
    evidence_score: 78.4,
    quality_percentile: 84,
    momentum_percentile: 76,
    growth_percentile: 71,
    fundamental_coverage: 0.92,
    technical_coverage: 0.98,
    dcf_status: "OK",
    dcf_base_case_upside: 0.284,
    primary_gate: "NONE",
    current_price: 391.15,
    pct_change_1m: 4.2,
    market_cap: 14520000000,
    pe_ratio: 28.4,
    liquidity_grade: "A",
    portfolio_actionable: true,
    median_turnover_20d_inr: 184000000,
    factor_model_applied: true,
    transcript_status: "SCORED",
    red_flag_status: "CLEAR",
  }),
  row({
    symbol: "HDFCBANK",
    company: "HDFC Bank Ltd",
    logo_domain: "hdfcbank.com",
    sector: "Financials",
    industry: "Private Banks",
    investment_rank: 2,
    rating: "BUY",
    decision_score: 68.5,
    evidence_score: 72.1,
    rating_capped: true,
    rating_cap_reason: "Coverage ceiling: fundamental coverage below 75%.",
    quality_percentile: 79,
    momentum_percentile: 55,
    growth_percentile: 62,
    fundamental_coverage: 0.71,
    technical_coverage: 0.95,
    dcf_status: "OK",
    dcf_base_case_upside: 0.121,
    primary_gate: "COVERAGE",
    current_price: 1642.8,
    pct_change_1m: -0.4,
    market_cap: 1252000000000,
    pe_ratio: 18.9,
    liquidity_grade: "A",
    portfolio_actionable: true,
    median_turnover_20d_inr: 8400000000,
    factor_model_applied: true,
    transcript_status: "NOT_ELIGIBLE",
    red_flag_status: "CLEAR",
  }),
  row({
    symbol: "TCS",
    company: "Tata Consultancy Services Ltd",
    logo_domain: "tcs.com",
    sector: "IT Services",
    industry: "IT Consulting",
    investment_rank: 3,
    rating: "HOLD",
    decision_score: 56.1,
    evidence_score: 56.1,
    quality_percentile: 88,
    momentum_percentile: 22,
    growth_percentile: 34,
    fundamental_coverage: 0.96,
    technical_coverage: 1,
    dcf_status: "NOT_MEANINGFUL",
    dcf_base_case_upside: null,
    primary_gate: "MOMENTUM",
    current_price: 3184.5,
    pct_change_1m: -2.8,
    market_cap: 1152000000000,
    pe_ratio: 26.1,
    liquidity_grade: "A",
    portfolio_actionable: true,
    median_turnover_20d_inr: 6100000000,
    factor_model_applied: true,
    transcript_status: "SCORED",
    red_flag_status: "CLEAR",
  }),
  row({
    symbol: "VODAIDEA",
    company: "Vodafone Idea Ltd",
    logo_domain: "myvi.in",
    sector: "Telecom",
    industry: "Telecom Services",
    investment_rank: 1844,
    rating: "REDUCE",
    decision_score: 44.2,
    evidence_score: 51.0,
    rating_capped: true,
    rating_cap_reason: "Leverage ceiling applied.",
    quality_percentile: 8,
    momentum_percentile: 41,
    growth_percentile: 19,
    fundamental_coverage: 0.64,
    technical_coverage: 0.9,
    dcf_status: "NOT_MEANINGFUL",
    primary_gate: "DEBT",
    current_price: 7.42,
    pct_change_1m: -11.4,
    market_cap: 51800000000,
    pe_ratio: null,
    liquidity_grade: "B",
    portfolio_actionable: false,
    median_turnover_20d_inr: 940000000,
    factor_model_applied: true,
    transcript_status: "STALE",
    red_flag_status: "FLAGGED",
    red_flag_severity: 2,
  }),
  row({
    symbol: "YESBANK",
    company: "Yes Bank Ltd",
    logo_domain: "yesbank.in",
    sector: "Financials",
    industry: "Private Banks",
    investment_rank: 1847,
    rating: "SELL",
    decision_score: 31.7,
    evidence_score: 31.7,
    quality_percentile: 4,
    momentum_percentile: 12,
    growth_percentile: 9,
    fundamental_coverage: 0.58,
    technical_coverage: 0.88,
    dcf_status: "NOT_MEANINGFUL",
    primary_gate: "QUALITY",
    current_price: 18.6,
    pct_change_1m: -6.1,
    market_cap: 58300000000,
    pe_ratio: 41.2,
    liquidity_grade: "C",
    portfolio_actionable: false,
    median_turnover_20d_inr: 410000000,
    factor_model_applied: true,
    transcript_status: "MISSING",
    red_flag_status: "FLAGGED",
    red_flag_severity: 3,
  }),
];

export const previewDetailRow: SnapshotRowWithPayload = {
  ...previewRows[0],
  combined_score: 74.2,
  score_after_dcf: 78.4,
  research_score_raw: 74.2,
  research_score_basis: "percentile",
  dcf_blend_eligible: true,
  dcf_valuation_score: 68,
  transcript_scoring_eligible: true,
  buy_eligible: true,
  strong_buy_eligible: true,
  trend_confirmed: true,
  data_quality: "GOOD",
  gate_failure_count: 0,
  decision_stability_status: "STABLE",
  fundamental_model: "Capital Goods v5",
  fund_fields_present: 23,
  fund_fields_expected: 25,
  payload: {
    // Deliberately includes the value shapes that used to force a horizontal
    // scrollbar on the source-record panel: an ISO timestamp, a long sentence,
    // and fixed-scale decimals with trailing zeros.
    Fundamental_Fetched_At: "2026-08-12T17:47:36+05:30",
    Fundamental_Raw_Points: 88.25,
    Fundamental_As_Of_Quality: "fetch_timestamp",
    Fundamental_Record_Available: true,
    Fundamental_Missing_Fields: "",
    Buy_Gate_Reason:
      "Sector not supported. Generic reverse DCF is disabled for this sector: the feed lacks bank regulatory and asset-quality inputs.",
    Red_Flag_Summary: "",
    Technical_Observed_Score: 66.6,
    DCF_Discount_Rate: 0.125,
    DCF_FCF_Yield: 0.0412,
    Liquidity_Group: "Group I - liquid",
    NSE_Liquidity_Group: "Group I",
    Portfolio_Estimated_Build_Days: 1.4,
    EPS: 22.8,
    ROA: 0.1291,
    MA20: 377.51,
    MA50: 358.24,
    MACD: 8.2011,
    ADX_14: 25.07,
    CMF_21: 0.3921,
    RSI_14: 54.83,
    ATR_14: 14.21,
    Rank: 1,
    Combined_Score: 74.2,
    Research_Score_Raw: 74.2,
    Score_After_DCF: 78.4,
    Evidence_Score: 78.4,
    Decision_Score: 78.4,
    Quality_Weight: 0.3,
    Momentum_Weight: 0.2,
    Growth_Weight: 0.2,
    Value_Weight: 0.2,
    Risk_Weight: 0.1,
  },
} as SnapshotRowWithPayload;

/**
 * TCS's statements as the financials worker stored them on 23 Sep 2026 --
 * real vendor output, including the Sep 2025 quarter Yahoo does not report,
 * so the preview exercises the gap column and date-matched growth.
 */
export const previewFinancials: FinancialStatementsRow = {
  "statements": {
    "v": 1,
    "annual": {
      "income": {
        "periods": [
          "2023-03-31",
          "2024-03-31",
          "2025-03-31",
          "2026-03-31"
        ],
        "rows": {
          "revenue": [
            2254580000000,
            2408930000000,
            2553240000000,
            2670210000000
          ],
          "operating_profit": [
            627080000000,
            677600000000,
            713690000000,
            722740000000
          ],
          "other_income": [
            970000000,
            510000000,
            590000000,
            800000000
          ],
          "interest": [
            7790000000,
            7780000000,
            7960000000,
            12270000000
          ],
          "depreciation": [
            50220000000,
            49850000000,
            52420000000,
            55600000000
          ],
          "pbt": [
            569070000000,
            619970000000,
            653310000000,
            654870000000
          ],
          "tax": [
            146040000000,
            158980000000,
            165340000000,
            160330000000
          ],
          "net_profit": [
            421470000000,
            459080000000,
            485530000000,
            492100000000
          ],
          "eps": [
            115.19,
            125.88,
            134.19,
            136.01
          ],
          "expenses": [
            1627500000000,
            1731330000000,
            1839550000000,
            1947470000000
          ]
        }
      },
      "balance": {
        "periods": [
          "2023-03-31",
          "2024-03-31",
          "2025-03-31",
          "2026-03-31"
        ],
        "rows": {
          "equity_capital": [
            3660000000,
            3620000000,
            3620000000,
            3620000000
          ],
          "shareholders_equity": [
            904240000000,
            904890000000,
            947560000000,
            1072400000000
          ],
          "borrowings": [
            76880000000,
            80210000000,
            93920000000,
            112830000000
          ],
          "fixed_assets": [
            189960000000,
            188540000000,
            219480000000,
            251000000000
          ],
          "cwip": [
            13020000000,
            16520000000,
            17260000000,
            30430000000
          ],
          "investments": [
            9610000000,
            10340000000,
            8540000000,
            8220000000
          ],
          "cash": [
            71150000000,
            90070000000,
            83310000000,
            64050000000
          ],
          "total_assets": [
            1436510000000,
            1464490000000,
            1596290000000,
            1823720000000
          ],
          "reserves": [
            900580000000,
            901270000000,
            943940000000,
            1068780000000
          ],
          "other_liabilities": [
            455390000000,
            479390000000,
            554810000000,
            638490000000
          ],
          "other_assets": [
            1223920000000,
            1249090000000,
            1351010000000,
            1534070000000
          ]
        }
      },
      "cashflow": {
        "periods": [
          "2023-03-31",
          "2024-03-31",
          "2025-03-31",
          "2026-03-31"
        ],
        "rows": {
          "cfo": [
            419650000000,
            443380000000,
            489080000000,
            520940000000
          ],
          "cfi": [
            390000000,
            60260000000,
            -23180000000,
            -128450000000
          ],
          "cff": [
            -478780000000,
            -485360000000,
            -474380000000,
            -421330000000
          ],
          "net_cash_flow": [
            -58740000000,
            18280000000,
            -8480000000,
            -28840000000
          ],
          "capex": [
            -31000000000,
            -26740000000,
            -39370000000,
            -41460000000
          ],
          "fcf": [
            388650000000,
            416640000000,
            449710000000,
            479480000000
          ]
        }
      }
    },
    "quarterly": {
      "income": {
        "periods": [
          "2025-03-31",
          "2025-06-30",
          "2025-12-31",
          "2026-03-31",
          "2026-06-30"
        ],
        "rows": {
          "revenue": [
            644790000000,
            634370000000,
            670870000000,
            706980000000,
            722750000000
          ],
          "operating_profit": [
            180080000000,
            185350000000,
            159960000000,
            200330000000,
            194560000000
          ],
          "other_income": [
            10280000000,
            16600000000,
            420000000,
            7570000000,
            15680000000
          ],
          "interest": [
            2270000000,
            1950000000,
            5380000000,
            2650000000,
            2730000000
          ],
          "depreciation": [
            13790000000,
            13610000000,
            13800000000,
            14060000000,
            12390000000
          ],
          "pbt": [
            164020000000,
            169790000000,
            140780000000,
            183620000000,
            179440000000
          ],
          "tax": [
            41090000000,
            41600000000,
            33580000000,
            45780000000,
            45240000000
          ],
          "net_profit": [
            122240000000,
            127600000000,
            106570000000,
            137180000000,
            133490000000
          ],
          "eps": [
            33.79,
            35.27,
            29.45,
            37.94,
            36.9
          ],
          "expenses": [
            464710000000,
            449020000000,
            510910000000,
            506650000000,
            528190000000
          ]
        }
      }
    }
  },
  "has_data": true,
  "currency": "INR",
  "source": "Yahoo Finance",
  "latest_annual": "2026-03-31",
  "latest_quarter": "2026-06-30",
  "fetched_at": "2026-09-23T03:12:00+00:00"
};

/**
 * New listings, shaped like the worker's live output on 23 Sep 2026: one on
 * its listing day, a few building history, one below the liquidity floor.
 */
const listing = (row: Partial<NewListingRow>): NewListingRow => ({
  symbol: "",
  company: null,
  series: "EQ",
  listed_on: "2026-09-17",
  status: "insufficient_history",
  sessions: 5,
  sessions_required: 60,
  first_session: null,
  first_close: null,
  last_session: "2026-09-23",
  last_close: null,
  change_since_first_pct: null,
  avg_turnover_20d: null,
  median_turnover_20d: null,
  turnover_floor: 5000000,
  market_cap: null,
  updated_at: "2026-09-23T03:40:00+00:00",
  ...row,
});

export const previewNewListings: NewListingRow[] = [
  listing({ symbol: "SSRETAIL", company: "SS Retail Limited", listed_on: "2026-09-23", sessions: 1, last_close: 748.8, market_cap: 55689601435, median_turnover_20d: 34246672952 }),
  listing({ symbol: "RENTOMOJO", company: "Rentomojo Limited", sessions: 5, last_close: 521.35, change_since_first_pct: -2.41, median_turnover_20d: 10951487003 }),
  listing({ symbol: "KARAMTARA", company: "Karamtara Engineering Limited", sessions: 5, last_close: 361.95, change_since_first_pct: 2.83, median_turnover_20d: 5367378738 }),
  listing({ symbol: "VTMLTD", company: "VTM Limited", listed_on: "2026-09-23", sessions: 32, last_close: 44.5, change_since_first_pct: 93.9, market_cap: 4475320500, median_turnover_20d: 3807455 }),
  listing({ symbol: "SLOWCO", company: "Slow Traders Limited", listed_on: "2026-03-02", status: "below_liquidity_floor", sessions: 140, last_close: 88.1, change_since_first_pct: -12.4, market_cap: 2100000000, median_turnover_20d: 1200000 }),
];
