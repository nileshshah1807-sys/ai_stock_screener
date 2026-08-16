"""Behavioural spec for the Model 5.0 factor blocks."""

import json
import unittest

import numpy as np
import pandas as pd

from screener.factors import FactorModel, cross_sectional_percentile


class Config:
    FACTOR_MODEL_ENABLED = True
    FACTOR_WEIGHT_QUALITY = 0.35
    FACTOR_WEIGHT_GROWTH = 0.20
    FACTOR_WEIGHT_VALUE = 0.15
    FACTOR_WEIGHT_MOMENTUM = 0.25
    FACTOR_WEIGHT_RISK = 0.05
    FACTOR_SECTOR_NEUTRAL = True
    FACTOR_MIN_SECTOR_PEERS = 8
    FACTOR_VALUE_QUALITY_FLOOR_PCT = 30.0
    FACTOR_VALUE_CEILING_WHEN_LOW_QUALITY = 50.0
    FACTOR_MIN_BLOCK_COVERAGE = 0.50


def universe(size=40, sector="Technology"):
    """A well-populated frame where every factor input is observed."""
    rng = np.random.default_rng(5)
    return pd.DataFrame(
        {
            "Symbol": [f"SYM{index:03d}" for index in range(size)],
            "Sector": sector,
            "Fundamental_Model": "Generic Fundamental Model",
            "Current_Price": rng.uniform(100, 500, size),
            "Market_Cap": rng.uniform(1e10, 1e12, size),
            "EPS": rng.uniform(5, 40, size),
            "Book_Value": rng.uniform(50, 300, size),
            "Free_CashFlow": rng.uniform(1e8, 1e10, size),
            "Total_Debt": rng.uniform(1e8, 1e10, size),
            "Total_Cash": rng.uniform(1e8, 1e10, size),
            "EV_EBITDA": rng.uniform(5, 30, size),
            "EBIT_Latest": rng.uniform(1e8, 1e10, size),
            "DCF_Valuation_Score": rng.uniform(20, 80, size),
            "ROIC": rng.uniform(0.02, 0.35, size),
            "Gross_Profit_To_Assets": rng.uniform(0.05, 0.6, size),
            "OCF_To_Assets": rng.uniform(0.01, 0.3, size),
            "FCF_To_Assets": rng.uniform(0.0, 0.25, size),
            "Accruals_To_Assets": rng.uniform(-0.1, 0.2, size),
            "Interest_Coverage": rng.uniform(1, 60, size),
            "Net_Debt_To_EBITDA": rng.uniform(-2, 6, size),
            "Operating_Margin_Stability": rng.uniform(0.01, 0.3, size),
            "Earnings_Stability": rng.uniform(0.05, 1.5, size),
            "Asset_Growth_1Y": rng.uniform(-0.1, 0.6, size),
            "Share_Dilution_3Y": rng.uniform(-0.02, 0.15, size),
            "Revenue_CAGR_3Y": rng.uniform(-0.1, 0.4, size),
            "EPS_CAGR_3Y": rng.uniform(-0.2, 0.5, size),
            "Revenue_Acceleration": rng.uniform(-0.2, 0.3, size),
            "EPS_Acceleration": rng.uniform(-0.3, 0.4, size),
            "Margin_Direction": rng.uniform(-0.1, 0.1, size),
            "Cash_Conversion": rng.uniform(0.2, 2.0, size),
            "Momentum_12_1_Pct": rng.uniform(-40, 90, size),
            "Momentum_6_1_Pct": rng.uniform(-30, 60, size),
            "Volatility_Ann_Pct": rng.uniform(15, 70, size),
            "Trend_Quality_R2": rng.uniform(-1, 1, size),
            "Pct_Change_6M": rng.uniform(-30, 70, size),
            "Pct_Change_12M": rng.uniform(-40, 120, size),
            "Max_Drawdown_1Y_Pct": rng.uniform(-70, -5, size),
            "Downside_Deviation_Pct": rng.uniform(10, 50, size),
            "Gap_Risk_Pct": rng.uniform(1, 12, size),
            "Return_Concentration_1Y": rng.uniform(0.05, 0.5, size),
            "Trading_Frequency_60D": rng.uniform(0.6, 1.0, size),
        }
    )


CONTEXT = {"Benchmark_Return_6M_Pct": 10.0, "Benchmark_Return_12M_Pct": 20.0}


