import json
import unittest
from types import SimpleNamespace

import pandas as pd

from screener.recommendation import finalize_recommendations, rating_from_score
from screener.numeric import round_half_up


def config():
    return SimpleNamespace(
        REVERSE_DCF_RANKING_WEIGHT=0.10,
        TRANSCRIPT_SENTIMENT_WEIGHT=0.15,
        REQUIRE_FUND_DATA_FOR_BUY=True,
        REQUIRE_UPTREND_FOR_BUY=True,
        BUY_MIN_MA50_SLOPE=0.0,
        BUY_MIN_3M_RETURN=0.0,
        STRONG_BUY_MIN_GROWTH=0.05,
        STRONG_BUY_MIN_TECH_SCORE=55.0,
        STRONG_BUY_MIN_ADX=20.0,
        FUNDAMENTAL_MIN_COVERAGE_FOR_STRONG_BUY=0.75,
        TECHNICAL_MIN_COVERAGE_FOR_STRONG_BUY=0.90,
        REQUIRE_TRANSCRIPT_FOR_STRONG_BUY=False,
        CAP_STRONG_BUY_ON_REPORTED_NEGATIVE_FCF=True,
    )


def row(symbol="ROW", score=65.0, **overrides):
    values = {
        "Symbol": symbol,
        "Combined_Score": score,
        "Current_Price": 110.0,
        "Technical_Price": 110.0,
        "MA50": 100.0,
        "MA50_Slope_Pct": 1.0,
        "Pct_Change_3M": 5.0,
        "Revenue_Growth": 0.10,
        "Earnings_Growth": 0.10,
        "ADX_14": 25.0,
        "ADX_Plus_DI": 20.0,
        "ADX_Minus_DI": 10.0,
        "Technical_Score": 65.0,
        "Data_Quality": "FULL",
        "Fund_Data_Stale": False,
        "Fundamental_Anomaly": False,
        "Fundamental_Anomaly_Reason": "",
        "Specialized_Fundamental_Model_Required": False,
        "Specialized_Quality_Eligible": True,
        "Fundamental_Model": "Generic Fundamental Model",
        "Coverage_Eligible": True,
        "Fundamental_Coverage_Eligible": True,
        "Technical_Coverage_Eligible": True,
        "Fundamental_Coverage": 1.0,
        "Technical_Coverage": 1.0,
        "DCF_Blend_Eligible": False,
        "DCF_Blend_Weight": 0.0,
        "DCF_Valuation_Score": 50.0,
        "Transcript_Blend_Eligible": False,
        "Transcript_Blend_Weight": 0.0,
        "Transcript_Effective_Score": None,
        "Transcript_Downside_Applied": False,
        "Transcript_Priority_Applied": False,
    }
    if "Current_Price" in overrides and "Technical_Price" not in overrides:
        overrides["Technical_Price"] = overrides["Current_Price"]
    values.update(overrides)
    return values


