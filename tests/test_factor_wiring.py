"""Wiring guarantees for the Model 5.0 stages inside the composition root."""

import inspect
import unittest

import app
from screener.runtime import Config


class DefaultsTests(unittest.TestCase):
    def test_factor_model_is_off_by_default(self):
        # Model 5.0 re-ranks the universe. It must stay opt-in until the
        # candidate-validation workflow has compared it against the baseline.
        self.assertFalse(Config.FACTOR_MODEL_ENABLED)

    def test_price_history_is_long_enough_for_the_new_features(self):
        # 12-1 momentum needs ~273 sessions and a rising-MA200 test ~220.
        self.assertIn(Config.PRICE_HISTORY_PERIOD, {"1y", "2y", "5y", "10y", "max"})
        self.assertNotEqual(Config.PRICE_HISTORY_PERIOD, "6mo")

    def test_six_month_features_stay_pinned_to_a_six_month_window(self):
        # Lengthening the download must not silently redefine Avg_Turnover_INR,
        # Pct_Change_6M or the 6M high/low into two-year measures.
        self.assertEqual(Config.LEGACY_HISTORY_WINDOW_SESSIONS, 126)

    def test_statement_cache_ttl_is_long(self):
        # Annual statements restate quarterly at most; a short TTL would turn
        # every run into a multi-hour refetch for no new information.
        self.assertGreaterEqual(Config.STATEMENT_CACHE_MAX_AGE_DAYS, 30)

    def test_factor_weights_sum_to_one(self):
        total = (
            Config.FACTOR_WEIGHT_QUALITY
            + Config.FACTOR_WEIGHT_GROWTH
            + Config.FACTOR_WEIGHT_VALUE
            + Config.FACTOR_WEIGHT_MOMENTUM
            + Config.FACTOR_WEIGHT_RISK
        )
        self.assertAlmostEqual(total, 1.0, places=6)


class StageOrderTests(unittest.TestCase):
    """The policy can only gate on evidence that already exists on the frame."""

    @staticmethod
    def source():
        return inspect.getsource(app.run_daily_analysis)

    def index_of(self, needle):
        source = self.source()
        position = source.find(needle)
        self.assertNotEqual(position, -1, f"{needle!r} not found in run_daily_analysis")
        return position

    def test_statements_are_collected_before_scoring(self):
        self.assertLess(
            self.index_of("FinancialStatementCollector"),
            self.index_of("scorer.score_all_stocks"),
        )

    def test_factor_model_runs_after_dcf_and_before_finalize(self):
        # The Value block consumes DCF_Valuation_Score, and the finalizer
        # consumes the factor percentiles.
        self.assertLess(
            self.index_of("ReverseDCFModel"), self.index_of("FactorModel(config).score")
        )
        self.assertLess(
            self.index_of("FactorModel(config).score"),
            self.index_of("finalize_recommendations"),
        )

    def test_liquidity_is_enriched_before_the_policy_runs(self):
        # Model 5.0 can require execution liquidity for a published BUY, so
        # Portfolio_Actionable has to exist before the gates are evaluated.
        self.assertLess(
            self.index_of("LiquidityQualityEnricher(config).enrich"),
            self.index_of("finalize_recommendations"),
        )

    def test_actionable_rank_still_follows_the_final_ordering(self):
        self.assertLess(
            self.index_of("finalize_recommendations"),
            self.index_of("rank_actionable_recommendations"),
        )

    def test_liquidity_is_enriched_exactly_once(self):
        self.assertEqual(
            self.source().count("LiquidityQualityEnricher(config).enrich"), 1
        )


if __name__ == "__main__":
    unittest.main()
