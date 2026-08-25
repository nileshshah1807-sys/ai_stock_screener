"""Model 5.0 eligibility gates on point-in-time evidence.

The gates decide which names reach a published BUY list, so a gate that fires
when it should not silently removes real candidates, and a gate that never
fires makes the whole comparison against `model_5` meaningless.
"""

import copy
import unittest

import numpy as np
import pandas as pd

from backtest.gates import (
    CLASS_BUY_ONLY,
    CLASS_CAPPED,
    CLASS_CLEAR,
    GateConfig,
    apply_gates,
    gate_failures,
    gate_summary,
)
from backtest.strategies import Model5Gated, attach_market_relative


def clean_row(**overrides):
    """A row that clears every gate; tests break one thing at a time."""
    row = {
        "Close": 120.0,
        "MA200": 100.0,
        "MA200_Slope_Pct": 1.5,
        "MA50_To_MA200_Pct": 10.0,   # MA50 = 110, so 120 > 110 > 100
        "Below_MA200_Streak": 0.0,
        "RS_Market_6M_Pct": 5.0,
        "RS_Market_12M_Pct": 8.0,
        "Quality_Percentile": 85.0,
        "Growth_Percentile": 75.0,
        "Momentum_Percentile": 80.0,
        "Quality_Coverage_Sufficient": True,
        "Growth_Coverage_Sufficient": True,
        "Value_Coverage_Sufficient": True,
        "Momentum_Coverage_Sufficient": True,
        "Risk_Coverage_Sufficient": True,
        "Score": 92.0,
    }
    row.update(overrides)
    return pd.Series(row)


