import json
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from app import EmailReporter
from scoring.transcript_enricher import TranscriptSentimentEnricher, rank_by_transcript_priority, recency_weight
from transcripts.periods import latest_expected_reporting_period


class FakeRepository:
    def latest_sentiments(self, symbols):
        return [{
            "symbol": "RELIANCE",
            "call_date": str(date.today() - timedelta(days=31)),
            "overall_score": 80,
            "risk_score": 20,
            "management_confidence": 85,
            "guidance_direction": "maintained",
            "optimism_qoq_delta": 10,
            "uncertainty_qoq_delta": -0.03,
            "previous_guidance_direction": "raised",
        }]


class UnclearGuidanceRepository:
    def latest_sentiments(self, symbols):
        return [{
            "symbol": "RELIANCE",
            "call_date": str(date.today()),
            "overall_score": 68,
            "risk_score": 42,
            "management_confidence": 72,
            "guidance_direction": "unclear",
            "optimism_qoq_delta": 4,
            "structured_output": {
                "revenue_outlook": "positive",
                "margin_outlook": "negative",
                "demand_outlook": "positive",
                "catalysts": ["Demand remained strong across core markets."],
                "risks": ["Margins remain under pressure from input costs."],
            },
        }]


class NegativeGuidanceRepository:
    def latest_sentiments(self, symbols):
        return [{
            "symbol": "RELIANCE",
            "call_date": str(date.today()),
            "overall_score": 40,
            "risk_score": 75,
            "management_confidence": 35,
            "guidance_direction": "lowered",
        }]


class PriorCycleRepository:
    def latest_sentiments(self, symbols):
        expected = latest_expected_reporting_period(date.today())
        return [{
            "symbol": "RELIANCE",
            "call_date": str(expected - timedelta(days=1)),
            "overall_score": 95,
            "risk_score": 5,
            "management_confidence": 95,
            "guidance_direction": "raised",
        }]


class OutlookRepository(FakeRepository):
    """FakeRepository's call, with a language-model outlook stored beside it."""

    def __init__(self, days_ago=31, verified_fields=3, previous=None):
        self.outlook = {
            "symbol": "RELIANCE",
            "call_date": str(date.today() - timedelta(days=days_ago)),
            "outlook_score": 73.0,
            "verified_fields": verified_fields,
            "extraction": {
                "guidance": {
                    "direction": "maintained", "metric": "revenue", "growth_pct": 15.0,
                    "quote": "We   maintain our guidance of 15% revenue\ngrowth for the year.",
                },
                "order_book": {"value_inr_crore": None, "revenue_cover_years": None, "trend": "unknown", "quote": None},
                "capacity": {"state": "none", "commissioning": None, "quote": None},
                "demand": {"tone": "strong", "quote": "Demand remains strong across our markets."},
                "margin": {"trend": "flat", "quote": "Margins should hold at these levels."},
                "tailwinds": [],
                "headwinds": [{"what": "input costs", "quote": "x" * 600}],
                "points": [
                    {"reason": "guidance raised", "points": 15.0},
                    {"reason": "demand outlook strong", "points": 8.0},
                    {"reason": "headwind: input costs", "points": -3.0},
                    {"reason": "guidance maintained", "points": 0},
                ],
            },
            "previous": previous,
        }
        self.requested = None

    def latest_outlooks(self, symbols, analysis_version, model_name=None):
        self.requested = (symbols, analysis_version, model_name)
        return [self.outlook]


