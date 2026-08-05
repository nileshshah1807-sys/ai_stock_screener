import unittest

from sentiment.openrouter_client import _content_preview, _parse_json_object
from sentiment.schemas import ChunkSentiment


class OpenRouterClientTests(unittest.TestCase):
    def test_parses_valid_json_object(self):
        self.assertEqual(_parse_json_object('{"overall_score": 20}'), {"overall_score": 20})

    def test_parses_json_with_provider_preamble_and_suffix(self):
        content = 'Here is the requested analysis:\n```json\n{"overall_score": 20}\n```\n'
        self.assertEqual(_parse_json_object(content), {"overall_score": 20})

    def test_parses_observed_model_payload(self):
        content = """{
  "risks": [],
  "evidence": [],
  "optimism": 0,
  "catalysts": [],
  "overall_score": 20,
  "answer_quality": 0,
  "demand_outlook": "",
  "margin_outlook": "",
  "risk_intensity": 0,
  "revenue_outlook": "",
  "analyst_pressure": 0,
  "confidence_score": 0,
  "guidance_strength": 0,
  "guidance_direction": "unclear",
  "management_confidence": 0
}"""

        payload = _parse_json_object(content)
        analysis = ChunkSentiment.from_payload(payload)

        self.assertEqual(analysis.optimism, 0)
        self.assertEqual(analysis.guidance_direction, "unclear")

    def test_rejects_response_without_json_object(self):
        with self.assertRaises(ValueError):
            _parse_json_object("I cannot analyze this transcript.")

    def test_response_preview_is_bounded(self):
        self.assertEqual(_content_preview("abcdef", 3), "abc... [truncated]")

    def test_request_forces_compact_json_object_output(self):
        from sentiment.openrouter_client import OpenRouterClient

        client = OpenRouterClient("test-key", "test-model")
        payload = client._request_payload("test prompt")

        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["max_tokens"], 600)


if __name__ == "__main__":
    unittest.main()