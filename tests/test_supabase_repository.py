import unittest

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


if __name__ == "__main__":
    unittest.main()