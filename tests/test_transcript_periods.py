import unittest
from datetime import date

from transcripts.periods import (
    CURRENT_CYCLE,
    EXPIRED,
    PRIOR_CYCLE,
    classify_transcript_evidence,
    latest_expected_reporting_period,
    reporting_period_end_for_call,
)


class TranscriptPeriodTests(unittest.TestCase):
    def test_call_is_assigned_to_period_that_ended_before_it(self):
        self.assertEqual(reporting_period_end_for_call(date(2026, 6, 1)), date(2026, 3, 31))
        self.assertEqual(reporting_period_end_for_call(date(2026, 7, 15)), date(2026, 6, 30))
        self.assertEqual(reporting_period_end_for_call(date(2026, 6, 30)), date(2026, 3, 31))

    def test_expected_period_advances_only_after_result_and_transcript_window(self):
        self.assertEqual(latest_expected_reporting_period(date(2026, 8, 8)), date(2026, 3, 31))
        self.assertEqual(latest_expected_reporting_period(date(2026, 8, 21)), date(2026, 6, 30))

    def test_old_call_becomes_prior_cycle_when_next_reporting_window_passes(self):
        before_deadline = classify_transcript_evidence("2026-06-01", date(2026, 8, 8))
        after_deadline = classify_transcript_evidence("2026-06-01", date(2026, 8, 21))
        newer_call = classify_transcript_evidence("2026-07-15", date(2026, 8, 21))

        self.assertEqual(before_deadline.status, CURRENT_CYCLE)
        self.assertTrue(before_deadline.scoring_eligible)
        self.assertEqual(after_deadline.status, PRIOR_CYCLE)
        self.assertFalse(after_deadline.scoring_eligible)
        self.assertEqual(newer_call.status, CURRENT_CYCLE)

    def test_age_limit_still_expires_very_old_evidence(self):
        evidence = classify_transcript_evidence("2025-01-01", date(2026, 8, 8))
        self.assertEqual(evidence.status, EXPIRED)


if __name__ == "__main__":
    unittest.main()
