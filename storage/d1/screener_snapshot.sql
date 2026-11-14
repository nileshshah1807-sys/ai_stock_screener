-- cupel-core: screener_snapshot, laid out by hand (Dwight, 14 Nov 2026).
--
-- Supabase's table has 156 columns; D1 allows 100. Real columns are the ones a
-- reader filters, sorts or shows: market, run_date, symbol, every field of the
-- grid's column registry (dashboard/lib/columns.ts), every SORTABLE key and
-- filter in getSnapshotPage (dashboard/lib/queries.ts), every range in
-- dashboard/lib/screener-ranges.mjs, and the selects of the search index,
-- company facts, Not rated rows, stage breaks, home movers, Returns and the
-- "Your score" run read (dashboard/lib/custom-score.mjs RUN_COLUMNS). That is 91.
-- Every other column (64, the CSV export's and the stock page's extras) is one
-- JSON object in "extra", keyed by its Supabase column name; the D1 backend has
-- no JSON paths, so the repository parses "extra" and merges it into the row.
-- "payload" is not carried: it has lived in Storage since Oct 2026 (null on new runs).
--
-- Rating, rank and score columns are stored here as in Supabase but are
-- admin-only (rank and score: nobody, while SHOW_VERDICT is off). D1 has no
-- views, so the repository passes every row through dashboard/lib/ratings.mjs
-- (withoutRatings / withoutVerdict), which drops hidden fields inside "extra"
-- (string or object) as it does inside "payload". Redact first, then merge
-- "extra" into the row; a real column always wins over a key in "extra".
--
-- Indexes: D1 counts each index a row touches as a row written, and a run is
-- ~6.5k rows across both markets, so only the default sort gets one. The key
-- (market, run_date, symbol) bounds every other sort and filter to one run's
-- rows; the grid's page cache keeps those reads per run, not per viewer.
-- tests/test_d1_snapshot_layout.py holds this file to the dashboard's reads.

CREATE TABLE IF NOT EXISTS "screener_snapshot" (
    "market" TEXT NOT NULL,
    "run_date" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "company" TEXT,
    "logo_domain" TEXT,
    "sector" TEXT,
    "industry" TEXT,
    "investment_rank" INTEGER,
    "actionable_rank" INTEGER,
    "fundamental_score" REAL,
    "technical_score" REAL,
    "evidence_score" REAL,
    "decision_score" REAL,
    "final_score" REAL,
    "rating" TEXT,
    "buy_eligible" INTEGER,
    "rating_capped" INTEGER,
    "rating_cap_reason" TEXT,
    "decision_cap_reason" TEXT,
    "fundamental_coverage" REAL,
    "technical_coverage" REAL,
    "current_price" REAL,
    "pct_change_1d" REAL,
    "pct_change_1m" REAL,
    "pct_change_3m" REAL,
    "pct_change_6m" REAL,
    "rsi_14" REAL,
    "market_cap" REAL,
    "pe_ratio" REAL,
    "pb_ratio" REAL,
    "roe" REAL,
    "debt_to_equity" REAL,
    "revenue_growth" REAL,
    "earnings_growth" REAL,
    "dividend_yield" REAL,
    "dcf_status" TEXT,
    "dcf_valuation_score" REAL,
    "dcf_base_case_upside" REAL,
    "dcf_assessment" TEXT,
    "dcf_blend_eligible" INTEGER,
    "transcript_status" TEXT,
    "transcript_score" REAL,
    "transcript_scoring_eligible" INTEGER,
    "transcript_guidance" TEXT,
    "transcript_age_days" INTEGER,
    "red_flag_status" TEXT,
    "red_flag_severity" INTEGER,
    "shadow_red_flag_would_change" INTEGER,
    "liquidity_grade" TEXT,
    "portfolio_actionable" INTEGER,
    "median_turnover_20d_inr" REAL,
    "price_bar_as_of" TEXT,
    "factor_model_applied" INTEGER,
    "research_score" REAL,
    "quality_score" REAL,
    "growth_score" REAL,
    "value_score" REAL,
    "momentum_score" REAL,
    "risk_score" REAL,
    "quality_percentile" REAL,
    "growth_percentile" REAL,
    "value_percentile" REAL,
    "momentum_percentile" REAL,
    "risk_percentile" REAL,
    "policy_eligible_rating" TEXT,
    "eligibility_class" INTEGER,
    "gate_severity" INTEGER,
    "price_to_ma200_pct" REAL,
    "momentum_12_1_pct" REAL,
    "pct_change_12m" REAL,
    "rs_market_6m_pct" REAL,
    "volatility_ann_pct" REAL,
    "max_drawdown_1y_pct" REAL,
    "roic" REAL,
    "stage" TEXT,
    "days_in_stage" INTEGER,
    "advance_age_days" INTEGER,
    "price_to_ma150_pct" REAL,
    "rs_rating" REAL,
    "rs_rating_change_1m" REAL,
    "entry_state" TEXT,
    "breakdown_date" TEXT,
    "breakdown_age_days" INTEGER,
    "breakdown_from" TEXT,
    "stage2_entry_date" TEXT,
    "stage2_entry_censored" INTEGER,
    "advance_age_censored" INTEGER,
    "pct_from_52w_high" REAL,
    "is_sme" INTEGER,
    "unrated_reason" TEXT,
    "primary_gate" TEXT,
    "extra" TEXT,
    PRIMARY KEY ("market", "run_date", "symbol")
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS "screener_snapshot_market_cap_idx"
    ON "screener_snapshot" ("market", "run_date", "market_cap" DESC);

-- screener_history (storage/d1/history.sql, generated) is keyed (observed_on,
-- symbol, market); the stock page reads one symbol's days, which that key cannot seek.
CREATE INDEX IF NOT EXISTS "screener_history_symbol_idx"
    ON "screener_history" ("market", "symbol", "observed_on");
