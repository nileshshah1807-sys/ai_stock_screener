import unittest
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from app import EmailReporter
from scoring.transcript_enricher import TranscriptSentimentEnricher, rank_by_transcript_priority, recency_weight


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
        })
        config = SimpleNamespace()

        result = TranscriptSentimentEnricher(config, FakeRepository()).enrich(source)

        self.assertEqual(result["Combined_Score"].tolist(), [72.0, 65.0])
        self.assertEqual(result.loc[0, "Transcript_Status"], "Available")
        self.assertEqual(result.loc[0, "Transcript_Weighted_Score"], 60.0)
        self.assertEqual(result.loc[0, "Final_Score"], 62.4)
        self.assertTrue(result.loc[0, "Transcript_Priority_Applied"])
        self.assertEqual(result.loc[0, "Transcript_Summary"].split(" | ")[:2], ["80.0", "Maintained"])
        self.assertEqual(result.loc[1, "Transcript_Status"], "No transcript")
        self.assertEqual(result.loc[1, "Final_Score"], 65.0)
        self.assertFalse(result.loc[1, "Transcript_Priority_Applied"])
        ranked = rank_by_transcript_priority(result)
        self.assertEqual(ranked["Symbol"].tolist(), ["RELIANCE", "TCS"])
        self.assertEqual(ranked["Rank"].tolist(), [1, 2])

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