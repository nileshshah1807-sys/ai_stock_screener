import unittest
from unittest.mock import patch

from sentiment.analyzer import analyze_transcript, aggregate_sentiments
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

    def test_explicit_guidance_strength_is_not_diluted_by_unclear_chunks(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(
                guidance_direction="raised", guidance_strength=85,
            )),
            ChunkSentiment.from_payload(sample_payload(
                guidance_direction="unclear", guidance_strength=35,
            )),
        ]
        chunks = [
            TranscriptChunk(0, "[prepared_remarks] CEO:\nWe will exceed guidance.", 50),
            TranscriptChunk(1, "[prepared_remarks] CEO:\nGeneral commentary.", 500),
        ]

        result = aggregate_sentiments(analyses, chunks)

        self.assertEqual(result["guidance_strength"], 85.0)

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

    def test_local_analyzer_detects_exceeding_prior_guidance(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "For the current year, we are on track to not only achieve what we have guided "
            "but exceed it, with 35% plus growth."
        )

        self.assertEqual(result["guidance_direction"], "raised")
        self.assertEqual(result["guidance_strength"], 85.0)

    def test_stockscans_style_transcript_preserves_syrma_raised_guidance(self):
        text = """Jasbir S. Gujral - Managing Director, Syrma SGS Technology Limited
We are well on track to not only achieving what we have guided but exceeding that achievement.
Nikhil Kandoi - Analyst, Axis Capital
Can you clarify the growth outlook?
Jasbir S. Gujral - Managing Director, Syrma SGS Technology Limited
It is 35% plus growth for the current year and 30% to 35% for the next three years.
"""

        result = analyze_transcript(text)

        self.assertEqual(result["guidance_direction"], "raised")
        self.assertEqual(result["guidance_strength"], 85.0)

    def test_local_analyzer_reports_financial_risk_and_baseline_features(self):
        result = LocalSentimentAnalyzer().analyze_chunk(
            "[management_answer] CFO: We may face commodity inflation and supply constraints."
        )

        self.assertEqual(result["section"], "management_answer")
        self.assertGreater(result["uncertainty_density"], 0)
        self.assertGreater(result["constraint_density"], 0)
        self.assertIn("textblob_polarity", result)
        self.assertIn("finbert_score", result)

    def test_required_finbert_inference_failure_is_not_silently_downgraded(self):
        def broken_classifier(*args, **kwargs):
            raise RuntimeError("model unavailable")

        with (
            patch.dict("os.environ", {"TRANSCRIPT_REQUIRE_FINBERT": "true"}),
            patch("sentiment.local_analyzer._finbert_pipeline", return_value=broken_classifier),
        ):
            with self.assertRaisesRegex(RuntimeError, "FinBERT inference failed"):
                LocalSentimentAnalyzer().analyze_chunk("Demand remained strong.")

    def test_finbert_sentences_are_batched_across_chunks(self):
        calls = []

        def classifier(sentences, **kwargs):
            calls.append((list(sentences), kwargs))
            return [{"label": "positive", "score": 0.9} for _ in sentences]

        with patch("sentiment.local_analyzer._finbert_pipeline", return_value=classifier):
            results = LocalSentimentAnalyzer().analyze_chunks([
                "Revenue improved. Demand remains strong.",
                "Margins improved.",
            ])

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0][0]), 3)
        self.assertEqual(calls[0][1]["batch_size"], 1)
        self.assertEqual([result["finbert_score"] for result in results], [0.9, 0.9])

    def test_finbert_input_is_capped_to_high_signal_sentences(self):
        calls = []

        def classifier(sentences, **kwargs):
            calls.append(list(sentences))
            return [{"label": "neutral", "score": 0.9} for _ in sentences]

        text = " ".join(
            f"Revenue growth improved by {index}% and demand remains strong."
            for index in range(40)
        )
        with patch("sentiment.local_analyzer._finbert_pipeline", return_value=classifier):
            LocalSentimentAnalyzer().analyze_chunks([text])

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 8)

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

    def test_aggregation_does_not_blend_analyst_question_tone_into_management_score(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(optimism=80, risk_intensity=20)),
            ChunkSentiment.from_payload(sample_payload(optimism=5, risk_intensity=95)),
        ]
        chunks = [
            TranscriptChunk(0, "[management_answer] CEO:\nDemand remains strong.", 100),
            TranscriptChunk(1, "[analyst_question] Analyst:\nWhy is demand collapsing?", 1000),
        ]

        result = aggregate_sentiments(analyses, chunks)

        self.assertEqual(result["optimism"], 80.0)
        self.assertEqual(result["risk_intensity"], 20.0)

    def test_lowered_guidance_is_not_outvoted_by_a_longer_maintained_chunk(self):
        analyses = [
            ChunkSentiment.from_payload(sample_payload(guidance_direction="lowered")),
            ChunkSentiment.from_payload(sample_payload(guidance_direction="maintained")),
        ]
        chunks = [
            TranscriptChunk(0, "[management_answer] CFO:\nWe lowered guidance.", 50),
            TranscriptChunk(1, "[prepared_remarks] CEO:\nPrior guidance discussion.", 1000),
        ]

        result = aggregate_sentiments(analyses, chunks)

        self.assertEqual(result["guidance_direction"], "lowered")


if __name__ == "__main__":
    unittest.main()
