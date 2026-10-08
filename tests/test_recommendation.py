import json
import unittest
from types import SimpleNamespace

import pandas as pd

from screener.numeric import round_half_up
from screener.recommendation import finalize_recommendations, rating_from_score


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

    def two_sided_frame(self):
        return pd.DataFrame(
            [
                row(
                    symbol,
                    60.0,
                    Transcript_Blend_Eligible=True,
                    Transcript_Blend_Weight=0.10,
                    Transcript_Effective_Score=score,
                )
                for symbol, score in (("WEAK", 55.0), ("MID", 65.0), ("STRONG", 80.0))
            ]
            + [row("NO_CALL", 60.0)]
        )

    def two_sided_config(self, minimum=3):
        settings = config()
        settings.TRANSCRIPT_TWO_SIDED = True
        settings.TRANSCRIPT_NEUTRAL_MIN_CALLS = minimum
        return settings

    def test_two_sided_transcript_is_measured_against_the_median_call(self):
        result = finalize_recommendations(
            self.two_sided_frame(), self.two_sided_config()
        ).set_index("Symbol")

        # 55 is above 50 and still an adverse call: most calls are upbeat, so
        # the reference is the median scored call (65), not the scale midpoint.
        self.assertEqual(result.loc["WEAK", "Evidence_Score"], 59.0)
        self.assertEqual(result.loc["MID", "Evidence_Score"], 60.0)
        self.assertEqual(result.loc["STRONG", "Evidence_Score"], 61.5)
        self.assertEqual(result.loc["STRONG", "Transcript_Applied_Direction"], "upside")
        self.assertEqual(result.loc["STRONG", "Transcript_Neutral_Score"], 65.0)

    def test_two_sided_transcript_leaves_a_company_without_a_call_alone(self):
        result = finalize_recommendations(
            self.two_sided_frame(), self.two_sided_config()
        ).set_index("Symbol")

        self.assertEqual(result.loc["NO_CALL", "Evidence_Score"], 60.0)
        self.assertEqual(result.loc["NO_CALL", "Transcript_Evidence_Contribution"], 0.0)

    def factor_ranking(self, rows):
        settings = self.two_sided_config()
        settings.FACTOR_MODEL_ENABLED = True
        frame = pd.DataFrame(
            [
                row(
                    symbol,
                    score,
                    Factor_Model_Applied=True,
                    Research_Score=score,
                    **(
                        {
                            "Transcript_Blend_Eligible": True,
                            "Transcript_Blend_Weight": 0.10,
                            "Transcript_Effective_Score": call,
                        }
                        if call is not None
                        else {}
                    ),
                )
                for symbol, score, call in rows
            ]
        )
        return finalize_recommendations(frame, settings).set_index("Symbol")

    def test_the_rank_follows_the_published_score_not_the_research_score(self):
        # Median call 65. LIFTED's call adds 2.0 and SUNK's takes 2.0 away, so
        # each crosses NO_CALL, whose score no call touched.
        result = self.factor_ranking(
            [("SUNK", 71.0, 45.0), ("NO_CALL", 70.0, None), ("LIFTED", 69.0, 85.0), ("MID", 50.0, 65.0)]
        )

        self.assertEqual(result.loc["LIFTED", "Evidence_Score"], 71.0)
        self.assertEqual(result.loc["SUNK", "Evidence_Score"], 69.0)
        self.assertEqual(
            result["Investment_Rank"].sort_values().index.tolist(),
            ["LIFTED", "NO_CALL", "SUNK", "MID"],
        )
        self.assertEqual(result["Rank"].tolist(), result["Investment_Rank"].tolist())

    def test_names_lifted_to_the_ceiling_are_ordered_by_research_score(self):
        # Both calls push past 100 and are clipped there; the tie must not
        # fall through to the alphabet.
        result = self.factor_ranking(
            [("AAA", 98.5, 95.0), ("ZZZ", 99.5, 95.0)]
            + [(f"MID{n}", 50.0 - n, 65.0) for n in range(3)]
        )

        self.assertEqual(result.loc["AAA", "Evidence_Score"], 100.0)
        self.assertEqual(result.loc["ZZZ", "Evidence_Score"], 100.0)
        self.assertEqual(result.loc["ZZZ", "Investment_Rank"], 1)
        self.assertEqual(result.loc["AAA", "Investment_Rank"], 2)

    def test_two_sided_transcript_falls_back_to_fifty_on_a_thin_run(self):
        result = finalize_recommendations(
            self.two_sided_frame(), self.two_sided_config(minimum=30)
        ).set_index("Symbol")

        self.assertEqual(result.loc["WEAK", "Transcript_Neutral_Score"], 50.0)
        self.assertEqual(result.loc["WEAK", "Evidence_Score"], 60.5)

    def outlook_frame(self):
        # Tone median 65 (55, 60, 70, 80); outlook median 60 (50, 60, 70).
        calls = (
            ("WEAK_TONE_GOOD_OUTLOOK", 55.0, 70.0),
            ("BOTH_WEAK", 60.0, 50.0),
            ("STRONG_TONE", 80.0, 60.0),
            ("TONE_ONLY", 70.0, None),
        )
        return pd.DataFrame(
            [
                row(
                    symbol,
                    60.0,
                    Transcript_Blend_Eligible=True,
                    Transcript_Blend_Weight=0.10,
                    Transcript_Effective_Score=tone,
                    Transcript_Outlook_Score=outlook,
                )
                for symbol, tone, outlook in calls
            ]
            + [row("NO_CALL", 60.0, Transcript_Outlook_Score=90.0)]
        )

    def outlook_config(self, share=0.5):
        settings = self.two_sided_config()
        settings.TRANSCRIPT_OUTLOOK_SHARE = share
        return settings

    def test_outlook_shares_the_transcript_weight_with_tone(self):
        result = finalize_recommendations(
            self.outlook_frame(), self.outlook_config()
        ).set_index("Symbol")

        # 0.10 * (0.5 * (tone - 65) + 0.5 * (outlook - 60))
        self.assertEqual(result.loc["WEAK_TONE_GOOD_OUTLOOK", "Evidence_Score"], 60.0)
        self.assertEqual(result.loc["BOTH_WEAK", "Evidence_Score"], 59.25)
        self.assertEqual(result.loc["STRONG_TONE", "Evidence_Score"], 60.75)
        self.assertEqual(result.loc["STRONG_TONE", "Transcript_Outlook_Neutral_Score"], 60.0)
        self.assertEqual(result.loc["BOTH_WEAK", "Transcript_Outlook_Score_Used"], 50.0)
        self.assertEqual(result.loc["BOTH_WEAK", "Transcript_Outlook_Share_Applied"], 0.5)

    def test_a_call_without_an_outlook_keeps_the_whole_weight_on_tone(self):
        result = finalize_recommendations(
            self.outlook_frame(), self.outlook_config()
        ).set_index("Symbol")

        self.assertFalse(result.loc["TONE_ONLY", "Transcript_Outlook_Applied"])
        self.assertEqual(result.loc["TONE_ONLY", "Evidence_Score"], 60.5)

    def test_an_outlook_without_an_eligible_call_changes_nothing(self):
        result = finalize_recommendations(
            self.outlook_frame(), self.outlook_config()
        ).set_index("Symbol")

        self.assertFalse(result.loc["NO_CALL", "Transcript_Outlook_Applied"])
        self.assertEqual(result.loc["NO_CALL", "Evidence_Score"], 60.0)

    def test_a_zero_outlook_share_is_the_tone_only_policy(self):
        with_outlooks = finalize_recommendations(
            self.outlook_frame(), self.outlook_config(share=0.0)
        ).set_index("Symbol")
        without = finalize_recommendations(
            self.outlook_frame().drop(columns="Transcript_Outlook_Score"),
            self.two_sided_config(),
        ).set_index("Symbol")

        self.assertEqual(
            with_outlooks["Evidence_Score"].tolist(), without["Evidence_Score"].tolist()
        )
        self.assertEqual(with_outlooks.loc["WEAK_TONE_GOOD_OUTLOOK", "Evidence_Score"], 59.0)

    def test_outlook_falls_back_to_fifty_when_few_calls_have_one(self):
        settings = self.outlook_config()
        settings.TRANSCRIPT_NEUTRAL_MIN_CALLS = 4
        result = finalize_recommendations(self.outlook_frame(), settings).set_index("Symbol")

        # Four tone scores keep the tone median; three outlooks are too few.
        self.assertEqual(result.loc["BOTH_WEAK", "Transcript_Neutral_Score"], 65.0)
        self.assertEqual(result.loc["BOTH_WEAK", "Transcript_Outlook_Neutral_Score"], 50.0)
        self.assertEqual(result.loc["BOTH_WEAK", "Evidence_Score"], 59.75)

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

    def test_factor_eligibility_ranking_does_not_leak_into_four_x(self):
        settings = config()
        settings.FACTOR_MODEL_ENABLED = False
        # This secondary setting defaults on for Model 5.0, but the master
        # switch must keep it from changing a 4.x production run.
        settings.RANK_BY_ELIGIBILITY_CLASS = True
        source = pd.DataFrame(
            [
                row("LOW_CLEAR", 45.0),
                row(
                    "HIGH_BUY_ONLY",
                    80.0,
                    Revenue_Growth=0.0,
                    Earnings_Growth=0.0,
                ),
            ]
        )

        result = finalize_recommendations(source, settings).set_index("Symbol")

        self.assertEqual(result.loc["HIGH_BUY_ONLY", "Rating"], "BUY")
        self.assertEqual(result.loc["LOW_CLEAR", "Rating"], "REDUCE")
        self.assertEqual(result.loc["HIGH_BUY_ONLY", "Investment_Rank"], 1)
        self.assertEqual(result.loc["LOW_CLEAR", "Investment_Rank"], 2)

    def test_factor_eligibility_ranking_requires_factor_rows(self):
        settings = config()
        settings.FACTOR_MODEL_ENABLED = True
        settings.RANK_BY_ELIGIBILITY_CLASS = True
        source = pd.DataFrame(
            [
                row("LOW_CLEAR", 45.0, Factor_Model_Applied=False),
                row(
                    "HIGH_BUY_ONLY",
                    80.0,
                    Factor_Model_Applied=False,
                    Revenue_Growth=0.0,
                    Earnings_Growth=0.0,
                ),
            ]
        )

        result = finalize_recommendations(source, settings).set_index("Symbol")

        self.assertEqual(result.loc["HIGH_BUY_ONLY", "Investment_Rank"], 1)
        self.assertEqual(result.loc["LOW_CLEAR", "Investment_Rank"], 2)

    def test_final_policy_refreshes_investment_rating_alias(self):
        source = pd.DataFrame(
            [row("ALPHA", 65.0, Investment_Rating="")]
        )

        result = finalize_recommendations(source, config()).iloc[0]

        self.assertEqual(result["Rating"], "BUY")
        self.assertEqual(result["Investment_Rating"], result["Rating"])

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
