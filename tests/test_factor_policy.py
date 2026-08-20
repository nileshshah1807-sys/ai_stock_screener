"""Behavioural spec for the Model 5.0 decision policy.

Covers the MA200 trend gate and its hysteresis, relative-strength and factor
percentile floors, the liquidity-for-BUY requirement, the market-regime overlay
and eligibility-class ranking.
"""

import json
import unittest

import pandas as pd

from screener.recommendation import (
    finalize_recommendations,
    is_integrity_gate,
    primary_gate,
)


class Config:
    # --- shared 4.x settings the policy still reads ---
    REQUIRE_UPTREND_FOR_BUY = True
    REQUIRE_ALIGNED_PRICE_BAR_FOR_BUY = True
    REVERSE_DCF_RANKING_WEIGHT = 0.10
    TRANSCRIPT_SENTIMENT_WEIGHT = 0.15
    REQUIRE_TRANSCRIPT_FOR_STRONG_BUY = False
    CAP_STRONG_BUY_ON_REPORTED_NEGATIVE_FCF = True
    FUNDAMENTAL_MIN_COVERAGE_FOR_STRONG_BUY = 0.75
    TECHNICAL_MIN_COVERAGE_FOR_STRONG_BUY = 0.90
    BORDERLINE_SCORE_BAND = 1.0
    BORDERLINE_PRICE_MA50_PCT_BAND = 1.0
    BORDERLINE_MA50_SLOPE_PCT_BAND = 0.25
    BORDERLINE_3M_RETURN_PCT_BAND = 1.0
    BORDERLINE_GROWTH_RATIO_BAND = 0.01
    BORDERLINE_ADX_BAND = 1.0
    BORDERLINE_DI_BAND = 1.0
    BORDERLINE_TECH_SCORE_BAND = 2.0
    BORDERLINE_COVERAGE_BAND = 0.05
    # --- Model 5.0 ---
    FACTOR_MODEL_ENABLED = True
    REQUIRE_MA200_TREND_FOR_BUY = True
    BUY_MA200_TOLERANCE = 0.98
    BUY_MIN_MA200_SLOPE_PCT = 0.0
    STRONG_BUY_REQUIRE_MA50_ABOVE_MA200 = True
    BUY_MIN_RS_6M = 0.0
    STRONG_BUY_MIN_RS_12M = 0.0
    BREAKDOWN_CONFIRM_SESSIONS = 10
    BUY_MIN_QUALITY_PCT = 40.0
    STRONG_BUY_MIN_QUALITY_PCT = 70.0
    STRONG_BUY_MIN_GROWTH_PCT = 60.0
    STRONG_BUY_MIN_MOMENTUM_PCT = 70.0
    FACTOR_FUNDAMENTAL_MIN_COVERAGE_FOR_BUY = 0.70
    FACTOR_TECHNICAL_MIN_COVERAGE_FOR_BUY = 0.90
    REQUIRE_LIQUIDITY_FOR_BUY = True
    RANK_BY_ELIGIBILITY_CLASS = True
    FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT = False
    MARKET_REGIME_ENABLED = True
    REGIME_RISK_OFF_DISABLES_STRONG_BUY = True
    REGIME_RISK_OFF_MIN_MOMENTUM_PCT = 90.0
    REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY = 85.0


def clean_row(symbol="ALPHA", score=82.0, **overrides):
    """A row that clears every Model 5.0 gate; tests break one thing at a time."""
    row = {
        "Symbol": symbol,
        "Combined_Score": score,
        "Research_Score": score,
        "Factor_Model_Applied": True,
        # trend
        "Technical_Price": 120.0,
        "MA50": 110.0,
        "MA200": 100.0,
        "MA200_Slope_Pct": 1.5,
        "Below_MA200_Streak": 0,
        # relative strength
        "RS_Market_6M_Pct": 8.0,
        "RS_Sector_6M_Pct": 4.0,
        "RS_Market_12M_Pct": 15.0,
        # factor percentiles
        "Quality_Percentile": 88.0,
        "Growth_Percentile": 80.0,
        "Momentum_Percentile": 92.0,
        "Quality_Coverage_Sufficient": True,
        "Growth_Coverage_Sufficient": True,
        "Value_Coverage_Sufficient": True,
        "Momentum_Coverage_Sufficient": True,
        "Risk_Coverage_Sufficient": True,
        # shared evidence gates
        "Fundamental_Coverage": 0.90,
        "Technical_Coverage": 0.95,
        "Coverage_Eligible": True,
        "Fundamental_Coverage_Eligible": True,
        "Technical_Coverage_Eligible": True,
        "Data_Quality": "FULL",
        "Fundamental_Model": "Generic Fundamental Model",
        "Specialized_Fundamental_Model_Required": False,
        "Fund_Data_Stale": False,
        "Price_Bar_Aligned": True,
        "Fundamental_Anomaly_Count": 0,
        "Fundamental_Anomaly_Reason": "",
        "Portfolio_Actionable": True,
        "Market_Regime": "RISK_ON",
        "DCF_Blend_Weight": 0.0,
        "DCF_Status": "ok",
    }
    row.update(overrides)
    return row


