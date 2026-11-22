"""Days since and to results, the columns the publisher stamps on every snapshot row."""

import unittest
from datetime import date
from unittest import mock
from zoneinfo import ZoneInfo

from workers import results_timing
from workers.dashboard_publisher import stamp_results_timing

RUN = date(2026, 11, 22)
IST = ZoneInfo("Asia/Kolkata")


class DaysSinceTests(unittest.TestCase):
    def test_the_latest_announcement_in_the_markets_own_day(self):
        days = results_timing.days_since([
            {"symbol": "ABC", "broadcast_at": "2026-08-10T12:00:00+00:00"},
            # 20 Nov 22:00 UTC is 21 Nov in India.
            {"symbol": "ABC", "broadcast_at": "2026-11-20T22:00:00+00:00"},
        ], RUN, IST)
        self.assertEqual(days, {"ABC": 1})

    def test_an_unreadable_time_is_skipped(self):
        self.assertEqual(results_timing.days_since([{"symbol": "ABC", "broadcast_at": None}], RUN, IST), {})


class DaysToTests(unittest.TestCase):
    def test_a_passed_date_is_no_date(self):
        days = results_timing.days_to({
            "ABC": {"next_result_date": "2026-11-29"},
            "OLD": {"next_result_date": "2026-11-20"},
            "TODAY": {"next_result_date": "2026-11-22"},
            "NONE": {"next_result_date": None},
        }, RUN)
        self.assertEqual(days, {"ABC": 7, "TODAY": 0})


class StampTests(unittest.TestCase):
    def test_every_row_gets_both_columns_and_a_failed_source_leaves_nulls(self):
        repo = mock.Mock()
        repo.result_broadcasts_since.side_effect = RuntimeError("table missing")
        repo.upcoming_events.return_value = {"ABC": {"next_result_date": "2026-11-25"}}
        rows = [{"symbol": "ABC"}, {"symbol": "XYZ"}]
        stamp_results_timing(repo, rows, RUN.isoformat(), "Asia/Kolkata")
        self.assertEqual(rows[0], {"symbol": "ABC", "days_since_result": None, "days_to_result": 3})
        self.assertEqual(rows[1], {"symbol": "XYZ", "days_since_result": None, "days_to_result": None})


if __name__ == "__main__":
    unittest.main()
