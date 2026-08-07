import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from transcripts.collector import discover_nse_transcripts, filing_payload, is_earnings_transcript


class TranscriptCollectorTests(unittest.TestCase):
    def test_accepts_earnings_call_transcript(self):
        self.assertTrue(is_earnings_transcript({"desc": "Conference Call Transcript", "attchmntText": "Q1 results"}))

    def test_rejects_agm_transcript(self):
        self.assertFalse(is_earnings_transcript({"desc": "AGM transcript", "attchmntText": ""}))

    def test_rejects_non_transcript(self):
        self.assertFalse(is_earnings_transcript({"desc": "Investor presentation", "attchmntText": ""}))

    def test_discovery_provides_required_nse_download_folder(self):
        class FakeNSE:
            init_kwargs = None

            def __init__(self, **kwargs):
                type(self).init_kwargs = kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def announcements(self, **kwargs):
                return [{"desc": "Earnings call transcript", "attchmntText": ""}]

        with patch.dict(sys.modules, {"nse": SimpleNamespace(NSE=FakeNSE)}):
            records = discover_nse_transcripts(7)

        self.assertEqual(len(records), 1)
        self.assertTrue(FakeNSE.init_kwargs["download_folder"])
        self.assertEqual(FakeNSE.init_kwargs["timeout"], 60)

    def test_discovery_retries_a_transient_nse_failure(self):
        class FlakyNSE:
            calls = 0

            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def announcements(self, **kwargs):
                type(self).calls += 1
                if type(self).calls == 1:
                    raise TimeoutError("temporary NSE timeout")
                return [{"desc": "Earnings call transcript", "attchmntText": ""}]

        with patch.dict(sys.modules, {"nse": SimpleNamespace(NSE=FlakyNSE)}):
            records = discover_nse_transcripts(120, attempts=2, retry_delay_seconds=0)

        self.assertEqual(len(records), 1)
        self.assertEqual(FlakyNSE.calls, 2)

    def test_filing_payload_preserves_iso_announcement_datetime(self):
        payload = filing_payload({
            "seq_id": "123",
            "symbol": "EXPLEOSOL",
            "an_dt": "2026-05-20T17:30:00+05:30",
        })

        self.assertEqual(payload["announcement_date"], "2026-05-20T17:30:00+05:30")


if __name__ == "__main__":
    unittest.main()
