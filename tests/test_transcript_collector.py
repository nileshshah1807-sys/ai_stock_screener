import unittest

from transcripts.collector import is_earnings_transcript


class TranscriptCollectorTests(unittest.TestCase):
    def test_accepts_earnings_call_transcript(self):
        self.assertTrue(is_earnings_transcript({"desc": "Conference Call Transcript", "attchmntText": "Q1 results"}))

    def test_rejects_agm_transcript(self):
        self.assertFalse(is_earnings_transcript({"desc": "AGM transcript", "attchmntText": ""}))

    def test_rejects_non_transcript(self):
        self.assertFalse(is_earnings_transcript({"desc": "Investor presentation", "attchmntText": ""}))


if __name__ == "__main__":
    unittest.main()