def finalize(rows):
    return finalize_recommendations(pd.DataFrame(rows), Config)


class ResearchRankConfig(Config):
    """Model 5.1 default: gates rate and label, they do not rank or cap."""

    RANK_BY_ELIGIBILITY_CLASS = False
    APPLY_RATING_CAP = False


class LegacyCapConfig(Config):
    """Model 5.0 behaviour: eligibility ranks first and the cap is enforced."""

    RANK_BY_ELIGIBILITY_CLASS = True
    APPLY_RATING_CAP = True


def finalize_legacy(rows):
    return finalize_recommendations(pd.DataFrame(rows), LegacyCapConfig)


def finalize_research_ranked(rows):
    return finalize_recommendations(pd.DataFrame(rows), ResearchRankConfig)


def failures(frame, symbol):
    row = frame.loc[frame["Symbol"] == symbol].iloc[0]
    return json.loads(row["Gate_Failures"])


class TrendGateTests(unittest.TestCase):
    def test_clean_candidate_reaches_strong_buy(self):
        result = finalize([clean_row()])
        self.assertEqual(result.iloc[0]["Rating"], "STRONG BUY")
        self.assertTrue(bool(result.iloc[0]["Buy_Eligible"]))
        self.assertTrue(bool(result.iloc[0]["Strong_Buy_Eligible"]))
        self.assertEqual(result.iloc[0]["Primary_Gate"], "NONE")

    def test_price_well_below_ma200_fails_buy(self):
        result = finalize([clean_row(Technical_Price=80.0, MA50=85.0)])
        self.assertEqual(result.iloc[0]["Decision_Score_Ceiling"], 59.99)
        self.assertIn(
            "price below MA200 tolerance band (98%)", failures(result, "ALPHA")
        )

    def test_tolerance_band_keeps_a_marginal_dip_eligible(self):
        # 99 against a 100 average is inside the 98% band. An exact boundary
        # would flip this row's rating on a one-rupee move.
        result = finalize([clean_row(Technical_Price=99.0, MA50=99.5)])
        self.assertTrue(bool(result.iloc[0]["Buy_Eligible"]))

    def test_just_outside_the_band_fails(self):
        result = finalize([clean_row(Technical_Price=97.0, MA50=98.0)])
        self.assertFalse(bool(result.iloc[0]["Buy_Eligible"]))

    def test_falling_ma200_fails_buy(self):
        result = finalize([clean_row(MA200_Slope_Pct=-0.4)])
        self.assertIn("MA200 slope falling", failures(result, "ALPHA"))

    def test_missing_ma200_fails_closed(self):
        result = finalize([clean_row(MA200=None, MA200_Slope_Pct=None)])
        gates = failures(result, "ALPHA")
        self.assertIn("price/MA200 unavailable", gates)
        self.assertIn("MA200 slope unavailable", gates)

    def test_confirmed_breakdown_requires_persistence_and_weakness(self):
        # One session below the line is not a breakdown.
        brief = finalize(
            [clean_row(Below_MA200_Streak=1, MA200_Slope_Pct=-0.2,
                       RS_Market_6M_Pct=-1.0)]
        )
        self.assertNotIn(
            "confirmed trend breakdown below MA200", failures(brief, "ALPHA")
        )
        # Persistent, with a falling average and weak relative strength, is.
        confirmed = finalize(
            [clean_row(Below_MA200_Streak=14, MA200_Slope_Pct=-0.2,
                       RS_Market_6M_Pct=-1.0)]
        )
        self.assertIn(
            "confirmed trend breakdown below MA200", failures(confirmed, "ALPHA")
        )

    def test_strong_buy_requires_the_ma50_ma200_stack(self):
        result = finalize([clean_row(MA50=95.0)])  # price > MA200 but MA50 below
        self.assertFalse(bool(result.iloc[0]["Strong_Buy_Eligible"]))
        self.assertIn(
            "price/MA50/MA200 not stacked bullishly", failures(result, "ALPHA")
        )
        self.assertEqual(result.iloc[0]["Decision_Score_Ceiling"], 69.99)