class GateFailureTests(unittest.TestCase):
    def setUp(self):
        self.config = GateConfig()

    def test_a_clean_row_fails_nothing(self):
        buy, strong = gate_failures(clean_row(), self.config)
        self.assertEqual(buy, [])
        self.assertEqual(strong, [])

    def test_price_inside_the_tolerance_band_still_passes(self):
        """The band exists so a name oscillating around MA200 keeps its rating."""
        buy, _ = gate_failures(clean_row(Close=99.0), self.config)
        self.assertEqual(buy, [])

    def test_price_below_the_tolerance_band_fails_buy(self):
        buy, _ = gate_failures(clean_row(Close=95.0), self.config)
        self.assertIn("price below MA200 tolerance band (98%)", buy)

    def test_falling_ma200_fails_buy(self):
        buy, _ = gate_failures(clean_row(MA200_Slope_Pct=-0.4), self.config)
        self.assertIn("MA200 slope falling", buy)

    def test_confirmed_breakdown_needs_all_three_conditions(self):
        """A dip through the line must not revoke a rating a rebound restores."""
        streak_only = clean_row(Below_MA200_Streak=30.0)
        buy, _ = gate_failures(streak_only, self.config)
        self.assertNotIn("confirmed trend breakdown below MA200", buy)

        confirmed = clean_row(
            Below_MA200_Streak=30.0, MA200_Slope_Pct=-0.5, RS_Market_6M_Pct=-4.0
        )
        buy, _ = gate_failures(confirmed, self.config)
        self.assertIn("confirmed trend breakdown below MA200", buy)

    def test_absent_relative_strength_fails_rather_than_passes(self):
        buy, _ = gate_failures(clean_row(RS_Market_6M_Pct=None), self.config)
        self.assertIn("market relative strength unavailable", buy)

    def test_quality_below_the_buy_floor_fails_buy(self):
        buy, _ = gate_failures(clean_row(Quality_Percentile=30.0), self.config)
        self.assertIn("quality percentile below BUY floor", buy)

    def test_quality_between_the_floors_fails_only_strong_buy(self):
        buy, strong = gate_failures(clean_row(Quality_Percentile=55.0), self.config)
        self.assertEqual(buy, [])
        self.assertIn("quality percentile below STRONG BUY floor", strong)

    def test_insufficient_block_coverage_fails_buy(self):
        buy, _ = gate_failures(
            clean_row(Value_Coverage_Sufficient=False), self.config
        )
        self.assertIn("value factor coverage insufficient", buy)

    def test_missing_coverage_flag_is_not_a_failure(self):
        """Absence of the column means the block was never assessed, not that it failed."""
        row = clean_row()
        del row["Risk_Coverage_Sufficient"]
        buy, _ = gate_failures(row, self.config)
        self.assertEqual(buy, [])

    def test_unstacked_averages_fail_strong_buy_only(self):
        # MA50 above price: 120 < 130, so the bullish stack is broken.
        buy, strong = gate_failures(
            clean_row(MA50_To_MA200_Pct=30.0), self.config
        )
        self.assertEqual(buy, [])
        self.assertIn("price/MA50/MA200 not stacked bullishly", strong)

    def test_buy_failures_propagate_into_strong_failures(self):
        """Failing a BUY gate must never leave a name STRONG BUY eligible."""
        buy, strong = gate_failures(clean_row(Close=90.0), self.config)
        self.assertTrue(buy)
        for reason in buy:
            self.assertIn(reason, strong)

    def test_risk_off_regime_requires_top_decile_momentum_for_buy(self):
        buy, strong = gate_failures(
            clean_row(Momentum_Percentile=80.0), self.config, regime="RISK_OFF"
        )
        self.assertIn(
            "market regime risk-off: BUY requires top-decile momentum", buy
        )
        self.assertIn("market regime risk-off: STRONG BUY disabled", strong)

    def test_risk_off_spares_a_top_decile_name_from_the_buy_gate(self):
        buy, _ = gate_failures(
            clean_row(Momentum_Percentile=95.0), self.config, regime="RISK_OFF"
        )
        self.assertEqual(buy, [])

    def test_neutral_regime_only_tightens_strong_buy(self):
        """The mechanism, exercised with the floor explicitly configured.

        Policy 5.2.0 disables this floor by default (see the next test), but the
        overlay itself must keep working for anyone who re-enables it: neutral
        constrains STRONG BUY and must never touch BUY.
        """
        config = copy.copy(self.config)
        config.REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY = 85.0
        buy, strong = gate_failures(
            clean_row(Momentum_Percentile=80.0), config, regime="NEUTRAL"
        )
        self.assertEqual(buy, [])
        self.assertIn(
            "market regime neutral: STRONG BUY requires exceptional momentum",
            strong,
        )

    def test_momentum_percentile_floors_are_disabled_by_default(self):
        """Recommendation policy 5.2.0.

        Both momentum *percentile* floors are off. A percentile floor is
        cross-sectional -- in a falling market the top 30% by momentum is still
        the top 30% -- so it never bought absolute downside protection, and it
        measurably cost return as a selection input. See
        docs/Review/p2_relative_strength_gate_preregistration.md (R4).

        The absolute protections must remain on, which is the other half of
        this assertion: risk-off still disables STRONG BUY outright.
        """
        config = GateConfig.from_runtime()
        self.assertEqual(config.STRONG_BUY_MIN_MOMENTUM_PCT, 0.0)
        self.assertEqual(
            config.REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY, 0.0
        )
        self.assertTrue(config.REGIME_RISK_OFF_DISABLES_STRONG_BUY)
        self.assertEqual(config.REGIME_RISK_OFF_MIN_MOMENTUM_PCT, 90.0)
        self.assertEqual(config.BUY_MA200_TOLERANCE, 0.98)
        self.assertTrue(config.STRONG_BUY_REQUIRE_MA50_ABOVE_MA200)

        # A weak-momentum name in a neutral regime now clears the overlay.
        _buy, strong = gate_failures(
            clean_row(Momentum_Percentile=20.0), config, regime="NEUTRAL"
        )
        self.assertNotIn(
            "market regime neutral: STRONG BUY requires exceptional momentum",
            strong,
        )
        self.assertNotIn("momentum percentile below STRONG BUY floor", strong)

    def test_thresholds_are_read_from_the_production_config(self):
        """A drifting production threshold must not leave the backtest behind."""
        config = GateConfig.from_runtime()
        from screener.runtime import Config

        self.assertEqual(
            config.BUY_MIN_QUALITY_PCT, Config.BUY_MIN_QUALITY_PCT
        )
        self.assertEqual(
            config.STRONG_BUY_MIN_MOMENTUM_PCT, Config.STRONG_BUY_MIN_MOMENTUM_PCT
        )