class TranscriptEnricherTests(unittest.TestCase):
    def test_recency_weight_matches_policy_boundaries(self):
        today = date(2026, 8, 5)
        self.assertEqual(recency_weight("2026-08-05", today), 1.0)
        self.assertAlmostEqual(recency_weight("2026-07-06", today), 0.793701, places=6)
        self.assertEqual(recency_weight("2026-05-07", today), 0.5)
        self.assertEqual(recency_weight("2026-02-06", today), 0.25)
        self.assertEqual(recency_weight("2026-02-05", today), 0.0)

    def test_enrichment_prioritizes_fetched_fresh_sentiment(self):
        source = pd.DataFrame({
            "Symbol": ["RELIANCE", "TCS"],
            "Combined_Score": [72.0, 65.0],
            "Final_Score": [72.0, 65.0],
            "Rating": ["BUY", "BUY"],
            "Technical_Score": [65.0, 65.0],
            "Trend_Confirmed": [True, True],
        })
        config = SimpleNamespace()

        result = TranscriptSentimentEnricher(config, FakeRepository()).enrich(source)

        self.assertEqual(result["Combined_Score"].tolist(), [72.0, 65.0])
        self.assertEqual(result.loc[0, "Transcript_Status"], "Available")
        self.assertEqual(result.loc[0, "Transcript_Weighted_Score"], 73.63)
        self.assertEqual(result.loc[0, "Final_Score"], 72.0)
        self.assertEqual(result.loc[0, "Rating"], "BUY")
        self.assertEqual(result.loc[0, "Transcript_Uncertainty_QoQ_Delta"], -0.03)
        self.assertEqual(result.loc[0, "Transcript_Previous_Guidance"], "raised")
        self.assertFalse(result.loc[0, "Transcript_Priority_Applied"])
        self.assertTrue(result.loc[0, "Transcript_Blend_Eligible"])
        expected_weight = 0.15 * recency_weight(
            str(date.today() - timedelta(days=31))
        )
        self.assertAlmostEqual(
            result.loc[0, "Transcript_Blend_Weight"], expected_weight, places=6
        )
        self.assertEqual(result.loc[0, "Transcript_Signal_Direction"], "neutral")
        self.assertEqual(result.loc[0, "Transcript_Tone_Direction"], "positive")
        self.assertEqual(result.loc[0, "Transcript_Summary"].split(" | ")[:2], ["80.0", "Maintained"])
        self.assertEqual(result.loc[1, "Transcript_Status"], "No transcript")
        self.assertEqual(result.loc[1, "Final_Score"], 65.0)
        self.assertFalse(result.loc[1, "Transcript_Priority_Applied"])
        ranked = rank_by_transcript_priority(result)
        self.assertEqual(ranked["Symbol"].tolist(), ["RELIANCE", "TCS"])
        self.assertEqual(ranked["Rank"].tolist(), [1, 2])

    def test_legacy_rank_helper_is_score_first_not_rating_first(self):
        source = pd.DataFrame({
            "Symbol": ["NO_TRANSCRIPT_BUY", "TRANSCRIPT_BUY", "TRANSCRIPT_REDUCE", "STRONG_BUY"],
            "Final_Score": [85.0, 70.0, 95.0, 72.0],
            "Rating": ["BUY", "BUY", "REDUCE", "STRONG BUY"],
            "Transcript_Priority_Applied": [False, True, True, False],
        })

        ranked = rank_by_transcript_priority(source)

        self.assertEqual(ranked["Symbol"].tolist(), [
            "TRANSCRIPT_REDUCE",
            "NO_TRANSCRIPT_BUY",
            "STRONG_BUY",
            "TRANSCRIPT_BUY",
        ])

    def test_transcript_confirmation_breaks_only_an_exact_score_tie(self):
        source = pd.DataFrame({
            "Symbol": ["A_NO_CALL", "Z_CONFIRMED"],
            "Final_Score": [70.0, 70.0],
            "Rating": ["STRONG BUY", "STRONG BUY"],
            "Transcript_Priority_Applied": [False, True],
        })

        ranked = rank_by_transcript_priority(source)

        self.assertEqual(ranked["Symbol"].tolist(), ["A_NO_CALL", "Z_CONFIRMED"])

    def test_missing_transcript_remains_neutral_even_if_legacy_flag_is_set(self):
        source = pd.DataFrame({
            "Symbol": ["TCS"],
            "Combined_Score": [75.0],
            "Final_Score": [75.0],
            "Rating": ["STRONG BUY"],
            "Technical_Score": [70.0],
            "Trend_Confirmed": [True],
            "Strong_Buy_Eligible": [True],
        })

        result = TranscriptSentimentEnricher(
            SimpleNamespace(REQUIRE_TRANSCRIPT_FOR_STRONG_BUY=True), FakeRepository()
        ).enrich(source)

        self.assertEqual(result.loc[0, "Rating"], "STRONG BUY")
        self.assertFalse(result.loc[0, "Transcript_Strong_Buy_Capped"])
        self.assertFalse(result.loc[0, "Transcript_Blend_Eligible"])

    def test_missing_transcript_is_neutral_by_default(self):
        source = pd.DataFrame({
            "Symbol": ["TCS"],
            "Final_Score": [75.0],
            "Rating": ["STRONG BUY"],
            "Technical_Score": [70.0],
            "Trend_Confirmed": [True],
            "Strong_Buy_Eligible": [True],
        })

        result = TranscriptSentimentEnricher(SimpleNamespace(), FakeRepository()).enrich(source)

        self.assertEqual(result.loc[0, "Rating"], "STRONG BUY")
        self.assertEqual(result.loc[0, "Final_Score"], 75.0)
        self.assertEqual(result.loc[0, "Management_Evidence_Path"], "No transcript; base model retained")
        self.assertFalse(result.loc[0, "Transcript_Strong_Buy_Capped"])

    def test_prior_cycle_transcript_is_visible_but_cannot_change_scoring(self):
        source = pd.DataFrame({
            "Symbol": ["RELIANCE"],
            "Final_Score": [62.0],
            "Rating": ["BUY"],
            "Technical_Score": [80.0],
            "Trend_Confirmed": [True],
        })

        result = TranscriptSentimentEnricher(SimpleNamespace(), PriorCycleRepository()).enrich(source)

        self.assertEqual(result.loc[0, "Transcript_Status"], "Prior-cycle")
        self.assertEqual(result.loc[0, "Transcript_Evidence_Status"], "Prior cycle")
        self.assertTrue(result.loc[0, "Transcript_Fallback_Used"])
        self.assertFalse(result.loc[0, "Transcript_Scoring_Eligible"])
        self.assertEqual(result.loc[0, "Final_Score"], 62.0)
        self.assertEqual(result.loc[0, "Rating"], "BUY")
        self.assertIn("Prior-cycle evidence", result.loc[0, "Transcript_Summary"])

    def test_limited_technical_score_cannot_promote_core_rating(self):
        source = pd.DataFrame({
            "Symbol": ["RELIANCE"],
            "Combined_Score": [65.0],
            "Final_Score": [65.0],
            "Rating": ["BUY"],
            "Technical_Score": [50.0],
            "Trend_Confirmed": [True],
        })

        result = TranscriptSentimentEnricher(SimpleNamespace(), FakeRepository()).enrich(source)

        self.assertEqual(result.loc[0, "Final_Score"], 65.0)
        self.assertEqual(result.loc[0, "Rating"], "BUY")
        self.assertFalse(result.loc[0, "Transcript_Priority_Applied"])
        self.assertTrue(result.loc[0, "Transcript_Blend_Eligible"])
        self.assertEqual(result.loc[0, "Transcript_Proposed_Delta_Core"], 0.0)
        self.assertEqual(result.loc[0, "Transcript_Technical_Gate"], "Downside-only evidence; finalized centrally")

    def test_unconfirmed_trend_prevents_sentiment_uplift_without_availability_penalty(self):
        source = pd.DataFrame({
            "Symbol": ["RELIANCE"],
            "Combined_Score": [65.0],
            "Final_Score": [65.0],
            "Rating": ["HOLD"],
            "Technical_Score": [67.0],
            "Trend_Confirmed": [False],
        })

        result = TranscriptSentimentEnricher(SimpleNamespace(), FakeRepository()).enrich(source)

        self.assertEqual(result.loc[0, "Final_Score"], 65.0)
        self.assertEqual(result.loc[0, "Rating"], "HOLD")
        self.assertFalse(result.loc[0, "Transcript_Priority_Applied"])
        self.assertEqual(result.loc[0, "Transcript_Technical_Gate"], "Downside-only evidence; finalized centrally")

    def test_negative_high_risk_transcript_applies_downside_without_priority(self):
        source = pd.DataFrame({
            "Symbol": ["RELIANCE"],
            "Combined_Score": [75.0],
            "Final_Score": [75.0],
            "Rating": ["STRONG BUY"],
            "Technical_Score": [70.0],
            "Trend_Confirmed": [True],
            "Strong_Buy_Eligible": [True],
        })

        result = TranscriptSentimentEnricher(SimpleNamespace(), NegativeGuidanceRepository()).enrich(source)

        self.assertEqual(result.loc[0, "Transcript_Weighted_Score"], 40.0)
        self.assertEqual(result.loc[0, "Transcript_Effective_Score"], 40.0)
        self.assertEqual(result.loc[0, "Final_Score"], 75.0)
        self.assertFalse(result.loc[0, "Transcript_Priority_Applied"])
        self.assertTrue(result.loc[0, "Transcript_Downside_Applied"])
        self.assertEqual(
            result.loc[0, "Transcript_Quality_Gate"],
            "Sentiment below priority threshold; Risk above priority threshold; Guidance lowered",
        )
        self.assertEqual(
            result.loc[0, "Transcript_Quality_Gate_Failure_Count"], 3
        )
        self.assertEqual(result.loc[0, "Transcript_Proposed_Delta_Core"], -1.5)
        self.assertEqual(
            result.loc[0, "Transcript_Technical_Gate"],
            "Downside-only evidence; finalized centrally",
        )
        self.assertEqual(result.loc[0, "Rating"], "STRONG BUY")

    def test_recommendation_cap_is_a_ceiling_not_a_forced_hold(self):
        source = pd.DataFrame({
            "Symbol": ["RELIANCE"],
            "Combined_Score": [50.0],
            "Final_Score": [50.0],
            "Rating": ["HOLD"],
            "Rating_Capped": [True],
            "Technical_Score": [70.0],
            "Trend_Confirmed": [True],
            "Strong_Buy_Eligible": [False],
        })

        result = TranscriptSentimentEnricher(
            SimpleNamespace(), NegativeGuidanceRepository()
        ).enrich(source)

        self.assertEqual(result.loc[0, "Final_Score"], 50.0)
        self.assertEqual(result.loc[0, "Rating"], "HOLD")
        self.assertEqual(result.loc[0, "Transcript_Proposed_Delta_Core"], -1.5)

    def test_unclear_guidance_summary_provides_evidence_based_commentary(self):
        source = pd.DataFrame({
            "Symbol": ["RELIANCE"],
            "Combined_Score": [65.0],
            "Rating": ["BUY"],
            "Technical_Score": [65.0],
            "Trend_Confirmed": [True],
        })

        result = TranscriptSentimentEnricher(SimpleNamespace(), UnclearGuidanceRepository()).enrich(source)
        summary = result.loc[0, "Transcript_Summary"]

        self.assertIn("No explicit guidance", summary)
        self.assertIn("positive demand", summary)
        self.assertIn("margin pressure", summary)
        self.assertNotIn("Unclear", summary)

    def enrich_with_outlook(self, repository, **settings):
        source = pd.DataFrame({"Symbol": ["RELIANCE", "TCS"], "Combined_Score": [72.0, 65.0]})
        config = SimpleNamespace(TRANSCRIPT_OUTLOOK_ENABLED=True, **settings)
        return TranscriptSentimentEnricher(config, repository).enrich(source)

    def test_outlook_of_the_scored_call_is_attached(self):
        repository = OutlookRepository()
        result = self.enrich_with_outlook(repository)

        self.assertEqual(result.loc[0, "Transcript_Outlook_Score"], 73.0)
        self.assertEqual(result.loc[0, "Transcript_Outlook_Verified_Fields"], 3)
        self.assertEqual(
            result.loc[0, "Transcript_Outlook_Summary"],
            "guidance raised (+15); demand outlook strong (+8); headwind: input costs (-3)",
        )
        self.assertTrue(pd.isna(result.loc[1, "Transcript_Outlook_Score"]))
        breakdown = json.loads(result.loc[0, "Transcript_Outlook_Points"])
        # Rebuilt from the stored sections, so each item has its sentence; the
        # two guidance items share one, with the line break and spacing tidied.
        self.assertEqual(
            breakdown[:2],
            [
                {"reason": "guidance maintained", "points": 3.0,
                 "quote": "We maintain our guidance of 15% revenue growth for the year."},
                {"reason": "guided revenue growth 15-25%", "points": 6.0,
                 "quote": "We maintain our guidance of 15% revenue growth for the year."},
            ],
        )
        self.assertEqual(breakdown[2]["quote"], "Demand remains strong across our markets.")
        self.assertEqual(len(breakdown[-1]["quote"]), 400)
        self.assertTrue(breakdown[-1]["quote"].endswith("…"))
        self.assertEqual(result.loc[1, "Transcript_Outlook_Points"], "[]")
        self.assertEqual(repository.requested, (["RELIANCE", "TCS"], "outlook-v1", None))
        # Evidence only: the tone columns the policy reads are untouched.
        self.assertEqual(result.loc[0, "Transcript_Effective_Score"], 80.0)

    def test_outlook_is_compared_with_the_quarter_before(self):
        previous = {
            "call_date": "2026-05-12",
            "outlook_score": 81.0,
            "verified_fields": 4,
            "extraction": {
                "guidance": {"direction": "maintained", "growth_pct": 20.0},
                "demand": {"tone": "strong"},
                "margin": {"trend": "down"},
            },
        }
        result = self.enrich_with_outlook(OutlookRepository(previous=previous))

        self.assertEqual(result.loc[0, "Transcript_Outlook_Previous_Call_Date"], "2026-05-12")
        self.assertEqual(result.loc[0, "Transcript_Outlook_QoQ_Delta"], -8.0)
        self.assertEqual(result.loc[0, "Transcript_Outlook_QoQ_Worse"], 1)
        self.assertEqual(result.loc[0, "Transcript_Outlook_QoQ_Better"], 1)
        self.assertEqual(result.loc[0, "Transcript_Outlook_QoQ_Kept"], 1)
        self.assertEqual(
            result.loc[0, "Transcript_Outlook_QoQ_Changes"],
            "guided growth cut 20% -> 15%; margin outlook down -> flat; 1 item unchanged",
        )
        self.assertEqual(
            json.loads(result.loc[0, "Transcript_Outlook_QoQ_Items"])[0],
            {"item": "guidance", "change": "worse", "text": "guided growth cut 20% -> 15%"},
        )

    def test_a_first_call_has_no_quarter_to_compare_with(self):
        result = self.enrich_with_outlook(OutlookRepository())

        self.assertEqual(result.loc[0, "Transcript_Outlook_Score"], 73.0)
        self.assertTrue(pd.isna(result.loc[0, "Transcript_Outlook_QoQ_Delta"]))
        self.assertEqual(result.loc[0, "Transcript_Outlook_QoQ_Changes"], "")

    def test_outlook_of_an_older_call_is_not_attached(self):
        result = self.enrich_with_outlook(OutlookRepository(days_ago=120))

        self.assertTrue(pd.isna(result.loc[0, "Transcript_Outlook_Score"]))
        self.assertEqual(result.loc[0, "Transcript_Outlook_Summary"], "")

    def test_outlook_with_nothing_verified_is_absent_not_neutral(self):
        result = self.enrich_with_outlook(OutlookRepository(verified_fields=0))

        self.assertTrue(pd.isna(result.loc[0, "Transcript_Outlook_Score"]))

    def test_outlooks_are_not_read_unless_enabled(self):
        repository = OutlookRepository()
        source = pd.DataFrame({"Symbol": ["RELIANCE"], "Combined_Score": [72.0]})
        result = TranscriptSentimentEnricher(SimpleNamespace(), repository).enrich(source)

        self.assertIsNone(repository.requested)
        self.assertTrue(pd.isna(result.loc[0, "Transcript_Outlook_Score"]))

    def test_email_report_includes_transcript_summary_column(self):
        config = SimpleNamespace(
            TOP_STOCKS_COUNT=1,
            REVERSE_DCF_DISCOUNT_RATE=0.11,
            REVERSE_DCF_TERMINAL_GROWTH=0.04,
        )
        report = EmailReporter(config).create_html_report(pd.DataFrame([{
            "Rank": 1,
            "Symbol": "RELIANCE",
            "Current_Price": 100.0,
            "Fundamental_Score": 70.0,
            "Technical_Score": 70.0,
            "Combined_Score": 70.0,
            "Rating": "BUY",
            "Transcript_Summary": "80.0 | Maintained | 2026-08-05",
        }]), "06-08-2026")

        self.assertIn("Transcript Summary", report)
        self.assertIn("80.0 | Maintained | 2026-08-05", report)
        self.assertIn("Liquidity", report)
        self.assertIn("Red-flag Review", report)


if __name__ == "__main__":
    unittest.main()
