import unittest

from sentiment.analyzer import aggregate_sentiments
from sentiment.schemas import ChunkSentiment
from transcripts.chunker import TranscriptChunk


def sample_payload(**overrides):
    payload = {
        "optimism": 80,
        "guidance_strength": 70,
        "management_confidence": 75,
        "risk_intensity": 20,
        "analyst_pressure": 35,
        "answer_quality": 85,
        "guidance_direction": "maintained",
        "revenue_outlook": "Growth continues.",
        "margin_outlook": "Margins stable.",
        "demand_outlook": "Demand healthy.",
        "catalysts": ["Capacity expansion"],
        "risks": ["Commodity costs"],
        "evidence": ["We maintain guidance."],
    }
    payload.update(overrides)
    return payload


class SentimentAnalysisTests(unittest.TestCase):
    def test_schema_rejects_out_of_range_scores(self):
        with self.assertRaises(ValueError):
            ChunkSentiment.from_payload(sample_payload(optimism=101))

    def test_aggregation_applies_documented_score_formula(self):
        analysis = ChunkSentiment.from_payload(sample_payload())
        result = aggregate_sentiments([analysis], [TranscriptChunk(0, "text", 100)])

        self.assertEqual(result["overall_score"], 77.75)
        self.assertEqual(result["confidence_score"], 75)
        self.assertEqual(result["guidance_direction"], "maintained")


if __name__ == "__main__":
    unittest.main()