class PercentileTests(unittest.TestCase):
    def test_endpoints_map_symmetrically_to_the_full_range(self):
        values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = cross_sectional_percentile(values, None)
        # pandas' rank(pct=True) maps onto [1/n, 1], which denies the best
        # observation full credit and biases every inverted metric.
        self.assertAlmostEqual(result.iloc[0], 0.0, places=6)
        self.assertAlmostEqual(result.iloc[-1], 100.0, places=6)

    def test_lower_is_better_inverts_cleanly(self):
        values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = cross_sectional_percentile(values, None, higher_is_better=False)
        self.assertAlmostEqual(result.iloc[0], 100.0, places=6)
        self.assertAlmostEqual(result.iloc[-1], 0.0, places=6)

    def test_missing_values_stay_missing(self):
        values = pd.Series([1.0, np.nan, 3.0])
        self.assertTrue(pd.isna(cross_sectional_percentile(values, None).iloc[1]))

    def test_ranks_inside_the_sector_when_it_is_large_enough(self):
        # Every "Utility" value is small in absolute terms but each is the best
        # in its own sector, so sector-neutral ranking must score it top.
        values = pd.Series([1.0, 2.0] + [100.0, 200.0] * 5)
        groups = pd.Series(["Utility", "Utility"] + ["Tech"] * 10)
        result = cross_sectional_percentile(values, groups, min_group=2)
        self.assertAlmostEqual(result.iloc[1], 100.0, places=6)

    def test_small_sector_falls_back_to_the_market_ranking(self):
        values = pd.Series([1.0, 2.0] + [100.0, 200.0] * 5)
        groups = pd.Series(["Utility", "Utility"] + ["Tech"] * 10)
        result = cross_sectional_percentile(values, groups, min_group=8)
        # Too few peers to be a distribution: compared market-wide instead,
        # where 1.0 is the worst observation.
        self.assertAlmostEqual(result.iloc[0], 0.0, places=6)