class RelativeStrengthTests(unittest.TestCase):
    def test_negative_market_relative_strength_fails_buy(self):
        result = finalize([clean_row(RS_Market_6M_Pct=-3.0)])
        self.assertIn(
            "6M market relative strength not positive", failures(result, "ALPHA")
        )

    def test_absent_sector_relative_strength_is_not_a_failure(self):
        # Thin sectors legitimately have no peer median; absence must not fail
        # a row the way an observed negative reading does.
        result = finalize([clean_row(RS_Sector_6M_Pct=None)])
        self.assertTrue(bool(result.iloc[0]["Buy_Eligible"]))

    def test_negative_twelve_month_strength_blocks_strong_buy_only(self):
        result = finalize([clean_row(RS_Market_12M_Pct=-5.0)])
        self.assertTrue(bool(result.iloc[0]["Buy_Eligible"]))
        self.assertFalse(bool(result.iloc[0]["Strong_Buy_Eligible"]))


class FactorPercentileTests(unittest.TestCase):
    def test_low_quality_fails_buy(self):
        result = finalize([clean_row(Quality_Percentile=25.0)])
        self.assertIn("quality percentile below BUY floor", failures(result, "ALPHA"))

    def test_mid_quality_blocks_strong_buy_only(self):
        result = finalize([clean_row(Quality_Percentile=55.0)])
        self.assertTrue(bool(result.iloc[0]["Buy_Eligible"]))
        self.assertIn(
            "quality percentile below STRONG BUY floor", failures(result, "ALPHA")
        )

    def test_weak_growth_or_momentum_blocks_strong_buy(self):
        growth = finalize([clean_row(Growth_Percentile=40.0)])
        self.assertFalse(bool(growth.iloc[0]["Strong_Buy_Eligible"]))
        momentum = finalize([clean_row(Momentum_Percentile=50.0)])
        self.assertFalse(bool(momentum.iloc[0]["Strong_Buy_Eligible"]))

    def test_insufficient_block_coverage_fails_buy(self):
        result = finalize([clean_row(Quality_Coverage_Sufficient=False)])
        self.assertIn("quality factor coverage insufficient", failures(result, "ALPHA"))

    def test_model_five_raises_the_buy_coverage_floors(self):
        # 0.60 fundamental coverage passes the 4.x 0.55 floor but not the 0.70
        # Model 5.0 floor, and the 4.x eligibility booleans still say True.
        result = finalize([clean_row(Fundamental_Coverage=0.60)])
        self.assertIn(
            "fundamental coverage insufficient for BUY", failures(result, "ALPHA")
        )


class LiquidityGateTests(unittest.TestCase):
    def test_illiquid_name_cannot_be_published_as_buy(self):
        result = finalize([clean_row(Portfolio_Actionable=False)])
        self.assertIn(
            "insufficient execution liquidity for target size",
            failures(result, "ALPHA"),
        )
        self.assertEqual(result.iloc[0]["Execution_Status"], "NOT_ACTIONABLE")

    def test_research_view_survives_the_liquidity_cap(self):
        result = finalize([clean_row(Portfolio_Actionable=False)])
        row = result.iloc[0]
        # The capped label is separate from the uncapped research read.
        self.assertEqual(row["Policy_Eligible_Rating"], "HOLD")
        self.assertEqual(row["Research_Rating"], "STRONG BUY")


