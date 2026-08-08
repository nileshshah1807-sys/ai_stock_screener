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
            25,
        )

        self.assertEqual(result, [])
        self.assertEqual(requests, [(
            "POST",
            "rpc/pending_transcripts_for_analysis",
            {"json": {
                "requested_model_name": "textblob-finance-lexicon",
                "requested_analysis_version": "v2-local-textblob-finance-lexicon",
                "requested_limit": 25,
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

    def test_latest_sentiments_batches_symbols_below_postgrest_row_limit(self):
        repository = SupabaseRepository("https://example.test", "service-role-key")
        requested_batches = []

        def request(method, path, **kwargs):
            symbols = kwargs["params"]["symbol"].removeprefix("in.(").removesuffix(")").split(",")
            requested_batches.append(symbols)
            return [{"symbol": symbol, "overall_score": 68} for symbol in symbols]

        repository._request = request
        symbols = [f"STOCK{index}" for index in range(501)]

        result = repository.latest_sentiments(symbols)

        self.assertEqual([len(batch) for batch in requested_batches], [200, 200, 101])
        self.assertEqual(len(result), 501)
        self.assertEqual(result[0]["symbol"], "STOCK0")
        self.assertEqual(result[-1]["symbol"], "STOCK500")

    def test_latest_sentiments_only_probes_missing_structured_column_once(self):
        repository = SupabaseRepository("https://example.test", "service-role-key")
        requested_selects = []

        def request(method, path, **kwargs):
            select = kwargs["params"]["select"]
            requested_selects.append(select)
            if "structured_output" in select:
                response = requests.Response()
                response.status_code = 400
                raise requests.HTTPError(response=response)
            return []

        repository._request = request

        repository.latest_sentiments(["A", "B", "C"], batch_size=2)

        self.assertEqual(len(requested_selects), 3)
        self.assertIn("structured_output", requested_selects[0])
        self.assertNotIn("structured_output", requested_selects[1])
        self.assertNotIn("structured_output", requested_selects[2])

    def test_red_flag_snapshot_reads_are_batched(self):
        repository = SupabaseRepository("https://example.test", "service-role-key")
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return []

        repository._request = request
        repository.latest_red_flag_snapshots(["A", "B", "C"], batch_size=2)

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][2]["params"]["symbol"], "in.(A,B)")
        self.assertEqual(calls[1][2]["params"]["symbol"], "in.(C)")

    def test_red_flag_snapshot_upserts_are_batched(self):
        repository = SupabaseRepository("https://example.test", "service-role-key")
        payload_sizes = []

        def request(method, path, **kwargs):
            payload_sizes.append(len(kwargs["json"]))
            return None

        repository._request = request
        saved = repository.upsert_red_flag_snapshots(
            [{"symbol": symbol} for symbol in ("A", "B", "C")],
            batch_size=2,
        )

        self.assertEqual(saved, 3)
        self.assertEqual(payload_sizes, [2, 1])

    def test_red_flag_history_is_idempotent_by_source_symbol_policy_and_day(self):
        repository = SupabaseRepository("https://example.test", "service-role-key")
        calls = []

        def request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return None

        repository._request = request
        saved = repository.upsert_red_flag_snapshot_history([{
            "source": "VIGIL",
            "symbol": "TEST",
            "severity": 2,
            "flag_count": 1,
            "summary": "pledge",
            "source_status": "current",
            "source_as_of": "2026-08-08",
            "snapshot": {"policy": "shadow-v2", "flags": []},
        }], "2026-08-08")

        self.assertEqual(saved, 1)
        self.assertIn(
            "on_conflict=source,symbol,policy,observed_on",
            calls[0][1],
        )
        self.assertEqual(calls[0][2]["json"][0]["policy"], "shadow-v2")
        self.assertEqual(calls[0][2]["json"][0]["observed_on"], "2026-08-08")
        self.assertIn("fetched_at", calls[0][2]["json"][0])


if __name__ == "__main__":
    unittest.main()