class BlockTests(unittest.TestCase):
    def score(self, frame=None, context=None):
        return FactorModel(Config).score(
            frame if frame is not None else universe(), context or CONTEXT
        )

    def test_every_block_and_the_research_score_are_published(self):
        scored = self.score()
        for block in ("Quality", "Growth", "Value", "Momentum", "Risk"):
            self.assertIn(f"{block}_Score", scored)
            self.assertIn(f"{block}_Coverage", scored)
            self.assertIn(f"{block}_Percentile", scored)
            self.assertTrue(scored[f"{block}_Score"].between(0, 100).all())
        self.assertTrue(scored["Research_Score"].between(0, 100).all())

    def test_raw_blend_is_the_declared_weighted_average(self):
        scored = self.score()
        expected = (
            scored["Quality_Score"] * 0.35
            + scored["Growth_Score"] * 0.20
            + scored["Value_Score"] * 0.15
            + scored["Momentum_Score"] * 0.25
            + scored["Risk_Score"] * 0.05
        )
        # Allow for the half-up rounding applied to each published column.
        self.assertTrue((scored["Research_Score_Raw"] - expected).abs().max() < 0.05)

    def test_published_score_is_the_percentile_of_the_blend(self):
        scored = self.score()
        self.assertEqual(
            scored["Research_Score_Basis"].iloc[0], "cross_sectional_percentile"
        )
        # Rank-preserving with respect to the raw blend. Compared on ranks
        # directly rather than via method="spearman", which needs scipy.
        self.assertGreater(
            scored["Research_Score"].rank().corr(scored["Research_Score_Raw"].rank()),
            0.999,
        )
        # ...but spread across the full range, which the raw blend is not.
        self.assertAlmostEqual(scored["Research_Score"].min(), 0.0, places=2)
        self.assertAlmostEqual(scored["Research_Score"].max(), 100.0, places=2)

    def test_percentile_rescaling_makes_the_rating_bands_reachable(self):
        # Averaging five uniform percentile blocks concentrates the composite
        # around 50, leaving the 70/60 bands nearly unreachable. Ranking it
        # restores them: >=70 must be about the top 30% of the cross-section.
        scored = self.score(universe(size=100))
        share_strong = float((scored["Research_Score"] >= 70).mean())
        share_buy = float((scored["Research_Score"] >= 60).mean())
        self.assertAlmostEqual(share_strong, 0.30, delta=0.03)
        self.assertAlmostEqual(share_buy, 0.40, delta=0.03)
        # The raw blend would have cleared 70 far less often.
        self.assertLess(float((scored["Research_Score_Raw"] >= 70).mean()), 0.15)

    def test_factor_model_takes_over_the_core_score(self):
        scored = self.score()
        self.assertTrue(scored["Factor_Model_Applied"].all())
        pd.testing.assert_series_equal(
            scored["Combined_Score"], scored["Research_Score"], check_names=False
        )
        pd.testing.assert_series_equal(
            scored["Core_Score"], scored["Research_Score"], check_names=False
        )

    def test_dcf_weight_is_zeroed_because_it_is_already_a_value_input(self):
        # The finalizer would otherwise apply the same valuation signal twice.
        scored = self.score()
        self.assertTrue((scored["DCF_Blend_Weight"] == 0.0).all())
        self.assertTrue(scored["DCF_In_Value_Block"].all())

    def test_value_coverage_excludes_inputs_that_do_not_apply(self):
        scored = self.score()
        # Technology does not use book yield and this fixture's reverse DCF is
        # not eligible. The three applicable, observed inputs therefore amount
        # to complete coverage rather than 70% of a fixed five-input template.
        self.assertTrue((scored["Value_Coverage"] == 1.0).all())
        audit = json.loads(scored["Value_Input_Audit"].iloc[0])
        statuses = {item["input"]: item["status"] for item in audit}
        self.assertEqual(statuses["Book_Yield"], "not_applicable")
        self.assertEqual(statuses["DCF_Valuation_Score"], "not_applicable")

    def test_value_audit_distinguishes_missing_from_not_applicable(self):
        frame = universe()
        frame["DCF_Blend_Eligible"] = True
        frame.loc[0, "DCF_Valuation_Score"] = np.nan
        scored = self.score(frame)
        row = scored.iloc[0]
        audit = {
            item["input"]: item for item in json.loads(row["Value_Input_Audit"])
        }
        self.assertEqual(audit["DCF_Valuation_Score"]["status"], "missing")
        self.assertEqual(audit["Book_Yield"]["status"], "not_applicable")
        self.assertIn("unavailable", audit["DCF_Valuation_Score"]["reason"])
        self.assertAlmostEqual(row["Value_Coverage"], 0.70 / 0.85, places=4)

    def test_absent_evidence_shrinks_a_block_toward_neutral(self):
        frame = universe()
        growth_columns = [
            "Revenue_CAGR_3Y", "EPS_CAGR_3Y", "Revenue_Acceleration",
            "EPS_Acceleration", "Margin_Direction", "Cash_Conversion",
        ]
        # Strip growth evidence from half the universe.
        frame.loc[: len(frame) // 2 - 1, growth_columns] = np.nan
        scored = self.score(frame)
        blind = scored.loc[scored["Revenue_CAGR_3Y"].isna()]
        self.assertTrue((blind["Growth_Coverage"] == 0.0).all())
        # No evidence must mean no confidence, not the worst possible score.
        self.assertTrue((blind["Growth_Score"] == 50.0).all())
        self.assertFalse(blind["Growth_Coverage_Sufficient"].any())

    def test_partial_evidence_moves_only_proportionally(self):
        frame = universe()
        frame.loc[0, ["EPS_CAGR_3Y", "Revenue_Acceleration", "EPS_Acceleration",
                      "Margin_Direction", "Cash_Conversion"]] = np.nan
        frame.loc[0, "Revenue_CAGR_3Y"] = 10.0  # best in the universe
        scored = self.score(frame)
        row = scored.loc[scored["Symbol"] == "SYM000"].iloc[0]
        self.assertLess(row["Growth_Coverage"], 0.30)
        # A single top-ranked input cannot manufacture a confident 100.
        self.assertLess(row["Growth_Score"], 70.0)
        self.assertGreater(row["Growth_Score"], 50.0)

    def test_value_is_capped_on_a_low_quality_business(self):
        frame = universe()
        # Make row 0 the cheapest company in the universe and the worst one.
        frame.loc[0, ["ROIC", "Gross_Profit_To_Assets", "OCF_To_Assets",
                      "FCF_To_Assets"]] = -1.0
        frame.loc[0, ["Accruals_To_Assets", "Operating_Margin_Stability",
                      "Earnings_Stability", "Asset_Growth_1Y"]] = 10.0
        frame.loc[0, "EPS"] = 400.0
        frame.loc[0, "Current_Price"] = 10.0
        frame.loc[0, "Free_CashFlow"] = 1e12
        frame.loc[0, "DCF_Valuation_Score"] = 99.0
        scored = self.score(frame)
        row = scored.loc[scored["Symbol"] == "SYM000"].iloc[0]
        self.assertTrue(bool(row["Value_Quality_Cap_Applied"]))
        self.assertLessEqual(row["Value_Score"], 50.0)
        # The uncapped evidence stays visible rather than being deleted.
        self.assertGreater(row["Value_Score_Uncapped"], 50.0)

    def test_high_quality_cheap_stock_is_not_capped(self):
        scored = self.score()
        high_quality = scored.loc[scored["Quality_Percentile"] >= 50]
        self.assertFalse(high_quality["Value_Quality_Cap_Applied"].any())

    def test_risk_adjusted_momentum_prefers_the_calmer_path(self):
        frame = universe()
        frame.loc[0, "Momentum_12_1_Pct"] = 50.0
        frame.loc[0, "Volatility_Ann_Pct"] = 20.0
        frame.loc[1, "Momentum_12_1_Pct"] = 50.0
        frame.loc[1, "Volatility_Ann_Pct"] = 70.0
        scored = self.score(frame)
        calm = scored.loc[scored["Symbol"] == "SYM000", "RiskAdj_Momentum_12_1"].iloc[0]
        wild = scored.loc[scored["Symbol"] == "SYM001", "RiskAdj_Momentum_12_1"].iloc[0]
        self.assertGreater(calm, wild)

    def test_relative_strength_is_measured_against_the_benchmark(self):
        frame = universe()
        frame.loc[0, "Pct_Change_6M"] = 25.0
        scored = self.score(frame)
        row = scored.loc[scored["Symbol"] == "SYM000"].iloc[0]
        self.assertAlmostEqual(row["RS_Market_6M_Pct"], 15.0, places=6)

    def test_financial_rows_use_the_specialist_quality_template(self):
        frame = universe(size=30, sector="Financial Services")
        frame["Fundamental_Model"] = "Bank Equity Quality Model"
        # Banks report none of the industrial-company quality inputs.
        frame[["ROIC", "Gross_Profit_To_Assets", "OCF_To_Assets",
               "FCF_To_Assets", "Accruals_To_Assets", "Interest_Coverage",
               "Net_Debt_To_EBITDA", "Operating_Margin_Stability"]] = np.nan
        rng = np.random.default_rng(9)
        frame["ROE_Statement"] = rng.uniform(0.05, 0.25, len(frame))
        frame["ROA_Statement"] = rng.uniform(0.005, 0.03, len(frame))
        frame["Equity_To_Assets"] = rng.uniform(0.05, 0.2, len(frame))
        frame["Profit_Margin"] = rng.uniform(0.1, 0.35, len(frame))
        scored = FactorModel(Config).score(frame, CONTEXT)
        # Scored on what banks actually report, not marked down for absent EBIT.
        self.assertTrue((scored["Quality_Coverage"] > 0.8).all())
        self.assertTrue(scored["Quality_Coverage_Sufficient"].all())
        self.assertGreater(scored["Quality_Score"].std(), 1.0)

    def test_book_yield_only_applies_where_book_value_anchors_valuation(self):
        tech = FactorModel(Config).score(universe(sector="Technology"), CONTEXT)
        self.assertTrue(tech["Book_Yield"].isna().all())
        realty = FactorModel(Config).score(universe(sector="Real Estate"), CONTEXT)
        self.assertFalse(realty["Book_Yield"].isna().all())

    def test_empty_frame_is_returned_untouched(self):
        empty = pd.DataFrame()
        self.assertIs(FactorModel(Config).score(empty, CONTEXT), empty)

    def test_scoring_does_not_mutate_the_caller_frame(self):
        frame = universe()
        before = frame.copy(deep=True)
        FactorModel(Config).score(frame, CONTEXT)
        pd.testing.assert_frame_equal(frame, before)


if __name__ == "__main__":
    unittest.main()