class FinancialSpecialistGateTests(unittest.TestCase):
    """Gross NPA, net NPA, CAR and solvency are required but never collected.

    The practical effect is that every bank, NBFC and insurer is permanently
    barred from BUY. These lock in both sides of that decision so the behaviour
    cannot change silently.
    """

    @staticmethod
    def bank_row(**overrides):
        row = clean_row(
            "BANKCO",
            Fundamental_Model="Bank Equity Quality Model",
            Specialized_Quality_Eligible=False,
            Specialized_Quality_Gate_Reason=(
                "missing specialized quality data: Gross_NPA, Net_NPA, Capital_Adequacy"
            ),
        )
        row.update(overrides)
        return row

    def test_default_keeps_financials_out_of_buy(self):
        result = finalize([self.bank_row()])
        self.assertIn(
            "specialized regulatory coverage insufficient", failures(result, "BANKCO")
        )
        self.assertFalse(bool(result.iloc[0]["Buy_Eligible"]))
        self.assertEqual(result.iloc[0]["Decision_Score_Ceiling"], 59.99)

    def test_opt_in_downgrades_it_to_a_strong_buy_gate(self):
        original = Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT
        Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT = True
        try:
            result = finalize([self.bank_row()])
            # Scored on the statement evidence banks actually report, so BUY is
            # reachable; the regulatory requirement still blocks STRONG BUY.
            self.assertTrue(bool(result.iloc[0]["Buy_Eligible"]))
            self.assertFalse(bool(result.iloc[0]["Strong_Buy_Eligible"]))
            self.assertEqual(result.iloc[0]["Decision_Score_Ceiling"], 69.99)
        finally:
            Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT = original

    def test_opt_in_still_requires_covered_financial_quality(self):
        original = Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT
        Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT = True
        try:
            result = finalize(
                [self.bank_row(Quality_Coverage_Sufficient=False)]
            )
            self.assertFalse(bool(result.iloc[0]["Buy_Eligible"]))
        finally:
            Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT = original

    def test_opt_in_does_not_affect_the_four_x_model(self):
        original = Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT
        Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT = True
        try:
            result = finalize([self.bank_row(Factor_Model_Applied=False)])
            self.assertFalse(bool(result.iloc[0]["Buy_Eligible"]))
        finally:
            Config.FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT = original


class RegimeOverlayTests(unittest.TestCase):
    def test_risk_off_disables_strong_buy(self):
        result = finalize([clean_row(Market_Regime="RISK_OFF")])
        self.assertIn(
            "market regime risk-off: STRONG BUY disabled", failures(result, "ALPHA")
        )

    def test_risk_off_buy_requires_top_decile_momentum(self):
        weak = finalize([clean_row(Market_Regime="RISK_OFF", Momentum_Percentile=75.0)])
        self.assertFalse(bool(weak.iloc[0]["Buy_Eligible"]))
        strong = finalize(
            [clean_row(Market_Regime="RISK_OFF", Momentum_Percentile=95.0)]
        )
        self.assertTrue(bool(strong.iloc[0]["Buy_Eligible"]))

    def test_neutral_regime_requires_exceptional_momentum_for_strong_buy(self):
        result = finalize([clean_row(Market_Regime="NEUTRAL", Momentum_Percentile=75.0)])
        self.assertTrue(bool(result.iloc[0]["Buy_Eligible"]))
        self.assertFalse(bool(result.iloc[0]["Strong_Buy_Eligible"]))
        exceptional = finalize(
            [clean_row(Market_Regime="NEUTRAL", Momentum_Percentile=95.0)]
        )
        self.assertTrue(bool(exceptional.iloc[0]["Strong_Buy_Eligible"]))

    def test_regime_never_edits_the_research_score(self):
        on = finalize([clean_row(Market_Regime="RISK_ON")]).iloc[0]
        off = finalize([clean_row(Market_Regime="RISK_OFF")]).iloc[0]
        self.assertEqual(on["Evidence_Score"], off["Evidence_Score"])
        self.assertEqual(on["Research_Score"], off["Research_Score"])


