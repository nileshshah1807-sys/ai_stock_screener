import unittest
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from scoring.transcript_enricher import TranscriptSentimentEnricher, recency_weight


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

    def test_enrichment_is_report_only(self):
        source = pd.DataFrame({"Symbol": ["RELIANCE", "TCS"], "Combined_Score": [72.0, 65.0]})
        config = SimpleNamespace()

        result = TranscriptSentimentEnricher(config, FakeRepository()).enrich(source)

        self.assertEqual(result["Combined_Score"].tolist(), [72.0, 65.0])
        self.assertEqual(result.loc[0, "Transcript_Status"], "Available")
        self.assertEqual(result.loc[0, "Transcript_Weighted_Score"], 60.0)
        self.assertEqual(result.loc[1, "Transcript_Status"], "No transcript")


if __name__ == "__main__":
    unittest.main()