import unittest

from sentiment.analyzer import aggregate_sentiments
from sentiment.local_analyzer import LocalSentimentAnalyzer
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

    def test_aggregation_preserves_explicit_guidance_over_unclear_chunks(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(guidance_direction="raised")),
            ChunkSentiment.from_payload(sample_payload(guidance_direction="unclear")),
            ChunkSentiment.from_payload(sample_payload(guidance_direction="unclear")),
        ]
        chunks = [
            TranscriptChunk(0, "guidance", 50),
            TranscriptChunk(1, "commentary", 500),
            TranscriptChunk(2, "questions", 500),
        ]

        result = aggregate_sentiments(analyses, chunks)

        self.assertEqual(result["guidance_direction"], "raised")

    def test_local_analyzer_detects_raised_guidance_and_positive_catalyst(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "Demand remains strong and margins improved. We raised guidance after order growth accelerated."
        )

        self.assertEqual(result["guidance_direction"], "raised")
        self.assertGreater(result["optimism"], 50)
        self.assertGreater(result["guidance_strength"], 50)
        self.assertTrue(result["catalysts"])

    def test_local_analyzer_detects_lowered_guidance_and_risk(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "We lowered guidance because demand weakness and margin pressure remain challenging."
        )

        self.assertEqual(result["guidance_direction"], "lowered")
        self.assertLess(result["guidance_strength"], 50)
        self.assertGreater(result["risk_intensity"], 50)
        self.assertTrue(result["risks"])

    def test_local_analyzer_detects_common_guidance_wording(self):
        analyzer = LocalSentimentAnalyzer()

        self.assertEqual(
            analyzer.analyze_chunk("WE UPGRADED OUR OUTLOOK following strong demand.")["guidance_direction"],
            "raised",
        )
        self.assertEqual(
            analyzer.analyze_chunk("We reaffirmed our forecast for the full year.")["guidance_direction"],
            "maintained",
        )
        self.assertEqual(
            analyzer.analyze_chunk("We reduced our expectations because of demand weakness.")["guidance_direction"],
            "lowered",
        )

    def test_local_analyzer_reports_financial_risk_and_baseline_features(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "[management_answer] CFO: We may face commodity inflation and supply constraints."
        )

        self.assertEqual(result["section"], "management_answer")
        self.assertGreater(result["uncertainty_density"], 0)
        self.assertGreater(result["constraint_density"], 0)
        self.assertIn("textblob_polarity", result)
        self.assertIn("finbert_score", result)

    def test_aggregation_compares_prepared_remarks_with_management_qa(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(optimism=80, management_confidence=85)),
            ChunkSentiment.from_payload(sample_payload(optimism=50, management_confidence=55)),
        ]
        chunks = [
            TranscriptChunk(0, "[prepared_remarks] CFO:\nDemand is strong.", 100),
            TranscriptChunk(1, "[management_answer] CFO:\nRisks remain.", 100),
        ]
        payloads = [
            {"textblob_polarity": 0.5, "finbert_score": 0.4, "uncertainty_density": 0.01},
            {"textblob_polarity": 0.0, "finbert_score": -0.2, "uncertainty_density": 0.05},
        ]

        result = aggregate_sentiments(analyses, chunks, payloads)

        self.assertEqual(result["prepared_vs_qa_tone_gap"], 30.0)
        self.assertEqual(result["qa_confidence_drop"], 30.0)
        self.assertTrue(result["review_flag"])


if __name__ == "__main__":
    unittest.main()
