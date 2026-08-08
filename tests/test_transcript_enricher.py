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


class TranscriptEnricherTests(unittest.TestCase):
    def test_recency_weight_matches_policy_boundaries(self):
        today = date(2026, 8, 5)
        self.assertEqual(recency_weight("2026-07-06", today), 1.0)
        self.assertEqual(recency_weight("2026-07-05", today), 0.75)
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
        self.assertEqual(result.loc[0, "Transcript_Weighted_Score"], 72.5)
        self.assertEqual(result.loc[0, "Final_Score"], 72.07)
        self.assertEqual(result.loc[0, "Rating"], "BUY")
        self.assertEqual(result.loc[0, "Transcript_Uncertainty_QoQ_Delta"], -0.03)
        self.assertEqual(result.loc[0, "Transcript_Previous_Guidance"], "raised")
        self.assertTrue(result.loc[0, "Transcript_Priority_Applied"])
        self.assertEqual(result.loc[0, "Transcript_Summary"].split(" | ")[:2], ["80.0", "Maintained"])
        self.assertEqual(result.loc[1, "Transcript_Status"], "No transcript")
        self.assertEqual(result.loc[1, "Final_Score"], 65.0)
        self.assertFalse(result.loc[1, "Transcript_Priority_Applied"])
        ranked = rank_by_transcript_priority(result)
        self.assertEqual(ranked["Symbol"].tolist(), ["RELIANCE", "TCS"])
        self.assertEqual(ranked["Rank"].tolist(), [1, 2])

    def test_ranking_prioritizes_validated_confirmation_within_rating_gate(self):
        source = pd.DataFrame({
            "Symbol": ["NO_TRANSCRIPT_BUY", "TRANSCRIPT_BUY", "TRANSCRIPT_REDUCE", "STRONG_BUY"],
            "Final_Score": [85.0, 70.0, 95.0, 72.0],
            "Rating": ["BUY", "BUY", "REDUCE", "STRONG BUY"],
            "Transcript_Priority_Applied": [False, True, True, False],
        })

        ranked = rank_by_transcript_priority(source)

        self.assertEqual(ranked["Symbol"].tolist(), [
            "STRONG_BUY",
            "TRANSCRIPT_BUY",
            "NO_TRANSCRIPT_BUY",
            "TRANSCRIPT_REDUCE",
        ])

    def test_missing_transcript_caps_strong_buy_at_buy(self):
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

        self.assertEqual(result.loc[0, "Rating"], "BUY")
        self.assertTrue(result.loc[0, "Transcript_Strong_Buy_Capped"])
        self.assertEqual(
            result.loc[0, "Transcript_Technical_Gate"],
            "Fresh, quality transcript required for STRONG BUY",
        )

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

        self.assertEqual(result.loc[0, "Final_Score"], 65.56)
        self.assertEqual(result.loc[0, "Rating"], "BUY")
        self.assertFalse(result.loc[0, "Transcript_Priority_Applied"])
        self.assertEqual(result.loc[0, "Transcript_Technical_Gate"], "Limited weight; no rating promotion")

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
        self.assertEqual(result.loc[0, "Transcript_Technical_Gate"], "Trend not confirmed; no transcript weight")

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
        self.assertEqual(result.loc[0, "Transcript_Effective_Score"], 25.0)
        self.assertEqual(result.loc[0, "Final_Score"], 67.5)
        self.assertFalse(result.loc[0, "Transcript_Priority_Applied"])
        self.assertTrue(result.loc[0, "Transcript_Downside_Applied"])
        self.assertEqual(result.loc[0, "Transcript_Quality_Gate"], "Guidance lowered")
        self.assertEqual(
            result.loc[0, "Transcript_Technical_Gate"],
            "Downside applied; transcript quality gate failed",
        )
        self.assertEqual(result.loc[0, "Rating"], "BUY")

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

        self.assertEqual(result.loc[0, "Final_Score"], 46.25)
        self.assertEqual(result.loc[0, "Rating"], "REDUCE")

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


if __name__ == "__main__":
    unittest.main()