class EligibilityRankingTests(unittest.TestCase):
    def test_capped_rows_keep_a_real_order_instead_of_alphabetical(self):
        rows = [
            # Two capped candidates with clearly different research merit.
            clean_row("ZEBRA", score=95.0, Portfolio_Actionable=False),
            clean_row("APPLE", score=61.0, Portfolio_Actionable=False),
            # One clean candidate that must outrank both.
            clean_row("MANGO", score=78.0),
        ]
        result = finalize_legacy(rows).sort_values("Investment_Rank")
        self.assertEqual(list(result["Symbol"]), ["MANGO", "ZEBRA", "APPLE"])
        # Both capped rows share the identical 59.99 ceiling, so ranking on
        # Decision_Score alone would have fallen through to the symbol
        # tie-break and put APPLE ahead of ZEBRA on merit it does not have.
        capped = result.loc[result["Symbol"].isin(["ZEBRA", "APPLE"])]
        self.assertEqual(capped["Decision_Score"].nunique(), 1)

    def test_eligibility_class_orders_strong_then_buy_then_capped(self):
        rows = [
            clean_row("STRONGCO", score=88.0),
            clean_row("BUYCO", score=88.0, Growth_Percentile=10.0),
            clean_row("CAPPEDCO", score=88.0, Quality_Percentile=5.0),
        ]
        result = finalize(rows).set_index("Symbol")
        self.assertEqual(result.loc["STRONGCO", "Eligibility_Class"], 0)
        self.assertEqual(result.loc["BUYCO", "Eligibility_Class"], 1)
        self.assertEqual(result.loc["CAPPEDCO", "Eligibility_Class"], 2)

    def test_ranks_are_dense_and_deterministic(self):
        rows = [clean_row(f"SYM{index}", score=70.0 + index) for index in range(6)]
        first = finalize(rows)
        second = finalize(list(reversed(rows)))
        self.assertEqual(sorted(first["Investment_Rank"]), list(range(1, 7)))
        self.assertEqual(
            list(first.sort_values("Investment_Rank")["Symbol"]),
            list(second.sort_values("Investment_Rank")["Symbol"]),
        )

    def test_rank_alias_tracks_investment_rank(self):
        result = finalize([clean_row("A", score=80.0), clean_row("B", score=60.0)])
        self.assertTrue((result["Rank"] == result["Investment_Rank"]).all())