class RecommendationPolicyTests(unittest.TestCase):
    def test_score_rounding_is_explicit_decimal_half_up(self):
        self.assertEqual(round_half_up(69.545, 2), 69.55)
        self.assertEqual(round_half_up(69.455, 2), 69.46)

    def test_dcf_cannot_resurrect_buy_when_trend_gate_fails(self):
        source = pd.DataFrame(
            [
                row(
                    score=58.0,
                    Current_Price=90.0,
                    MA50=100.0,
                    DCF_Blend_Eligible=True,
                    DCF_Blend_Weight=0.10,
                    DCF_Valuation_Score=100.0,
                )
            ]
        )

        result = finalize_recommendations(source, config()).iloc[0]

        self.assertEqual(result["Evidence_Score"], 63.0)
        self.assertEqual(result["Evidence_Rating"], "BUY")
        self.assertEqual(result["Decision_Score"], 59.99)
        self.assertEqual(result["Rating"], "HOLD")
        self.assertFalse(result["Buy_Eligible"])
        self.assertIn("price not above MA50", json.loads(result["Buy_Gate_Failures"]))

    def test_price_gate_uses_adjusted_technical_scale_not_raw_display_price(self):
        source = pd.DataFrame(
            [
                row(
                    score=65.0,
                    Current_Price=220.0,
                    Technical_Price=90.0,
                    MA50=100.0,
                )
            ]
        )

        result = finalize_recommendations(source, config()).iloc[0]

        self.assertFalse(result["Buy_Eligible"])
        self.assertIn("price not above MA50", json.loads(result["Buy_Gate_Failures"]))
        self.assertEqual(result["Buy_Price_MA50_Margin_Pct"], -10.0)

    def test_every_simultaneous_gate_failure_is_exported(self):
        source = pd.DataFrame(
            [
                row(
                    score=80.0,
                    Current_Price=90.0,
                    MA50=100.0,
                    MA50_Slope_Pct=-1.0,
                    Pct_Change_3M=-2.0,
                    Revenue_Growth=0.0,
                    Earnings_Growth=0.0,
                    ADX_14=10.0,
                    ADX_Plus_DI=5.0,
                    ADX_Minus_DI=10.0,
                    Technical_Score=40.0,
                    Fundamental_Coverage=0.70,
                    Technical_Coverage=0.80,
                )
            ]
        )

        result = finalize_recommendations(source, config()).iloc[0]
        failures = set(json.loads(result["Strong_Buy_Gate_Failures"]))

        expected = {
            "price not above MA50",
            "MA50 falling",
            "3M return not positive",
            "growth below threshold",
            "ADX below threshold",
            "positive DI not above negative DI",
            "technical score below threshold",
            "fundamental coverage below STRONG BUY threshold",
            "technical coverage below STRONG BUY threshold",
        }
        self.assertTrue(expected.issubset(failures))
        self.assertEqual(result["Strong_Buy_Gate_Failure_Count"], len(failures))
        self.assertEqual(result["Decision_Score"], 59.99)
        self.assertEqual(result["Rating"], "HOLD")

    def test_gate_margins_and_borderline_reasons_are_exported(self):
        source = pd.DataFrame(
            [
                row(
                    score=70.4,
                    ADX_14=19.5,
                    MA50_Slope_Pct=0.1,
                    Pct_Change_3M=0.5,
                    Revenue_Growth=0.055,
                    Earnings_Growth=0.055,
                )
            ]
        )

        result = finalize_recommendations(source, config()).iloc[0]
        reasons = set(json.loads(result["Gate_Borderline_Reasons"]))

        self.assertEqual(result["Strong_Buy_ADX_Margin"], -0.5)
        self.assertEqual(result["Buy_MA50_Slope_Margin_Pct"], 0.1)
        self.assertEqual(result["Buy_3M_Return_Margin_Pct"], 0.5)
        self.assertEqual(result["Strong_Buy_Growth_Margin_Ratio"], 0.005)
        self.assertTrue(result["Gate_Borderline"])
        self.assertEqual(result["Decision_Stability_Status"], "BORDERLINE")
        self.assertTrue({"ADX", "MA50 slope", "3M return", "growth"}.issubset(reasons))

    def test_required_coverage_caps_decision_at_hold(self):
        source = pd.DataFrame(
            [
                row(
                    score=85.0,
                    Coverage_Eligible=False,
                    Fundamental_Coverage_Eligible=False,
                    Technical_Coverage_Eligible=False,
                )
            ]
        )

        result = finalize_recommendations(source, config()).iloc[0]
        failures = set(json.loads(result["Buy_Gate_Failures"]))

        self.assertEqual(result["Decision_Score"], 59.99)
        self.assertEqual(result["Rating"], "HOLD")
        self.assertIn("overall required coverage insufficient", failures)
        self.assertIn("fundamental required coverage insufficient", failures)
        self.assertIn("technical required coverage insufficient", failures)

    def test_missing_specialized_regulatory_coverage_caps_at_hold(self):
        source = pd.DataFrame(
            [
                row(
                    score=80.0,
                    Fundamental_Model="Bank Equity Quality Model",
                    Specialized_Quality_Eligible=False,
                    Specialized_Quality_Gate_Reason="missing Gross_NPA, Net_NPA",
                )
            ]
        )

        result = finalize_recommendations(source, config()).iloc[0]

        self.assertEqual(result["Rating"], "HOLD")
        self.assertIn(
            "specialized regulatory coverage insufficient",
            json.loads(result["Buy_Gate_Failures"]),
        )

    def test_reported_negative_fcf_caps_only_strong_buy_conviction(self):
        source = pd.DataFrame(
            [
                row(
                    score=78.0,
                    DCF_Source_Type="observed_negative",
                    DCF_Status="negative_fcf",
                )
            ]
        )

        result = finalize_recommendations(source, config()).iloc[0]

        self.assertTrue(result["Buy_Eligible"])
        self.assertFalse(result["Strong_Buy_Eligible"])
        self.assertEqual(result["Rating"], "BUY")
        self.assertEqual(result["Decision_Score"], 69.99)
        self.assertIn(
            "reported non-positive FCF requires normalization review",
            json.loads(result["Strong_Buy_Gate_Failures"]),
        )

    def test_only_eligible_dcf_evidence_changes_score(self):
        source = pd.DataFrame(
            [
                row(
                    "ADVERSE",
                    80.0,
                    DCF_Blend_Eligible=True,
                    DCF_Blend_Weight=0.10,
                    DCF_Valuation_Score=10.0,
                ),
                row(
                    "ESTIMATED",
                    80.0,
                    DCF_Blend_Eligible=False,
                    DCF_Blend_Weight=0.0,
                    DCF_Valuation_Score=100.0,
                ),
            ]
        )

        result = finalize_recommendations(source, config()).set_index("Symbol")

        self.assertEqual(result.loc["ADVERSE", "Evidence_Score"], 76.0)
        self.assertEqual(result.loc["ESTIMATED", "Evidence_Score"], 80.0)
        self.assertTrue(result.loc["ADVERSE", "DCF_Blend_Applied"])
        self.assertFalse(result.loc["ESTIMATED", "DCF_Blend_Applied"])

    def test_transcript_is_applied_after_dcf_and_is_downside_only(self):
        source = pd.DataFrame(
            [
                row(
                    "NEGATIVE",
                    60.0,
                    DCF_Blend_Eligible=True,
                    DCF_Blend_Weight=0.10,
                    DCF_Valuation_Score=100.0,
                    Transcript_Blend_Eligible=True,
                    Transcript_Blend_Weight=0.15,
                    Transcript_Effective_Score=40.0,
                    Transcript_Downside_Applied=True,
                ),
                row(
                    "POSITIVE_BUT_NOT_PROMOTIONAL",
                    60.0,
                    Transcript_Blend_Eligible=True,
                    Transcript_Blend_Weight=0.15,
                    Transcript_Effective_Score=90.0,
                    Transcript_Downside_Applied=False,
                    Transcript_Priority_Applied=False,
                ),
            ]
        )

        result = finalize_recommendations(source, config()).set_index("Symbol")

        self.assertEqual(result.loc["NEGATIVE", "Score_After_DCF"], 65.0)
        self.assertEqual(result.loc["NEGATIVE", "Evidence_Score"], 63.5)
        self.assertLessEqual(
            result.loc["NEGATIVE", "Transcript_Effective_Score_Used"],
            result.loc["NEGATIVE", "Score_After_DCF"],
        )
        self.assertEqual(
            result.loc["POSITIVE_BUT_NOT_PROMOTIONAL", "Evidence_Score"],
            60.0,
        )
        self.assertEqual(
            result.loc[
                "POSITIVE_BUT_NOT_PROMOTIONAL", "Transcript_Evidence_Contribution"
            ],
            0.0,
        )

    def test_downside_policy_overrides_promotional_evidence(self):
        source = pd.DataFrame(
            [
                row(
                    score=60.0,
                    Transcript_Blend_Eligible=True,
                    Transcript_Blend_Weight=0.15,
                    Transcript_Effective_Score=90.0,
                    Transcript_Promotion_Eligible=True,
                )
            ]
        )

        result = finalize_recommendations(source, config()).iloc[0]

        self.assertEqual(result["Evidence_Score"], 60.0)
        self.assertEqual(result["Decision_Score"], 60.0)

    def test_dcf_neutral_is_noop_and_direction_matches_contribution(self):
        source = pd.DataFrame(
            [
                row(
                    "NEUTRAL",
                    75.0,
                    DCF_Blend_Eligible=True,
                    DCF_Blend_Weight=0.10,
                    DCF_Valuation_Score=50.0,
                ),
                row(
                    "FAVORABLE",
                    75.0,
                    DCF_Blend_Eligible=True,
                    DCF_Blend_Weight=0.10,
                    DCF_Valuation_Score=80.0,
                ),
                row(
                    "ADVERSE",
                    75.0,
                    DCF_Blend_Eligible=True,
                    DCF_Blend_Weight=0.10,
                    DCF_Valuation_Score=20.0,
                ),
            ]
        )

        result = finalize_recommendations(source, config()).set_index("Symbol")

        self.assertEqual(result.loc["NEUTRAL", "DCF_Evidence_Contribution"], 0.0)
        self.assertEqual(result.loc["FAVORABLE", "DCF_Evidence_Contribution"], 3.0)
        self.assertEqual(result.loc["ADVERSE", "DCF_Evidence_Contribution"], -3.0)

    def test_primary_rank_is_decision_score_first_and_other_ranks_are_retained(self):
        source = pd.DataFrame(
            [
                row("HIGH_EVIDENCE_CAPPED", 80.0, Coverage_Eligible=False),
                row("STRONG", 72.0),
                row("BUY", 65.0),
            ]
        )

        result = finalize_recommendations(source, config()).set_index("Symbol")

        self.assertEqual(result.loc["HIGH_EVIDENCE_CAPPED", "Score_Rank"], 1)
        self.assertEqual(result.loc["STRONG", "Investment_Rank"], 1)
        self.assertEqual(result.loc["BUY", "Investment_Rank"], 2)
        self.assertEqual(result.loc["HIGH_EVIDENCE_CAPPED", "Investment_Rank"], 3)
        self.assertEqual(result.loc["STRONG", "Recommendation_Rank"], 1)

    def test_finalizer_is_pure_and_deterministic(self):
        source = pd.DataFrame([row("A", 70.0), row("B", 65.0)])
        original = source.copy(deep=True)

        first = finalize_recommendations(source, config())
        second = finalize_recommendations(source, config())
        retried = finalize_recommendations(first, config())

        pd.testing.assert_frame_equal(source, original)
        pd.testing.assert_frame_equal(first, second)
        pd.testing.assert_frame_equal(first, retried)

    def test_gate_caps_hold_for_a_range_of_overlay_scores(self):
        for core_score in range(50, 60):
            for dcf_score in (60.0, 80.0, 100.0):
                with self.subTest(core_score=core_score, dcf_score=dcf_score):
                    source = pd.DataFrame(
                        [
                            row(
                                score=float(core_score),
                                Current_Price=90.0,
                                MA50=100.0,
                                DCF_Blend_Eligible=True,
                                DCF_Blend_Weight=0.50,
                                DCF_Valuation_Score=dcf_score,
                            )
                        ]
                    )
                    result = finalize_recommendations(source, config()).iloc[0]
                    self.assertLessEqual(result["Decision_Score"], 59.99)
                    self.assertNotIn(result["Rating"], {"BUY", "STRONG BUY"})

    def test_rating_thresholds_match_decision_score(self):
        expected = {
            70.0: "STRONG BUY",
            69.99: "BUY",
            60.0: "BUY",
            59.99: "HOLD",
            50.0: "HOLD",
            49.99: "REDUCE",
            40.0: "REDUCE",
            39.99: "SELL",
        }
        for score, rating in expected.items():
            with self.subTest(score=score):
                self.assertEqual(rating_from_score(score), rating)


if __name__ == "__main__":
    unittest.main()
