import unittest

import requests

from storage.supabase_repository import SupabaseRepository


class PendingTranscriptRepositoryTests(unittest.TestCase):
    def test_requests_only_pending_transcripts_for_current_analyzer_version(self):
        repository = SupabaseRepository("https://example.test", "service-role-key")
        requests = []

        def request(method, path, **kwargs):
            requests.append((method, path, kwargs))
            return []

        repository._request = request

        result = repository.list_transcripts_for_analysis(
            "textblob-finance-lexicon",
            "v2-local-textblob-finance-lexicon",
        )

        self.assertEqual(result, [])
        self.assertEqual(requests, [(
            "POST",
            "rpc/pending_transcripts_for_analysis",
            {"json": {
                "requested_model_name": "textblob-finance-lexicon",
                "requested_analysis_version": "v2-local-textblob-finance-lexicon",
            }},
        )])

    def test_latest_sentiments_falls_back_when_structured_output_view_is_not_deployed(self):
        repository = SupabaseRepository("https://example.test", "service-role-key")
        requests_made = []

        def request(method, path, **kwargs):
            requests_made.append(kwargs["params"]["select"])
            if "structured_output" in kwargs["params"]["select"]:
                response = requests.Response()
                response.status_code = 400
                raise requests.HTTPError(response=response)
            return [{"symbol": "RELIANCE", "overall_score": 68}]

        repository._request = request

        result = repository.latest_sentiments(["RELIANCE"])

        self.assertEqual(result[0]["overall_score"], 68)
        self.assertEqual(len(requests_made), 2)
        self.assertNotIn("structured_output", requests_made[1])


if __name__ == "__main__":
    unittest.main()