class ResearchRankingTests(unittest.TestCase):
    """Ranking on research merit alone -- the Model 5.1 default.

    Four point-in-time windows found eligibility-first ranking cost 5-16 CAGR
    points wherever the gates bound and contributed nothing in the 2018-2020
    drawdown, where every name failed a gate and the class key was constant.
    """

    def test_a_capped_name_can_outrank_a_clean_one_on_merit(self):
        rows = [
            clean_row("MANGO", score=78.0),
            clean_row("ZEBRA", score=95.0, Portfolio_Actionable=False),
        ]
        result = finalize_research_ranked(rows).sort_values("Investment_Rank")
        self.assertEqual(list(result["Symbol"]), ["ZEBRA", "MANGO"])

    def test_eligibility_first_still_available_behind_the_flag(self):
        """The old policy must stay reachable, not be deleted."""
        rows = [
            clean_row("MANGO", score=78.0),
            clean_row("ZEBRA", score=95.0, Portfolio_Actionable=False),
        ]
        result = finalize(rows).sort_values("Investment_Rank")
        self.assertEqual(list(result["Symbol"]), ["MANGO", "ZEBRA"])

    def test_research_merit_survives_where_the_capped_score_would_not(self):
        """Policy_Capped_Score is constant across a class; sorting it is alphabetical.

        Both rows fail a *policy* gate (quality percentile below the BUY floor),
        so 5.1 publishes their research score. An integrity failure would still
        cap -- see test_an_integrity_failure_still_caps.
        """
        rows = [
            clean_row("ZEBRA", score=95.0, Quality_Percentile=5.0),
            clean_row("APPLE", score=61.0, Quality_Percentile=5.0),
        ]
        result = finalize_research_ranked(rows).sort_values("Investment_Rank")
        # The ceiling both rows would have shared, had it been enforced.
        self.assertEqual(result["Policy_Capped_Score"].nunique(), 1)
        # The published score keeps them apart, and so does the order.
        self.assertEqual(result["Decision_Score"].nunique(), 2)
        self.assertEqual(list(result["Symbol"]), ["ZEBRA", "APPLE"])

    def test_gates_are_still_computed_and_published(self):
        """Turning the gates off for ranking must not stop them being reported."""
        result = finalize_research_ranked(
            [clean_row("CAPPEDCO", score=88.0, Quality_Percentile=5.0)]
        ).iloc[0]
        self.assertEqual(result["Eligibility_Class"], 2)
        self.assertTrue(json.loads(result["Gate_Failures"]))
        self.assertTrue(str(result["Primary_Gate"]))
        # The cap is reported, not applied.
        self.assertEqual(result["Decision_Score"], result["Research_Score"])
        self.assertLess(result["Policy_Capped_Score"], result["Research_Score"])
        self.assertTrue(bool(result["Rating_Capped"]))
        self.assertFalse(bool(result["Cap_Enforced"]))

    def test_a_gated_name_carries_a_warning_naming_the_policy_rating(self):
        """The details page needs one rendered sentence, not raw JSON."""
        result = finalize_research_ranked(
            [clean_row("CAPPEDCO", score=88.0, Quality_Percentile=5.0)]
        ).iloc[0]
        warning = str(result["Gate_Warning"])
        self.assertIn("research merit", warning)
        self.assertIn(str(result["Policy_Eligible_Rating"]), warning)

    def test_a_clean_name_carries_no_warning(self):
        result = finalize_research_ranked([clean_row("CLEANCO", score=88.0)]).iloc[0]
        self.assertEqual(str(result["Gate_Warning"]), "")
        self.assertFalse(bool(result["Rating_Capped"]))

    def test_an_integrity_failure_still_caps(self):
        """Bad evidence is not a research view.

        The archive excludes unscorable names by construction, so the
        point-in-time validation never measured the integrity gates and cannot
        license lifting them. Only the policy gates were relaxed.
        """
        result = finalize_research_ranked(
            [clean_row("THINCO", score=88.0, Portfolio_Actionable=False)]
        ).iloc[0]
        self.assertLess(result["Decision_Score"], result["Research_Score"])
        self.assertTrue(bool(result["Cap_Enforced"]))

    def test_an_unclassified_gate_fails_closed(self):
        """A new gate must cap until someone classifies it."""
        self.assertTrue(is_integrity_gate("some brand new gate nobody classified"))
        self.assertTrue(is_integrity_gate(""))
        self.assertFalse(is_integrity_gate("price below MA200 tolerance band (98%)"))
        self.assertFalse(is_integrity_gate("quality percentile below BUY floor"))
        self.assertTrue(is_integrity_gate("quality percentile unavailable"))

    def test_the_cap_is_restorable_for_a_rollback(self):
        """5.0 behaviour must stay reachable, not be deleted."""
        result = finalize_legacy(
            [clean_row("CAPPEDCO", score=88.0, Quality_Percentile=5.0)]
        ).iloc[0]
        self.assertLess(result["Decision_Score"], result["Research_Score"])
        self.assertTrue(bool(result["Cap_Enforced"]))

    def test_ranks_stay_dense_and_order_independent(self):
        rows = [clean_row(f"SYM{index}", score=70.0 + index) for index in range(6)]
        first = finalize_research_ranked(rows)
        second = finalize_research_ranked(list(reversed(rows)))
        self.assertEqual(sorted(first["Investment_Rank"]), list(range(1, 7)))
        self.assertEqual(
            list(first.sort_values("Investment_Rank")["Symbol"]),
            list(second.sort_values("Investment_Rank")["Symbol"]),
        )


class PrimaryGateTests(unittest.TestCase):
    def test_most_severe_reason_wins(self):
        self.assertEqual(
            primary_gate(["quality percentile below BUY floor", "core score unavailable"]),
            "NO_SCORE",
        )

    def test_no_failures_is_none(self):
        self.assertEqual(primary_gate([]), "NONE")

    def test_unrecognised_reason_is_labelled_other(self):
        self.assertEqual(primary_gate(["something new"]), "OTHER")


class BackwardCompatibilityTests(unittest.TestCase):
    def test_four_x_rows_keep_the_ma50_gates(self):
        # Without Factor_Model_Applied the 4.x policy must be unchanged: this
        # row has a good MA200 stack but a falling MA50, which only 4.x checks.
        row = clean_row(Factor_Model_Applied=False)
        row.update(
            {
                "MA50_Slope_Pct": -2.0,
                "Pct_Change_3M": 5.0,
                "Revenue_Growth": 0.20,
                "Earnings_Growth": 0.20,
                "ADX_14": 30.0,
                "ADX_Plus_DI": 30.0,
                "ADX_Minus_DI": 10.0,
                "Technical_Score": 70.0,
            }
        )
        result = finalize([row])
        self.assertIn("MA50 falling", failures(result, "ALPHA"))
        # And none of the Model 5.0 gates fire.
        self.assertNotIn("MA200 slope falling", failures(result, "ALPHA"))


if __name__ == "__main__":
    unittest.main()
