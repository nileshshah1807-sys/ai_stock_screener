"""Behavioural spec for the empirical trading calendar.

The execution-critical property under test is that "the next trading day" is
resolved from sessions the exchange actually published, never from a weekday
assumption.
"""

import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from backtest.calendar import (
    NO_SESSION,
    SESSION,
    UNKNOWN,
    CalendarLedger,
    TradingCalendar,
    build_calendar,
)


class FakeStore:
    """A bhavcopy store whose available sessions are declared up front."""

    def __init__(self, available):
        self.available = set(available)
        self.cached = set()
        self.fetch_calls = []

    def has_day(self, day):
        return day in self.cached

    def fetch_day(self, day):
        self.fetch_calls.append(day)
        if day not in self.available:
            raise RuntimeError("NSE file is unavailable or not yet updated.")
        self.cached.add(day)
        return pd.DataFrame({"ISIN": ["INE001A01036"]})


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "calendar.csv"

    def tearDown(self):
        self._tmp.cleanup()

    def test_unprobed_date_is_unknown(self):
        ledger = CalendarLedger(self.path)
        self.assertEqual(ledger.status(date(2026, 8, 11)), UNKNOWN)

    def test_record_and_reload_round_trip(self):
        ledger = CalendarLedger(self.path)
        ledger.record(date(2026, 8, 11), SESSION)
        ledger.save()
        self.assertEqual(CalendarLedger(self.path).status(date(2026, 8, 11)), SESSION)

    def test_probe_count_accumulates(self):
        ledger = CalendarLedger(self.path)
        ledger.record(date(2026, 8, 12), UNKNOWN)
        ledger.record(date(2026, 8, 12), UNKNOWN)
        self.assertEqual(ledger.probes(date(2026, 8, 12)), 2)

    def test_pending_gap_before_a_later_session_becomes_a_holiday(self):
        ledger = CalendarLedger(self.path)
        ledger.record(date(2026, 8, 12), UNKNOWN)
        ledger.record(date(2026, 8, 13), SESSION)
        self.assertEqual(ledger.resolve_pending(), 1)
        self.assertEqual(ledger.status(date(2026, 8, 12)), NO_SESSION)

    def test_pending_gap_after_the_last_session_stays_unknown(self):
        """A file that may simply not be published yet must not become a holiday."""
        ledger = CalendarLedger(self.path)
        ledger.record(date(2026, 8, 13), SESSION)
        ledger.record(date(2026, 8, 14), UNKNOWN)
        ledger.resolve_pending()
        self.assertEqual(ledger.status(date(2026, 8, 14)), UNKNOWN)

    def test_unresolved_dates_are_excluded_from_sessions(self):
        ledger = CalendarLedger(self.path)
        ledger.record(date(2026, 8, 14), UNKNOWN)
        self.assertEqual(ledger.sessions(), [])

    def test_unreadable_ledger_starts_empty_rather_than_raising(self):
        self.path.write_text("this is not a csv\x00", encoding="utf-8")
        self.assertEqual(CalendarLedger(self.path).sessions(), [])


class TradingCalendarTests(unittest.TestCase):
    def setUp(self):
        # Mon 10th .. Fri 14th Aug 2026, with the 12th a holiday.
        self.calendar = TradingCalendar(
            [
                date(2026, 8, 10),
                date(2026, 8, 11),
                date(2026, 8, 13),
                date(2026, 8, 14),
            ]
        )

    def test_next_session_skips_a_non_session_day(self):
        self.assertEqual(
            self.calendar.next_session(date(2026, 8, 11)), date(2026, 8, 13)
        )

    def test_next_session_is_strictly_after_the_signal_date(self):
        """Signal on the close of t must never fill on t."""
        self.assertNotEqual(
            self.calendar.next_session(date(2026, 8, 10)), date(2026, 8, 10)
        )

    def test_next_session_from_a_non_session_date(self):
        self.assertEqual(
            self.calendar.next_session(date(2026, 8, 12)), date(2026, 8, 13)
        )

    def test_next_session_past_the_end_returns_none(self):
        self.assertIsNone(self.calendar.next_session(date(2026, 8, 14)))

    def test_next_session_does_not_clamp_to_the_last_session(self):
        """A position that cannot be filled must be dropped, not back-filled."""
        self.assertIsNone(self.calendar.next_session(date(2026, 8, 13), offset=5))

    def test_next_session_offset_counts_sessions_not_days(self):
        self.assertEqual(
            self.calendar.next_session(date(2026, 8, 10), offset=2), date(2026, 8, 13)
        )

    def test_previous_session_is_strictly_before(self):
        self.assertEqual(
            self.calendar.previous_session(date(2026, 8, 13)), date(2026, 8, 11)
        )

    def test_previous_session_before_the_start_returns_none(self):
        self.assertIsNone(self.calendar.previous_session(date(2026, 8, 10)))

    def test_session_on_or_before_returns_the_date_itself_when_a_session(self):
        self.assertEqual(
            self.calendar.session_on_or_before(date(2026, 8, 11)), date(2026, 8, 11)
        )

    def test_session_on_or_before_falls_back_on_a_holiday(self):
        self.assertEqual(
            self.calendar.session_on_or_before(date(2026, 8, 12)), date(2026, 8, 11)
        )

    def test_offset_below_one_is_rejected(self):
        with self.assertRaises(ValueError):
            self.calendar.next_session(date(2026, 8, 10), offset=0)

    def test_membership_and_length(self):
        self.assertIn(date(2026, 8, 13), self.calendar)
        self.assertNotIn(date(2026, 8, 12), self.calendar)
        self.assertEqual(len(self.calendar), 4)

    def test_sessions_between_is_inclusive(self):
        self.assertEqual(
            self.calendar.sessions_between(date(2026, 8, 11), date(2026, 8, 13)),
            [date(2026, 8, 11), date(2026, 8, 13)],
        )


