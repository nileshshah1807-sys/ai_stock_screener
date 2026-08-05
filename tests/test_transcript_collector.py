import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from transcripts.collector import discover_nse_transcripts, is_earnings_transcript


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


if __name__ == "__main__":
    unittest.main()