class ApplyGatesTests(unittest.TestCase):
    def test_classes_and_ceilings_match_the_failures(self):
        frame = pd.DataFrame([
            clean_row(),                              # clears everything
            clean_row(Quality_Percentile=55.0),       # STRONG BUY only
            clean_row(Close=90.0),                    # BUY failure
        ])
        gated = apply_gates(frame, GateConfig())
        self.assertEqual(
            gated["Eligibility_Class"].tolist(),
            [CLASS_CLEAR, CLASS_BUY_ONLY, CLASS_CAPPED],
        )
        self.assertEqual(
            gated["Decision_Score_Ceiling"].tolist(), [100.0, 69.99, 59.99]
        )

    def test_the_gated_score_is_capped_at_the_ceiling(self):
        frame = pd.DataFrame([clean_row(Score=99.8, Quality_Percentile=55.0)])
        gated = apply_gates(frame, GateConfig())
        self.assertAlmostEqual(float(gated["Gated_Score"].iloc[0]), 69.99)

    def test_an_empty_cross_section_returns_the_columns(self):
        gated = apply_gates(pd.DataFrame(columns=["Score"]), GateConfig())
        self.assertIn("Eligibility_Class", gated)
        self.assertEqual(len(gated), 0)

    def test_summary_counts_each_class(self):
        frame = pd.DataFrame([clean_row(), clean_row(Close=90.0)])
        summary = gate_summary(apply_gates(frame, GateConfig()))
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["clear"], 1)
        self.assertEqual(summary["capped"], 1)


class Model5GatedTests(unittest.TestCase):
    def test_eligibility_dominates_research_score(self):
        """A capped name must rank below an eligible one however good its research.

        This is the whole point of the strategy: ranking on the capped score
        alone would sort a column that is constant inside a class.
        """
        frame = pd.DataFrame([
            clean_row(Score=99.9, Close=90.0),   # best research, BUY failure
            clean_row(Score=60.0),               # weaker research, clears all
        ])
        strategy = Model5Gated(GateConfig())
        scored = strategy.score(frame, {"model_5": frame})
        self.assertLess(
            float(scored["Score"].iloc[0]), float(scored["Score"].iloc[1])
        )

    def test_research_order_is_preserved_inside_a_class(self):
        frame = pd.DataFrame([
            clean_row(Score=70.0, Quality_Percentile=55.0),
            clean_row(Score=90.0, Quality_Percentile=55.0),
        ])
        scored = Model5Gated(GateConfig()).score(frame, {"model_5": frame})
        self.assertLess(
            float(scored["Score"].iloc[0]), float(scored["Score"].iloc[1])
        )
        self.assertEqual(
            scored["Eligibility_Class"].tolist(), [CLASS_BUY_ONLY, CLASS_BUY_ONLY]
        )

    def test_the_regime_reaches_the_gates_through_shared(self):
        frame = pd.DataFrame([clean_row(Momentum_Percentile=80.0)])
        strategy = Model5Gated(GateConfig())

        calm = strategy.score(frame, {"model_5": frame})
        self.assertEqual(int(calm["Eligibility_Class"].iloc[0]), CLASS_CLEAR)

        stressed = strategy.score(
            frame, {"model_5": frame, "market_regime": "RISK_OFF"}
        )
        self.assertEqual(int(stressed["Eligibility_Class"].iloc[0]), CLASS_CAPPED)


class MarketRelativeTests(unittest.TestCase):
    def test_twelve_month_relative_strength_is_centred_on_the_median(self):
        frame = pd.DataFrame({
            "Momentum_6_1_Pct": [10.0, 20.0, 30.0],
            "Pct_Change_12M": [5.0, 15.0, 25.0],
        })
        out = attach_market_relative(frame)
        self.assertEqual(out["RS_Market_12M_Pct"].tolist(), [-10.0, 0.0, 10.0])

    def test_an_absent_twelve_month_column_yields_nan_not_zero(self):
        """A missing input must fail the gate, not silently pass it as neutral."""
        out = attach_market_relative(pd.DataFrame({"Momentum_6_1_Pct": [1.0]}))
        self.assertTrue(np.isnan(float(out["RS_Market_12M_Pct"].iloc[0])))


if __name__ == "__main__":
    unittest.main()