class HorizonTests(unittest.TestCase):
    def test_month_horizon_lands_on_the_first_session_at_or_after_the_target(self):
        calendar = TradingCalendar(
            [date(2026, 1, 30), date(2026, 4, 30), date(2026, 5, 4)]
        )
        self.assertEqual(
            calendar.session_after_calendar_months(date(2026, 1, 30), 3),
            date(2026, 4, 30),
        )

    def test_month_horizon_skips_a_closed_target_date(self):
        calendar = TradingCalendar([date(2026, 1, 30), date(2026, 5, 4)])
        self.assertEqual(
            calendar.session_after_calendar_months(date(2026, 1, 30), 3),
            date(2026, 5, 4),
        )

    def test_horizon_beyond_available_data_returns_none(self):
        calendar = TradingCalendar([date(2026, 1, 30)])
        self.assertIsNone(
            calendar.session_after_calendar_months(date(2026, 1, 30), 3)
        )


class BuildCalendarTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "calendar.csv"
        self.clock = lambda: datetime(2026, 8, 20, 9, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_holiday_inside_the_window_is_classified_and_excluded(self):
        store = FakeStore({date(2026, 8, 11), date(2026, 8, 13)})
        ledger = CalendarLedger(self.path, clock=self.clock)
        calendar = build_calendar(
            store, date(2026, 8, 11), date(2026, 8, 13), ledger=ledger
        )
        self.assertEqual(calendar.sessions, [date(2026, 8, 11), date(2026, 8, 13)])
        self.assertEqual(ledger.status(date(2026, 8, 12)), NO_SESSION)

    def test_weekend_is_never_probed(self):
        store = FakeStore({date(2026, 8, 14), date(2026, 8, 17)})
        ledger = CalendarLedger(self.path, clock=self.clock)
        build_calendar(store, date(2026, 8, 14), date(2026, 8, 17), ledger=ledger)
        self.assertNotIn(date(2026, 8, 15), store.fetch_calls)
        self.assertNotIn(date(2026, 8, 16), store.fetch_calls)

    def test_fetch_budget_is_respected(self):
        store = FakeStore(
            {date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)}
        )
        ledger = CalendarLedger(self.path, clock=self.clock)
        build_calendar(
            store, date(2026, 8, 10), date(2026, 8, 13), ledger=ledger, max_fetches=2
        )
        self.assertEqual(len(store.fetch_calls), 2)

    def test_build_resumes_where_the_budget_stopped(self):
        store = FakeStore(
            {date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)}
        )
        ledger = CalendarLedger(self.path, clock=self.clock)
        for _ in range(2):
            calendar = build_calendar(
                store,
                date(2026, 8, 10),
                date(2026, 8, 13),
                ledger=ledger,
                max_fetches=2,
            )
        self.assertEqual(len(calendar), 4)

    def test_known_holiday_is_not_reprobed_on_a_later_build(self):
        store = FakeStore({date(2026, 8, 11), date(2026, 8, 13)})
        ledger = CalendarLedger(self.path, clock=self.clock)
        build_calendar(store, date(2026, 8, 11), date(2026, 8, 13), ledger=ledger)
        before = len(store.fetch_calls)
        build_calendar(store, date(2026, 8, 11), date(2026, 8, 13), ledger=ledger)
        self.assertEqual(len(store.fetch_calls), before)

    def test_already_cached_day_is_recorded_without_fetching(self):
        store = FakeStore({date(2026, 8, 11)})
        store.cached.add(date(2026, 8, 11))
        ledger = CalendarLedger(self.path, clock=self.clock)
        calendar = build_calendar(
            store, date(2026, 8, 11), date(2026, 8, 11), ledger=ledger
        )
        self.assertEqual(store.fetch_calls, [])
        self.assertEqual(calendar.sessions, [date(2026, 8, 11)])

    def test_ledger_is_persisted_for_the_next_run(self):
        store = FakeStore({date(2026, 8, 11)})
        ledger = CalendarLedger(self.path, clock=self.clock)
        build_calendar(store, date(2026, 8, 11), date(2026, 8, 11), ledger=ledger)
        self.assertTrue(self.path.exists())


if __name__ == "__main__":
    unittest.main()
