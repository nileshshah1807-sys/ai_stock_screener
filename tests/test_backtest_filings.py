"""Behavioural spec for point-in-time filing metadata.

Two properties carry the whole fundamental path:

* a filing is invisible before it was broadcast, and
* a restatement is invisible before it was published, even though it is the only
  version a present-day data source would show.

If either fails, every quality and growth score in the backtest is computed with
information the investor did not have.
"""

import unittest
from datetime import date, datetime

import pandas as pd

from backtest.calendar import TradingCalendar
from backtest.filings import (
    IND_AS_FROM_YEAR,
    FilingStore,
    PointInTimeFilings,
    assign_versions,
    attach_availability,
    normalise_filings,
    parse_nse_timestamp,
)

SESSIONS = [
    date(2024, 5, 15),
    date(2024, 5, 16),
    date(2024, 5, 17),
    date(2024, 5, 20),
    date(2025, 4, 20),
    date(2025, 4, 21),
]


def raw(**overrides):
    record = {
        "seqNumber": "1197618",
        "isin": "INE002A01018",
        "symbol": "RELIANCE",
        "companyName": "Reliance Industries Limited",
        "fromDate": "01-Apr-2023",
        "toDate": "31-Mar-2024",
        "relatingTo": "Fourth Quarter",
        "financialYear": "01-Apr-2023 To 31-Mar-2024",
        "filingDate": "16-May-2024 14:07",
        "broadCastDate": "16-May-2024 14:07:24",
        "consolidated": "Consolidated",
        "audited": "Audited",
        "cumulative": "Cumulative",
        "period": "Annual",
        "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_1_1_16052024.xml",
    }
    record.update(overrides)
    return record


class TimestampTests(unittest.TestCase):
    def test_parses_the_minute_precision_form(self):
        self.assertEqual(
            parse_nse_timestamp("06-Aug-2026 14:07"), datetime(2026, 8, 6, 14, 7)
        )

    def test_parses_the_second_precision_form(self):
        self.assertEqual(
            parse_nse_timestamp("06-Aug-2026 14:07:24"),
            datetime(2026, 8, 6, 14, 7, 24),
        )

    def test_parses_a_bare_date(self):
        self.assertEqual(parse_nse_timestamp("06-Aug-2026"), datetime(2026, 8, 6))

    def test_placeholder_is_not_a_timestamp(self):
        self.assertIsNone(parse_nse_timestamp("-"))
        self.assertIsNone(parse_nse_timestamp(""))
        self.assertIsNone(parse_nse_timestamp(None))


class NormaliseTests(unittest.TestCase):
    def test_captures_the_filing_timestamp(self):
        frame = normalise_filings([raw()])
        self.assertEqual(frame["Broadcast_Timestamp"].iloc[0], "2024-05-16T14:07:24")

    def test_captures_the_period_covered(self):
        frame = normalise_filings([raw()])
        self.assertEqual(frame["Period_End"].iloc[0], "2024-03-31")

    def test_period_end_and_filing_date_are_different_facts(self):
        """The distinction the whole module exists for: FY ends March, the
        statement arrives in May."""
        frame = normalise_filings([raw()])
        self.assertLess(
            frame["Period_End"].iloc[0], frame["Broadcast_Timestamp"].iloc[0][:10]
        )

    def test_consolidated_and_audited_flags_are_parsed(self):
        frame = normalise_filings([raw()])
        self.assertTrue(bool(frame["Consolidated"].iloc[0]))
        self.assertTrue(bool(frame["Audited"].iloc[0]))

    def test_standalone_is_not_consolidated(self):
        frame = normalise_filings([raw(consolidated="Non-Consolidated")])
        self.assertFalse(bool(frame["Consolidated"].iloc[0]))

    def test_ind_as_documents_are_flagged(self):
        self.assertTrue(bool(normalise_filings([raw()])["Is_Ind_AS"].iloc[0]))

    def test_non_ind_as_document_is_flagged_false(self):
        frame = normalise_filings(
            [raw(xbrl="https://nsearchives.nseindia.com/corporate/xbrl/OLDGAAP_1.xml")]
        )
        self.assertFalse(bool(frame["Is_Ind_AS"].iloc[0]))

    def test_row_without_isin_is_dropped(self):
        self.assertTrue(normalise_filings([raw(isin="")]).empty)

    def test_row_without_period_end_is_dropped(self):
        self.assertTrue(normalise_filings([raw(toDate="-")]).empty)

    def test_row_without_a_broadcast_timestamp_is_dropped(self):
        """A filing that cannot be placed in time is worse than no filing."""
        self.assertTrue(
            normalise_filings([raw(broadCastDate="-", filingDate="-")]).empty
        )

    def test_filings_before_the_ind_as_era_are_excluded(self):
        old = raw(broadCastDate="16-May-2015 14:07:24", filingDate="16-May-2015 14:07")
        self.assertTrue(normalise_filings([old]).empty)

    def test_min_year_is_the_ind_as_boundary(self):
        self.assertEqual(IND_AS_FROM_YEAR, 2018)

    def test_duplicate_exchange_records_collapse(self):
        frame = normalise_filings([raw(), raw()])
        self.assertEqual(len(frame), 1)

    def test_empty_input_keeps_the_schema(self):
        frame = normalise_filings([])
        self.assertTrue(frame.empty)
        self.assertIn("Available_From", frame.columns)


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.calendar = TradingCalendar(SESSIONS)

    def test_available_from_is_the_next_session_after_broadcast(self):
        frame = attach_availability(normalise_filings([raw()]), self.calendar)
        self.assertEqual(frame["Available_From"].iloc[0], "2024-05-17")

    def test_a_filing_before_the_close_is_still_next_session(self):
        """Broadcast at 09:30 does not make it actionable that session."""
        frame = attach_availability(
            normalise_filings([raw(broadCastDate="16-May-2024 09:30:00")]),
            self.calendar,
        )
        self.assertEqual(frame["Available_From"].iloc[0], "2024-05-17")

    def test_a_filing_after_the_close_skips_to_the_next_session(self):
        frame = attach_availability(
            normalise_filings([raw(broadCastDate="17-May-2024 18:30:00")]),
            self.calendar,
        )
        self.assertEqual(frame["Available_From"].iloc[0], "2024-05-20")

    def test_a_filing_past_the_calendar_has_no_availability(self):
        frame = attach_availability(
            normalise_filings([raw(broadCastDate="30-Dec-2025 10:00:00")]),
            self.calendar,
        )
        self.assertEqual(frame["Available_From"].iloc[0], "")


class VersionTests(unittest.TestCase):
    def two_versions(self):
        original = raw(seqNumber="1", broadCastDate="16-May-2024 14:07:24")
        restated = raw(seqNumber="2", broadCastDate="20-Apr-2025 10:00:00")
        frame = normalise_filings([original, restated])
        return assign_versions(attach_availability(frame, TradingCalendar(SESSIONS)))

    def test_versions_are_numbered_in_broadcast_order(self):
        frame = self.two_versions()
        self.assertEqual(list(frame["Version"]), [1, 2])

    def test_only_later_filings_are_restatements(self):
        frame = self.two_versions()
        self.assertEqual(list(frame["Is_Restatement"]), [False, True])

    def test_both_versions_are_retained(self):
        """Overwriting version 1 would erase what was knowable in 2024."""
        self.assertEqual(len(self.two_versions()), 2)

    def test_version_count_is_recorded(self):
        self.assertEqual(set(self.two_versions()["Version_Count"]), {2})

    def test_consolidated_and_standalone_are_versioned_separately(self):
        frame = normalise_filings([
            raw(seqNumber="1", consolidated="Consolidated"),
            raw(seqNumber="2", consolidated="Non-Consolidated"),
        ])
        versioned = assign_versions(
            attach_availability(frame, TradingCalendar(SESSIONS))
        )
        self.assertEqual(set(versioned["Version"]), {1})


class PointInTimeTests(unittest.TestCase):
    def resolver(self):
        rows = [
            raw(seqNumber="1", toDate="31-Mar-2022",
                broadCastDate="16-May-2024 14:07:24"),
            raw(seqNumber="2", toDate="31-Mar-2023",
                broadCastDate="16-May-2024 14:07:24"),
            # Restatement of FY2022, published nearly a year later.
            raw(seqNumber="3", toDate="31-Mar-2022",
                broadCastDate="20-Apr-2025 10:00:00"),
        ]
        frame = assign_versions(
            attach_availability(normalise_filings(rows), TradingCalendar(SESSIONS))
        )
        return PointInTimeFilings(frame)

    def test_nothing_is_visible_before_the_broadcast(self):
        self.assertEqual(
            self.resolver().known_periods("INE002A01018", date(2024, 5, 16)), []
        )

    def test_filings_become_visible_on_the_next_session(self):
        periods = self.resolver().known_periods("INE002A01018", date(2024, 5, 17))
        self.assertEqual(len(periods), 2)

    def test_latest_known_is_the_most_recent_period(self):
        latest = self.resolver().latest_known("INE002A01018", date(2024, 5, 17))
        self.assertEqual(latest["period_end"], date(2023, 3, 31))

    def test_a_restatement_is_invisible_before_it_was_published(self):
        """The p0.md worked example. In 2024 the original must be returned even
        though a 2025 revision is the only version a live feed would show."""
        periods = self.resolver().known_periods("INE002A01018", date(2024, 5, 20))
        fy2022 = [p for p in periods if p["period_end"] == date(2022, 3, 31)][0]
        self.assertEqual(fy2022["version"], 1)
        self.assertEqual(fy2022["seq"], "1")

    def test_the_restatement_is_used_once_it_exists(self):
        periods = self.resolver().known_periods("INE002A01018", date(2025, 4, 21))
        fy2022 = [p for p in periods if p["period_end"] == date(2022, 3, 31)][0]
        self.assertEqual(fy2022["seq"], "3")

    def test_periods_are_returned_newest_first(self):
        periods = self.resolver().known_periods("INE002A01018", date(2024, 5, 17))
        self.assertGreater(periods[0]["period_end"], periods[1]["period_end"])

    def test_limit_truncates_to_the_most_recent_periods(self):
        periods = self.resolver().known_periods(
            "INE002A01018", date(2024, 5, 17), limit=1
        )
        self.assertEqual(len(periods), 1)

    def test_unknown_security_returns_nothing(self):
        self.assertEqual(
            self.resolver().known_periods("INE999Z01011", date(2024, 5, 17)), []
        )

    def test_coverage_counts_securities_with_visible_filings(self):
        resolver = self.resolver()
        self.assertEqual(resolver.coverage(date(2024, 5, 16)), 0)
        self.assertEqual(resolver.coverage(date(2024, 5, 17)), 1)

    def test_consolidated_is_preferred_over_standalone(self):
        rows = [
            raw(seqNumber="1", consolidated="Non-Consolidated"),
            raw(seqNumber="2", consolidated="Consolidated"),
        ]
        frame = assign_versions(
            attach_availability(normalise_filings(rows), TradingCalendar(SESSIONS))
        )
        latest = PointInTimeFilings(frame).latest_known(
            "INE002A01018", date(2024, 5, 17)
        )
        self.assertTrue(latest["consolidated"])


class MasterBridgeTests(unittest.TestCase):
    class FakeMaster:
        def security_id_for_isin(self, isin):
            return "INE002A01" if str(isin).startswith("INE002A01") else None

    def test_filings_resolve_through_the_bridged_security_id(self):
        frame = assign_versions(
            attach_availability(
                normalise_filings([raw()]), TradingCalendar(SESSIONS)
            )
        )
        resolver = PointInTimeFilings(frame, master=self.FakeMaster())
        self.assertIsNotNone(resolver.latest_known("INE002A01", date(2024, 5, 17)))


class StoreTests(unittest.TestCase):
    class StubNSE:
        def __init__(self, records):
            self.records = records
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def financial_results(self, segment=None, period=None, from_date=None,
                              to_date=None, **kwargs):
            self.calls.append((from_date.year, period))
            return self.records

    def test_fetch_queries_each_year_and_caches(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        stub = self.StubNSE([raw()])
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "filings.csv"
            store = FilingStore(path, nse_factory=lambda folder: stub)
            frame = store.fetch(2023, 2024)
            self.assertEqual([call[0] for call in stub.calls], [2023, 2024])
            self.assertTrue(path.exists())
            self.assertFalse(frame.empty)

    def test_loading_a_missing_cache_returns_the_schema(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as tmp:
            frame = FilingStore(Path(tmp) / "absent.csv").load()
            self.assertTrue(frame.empty)
            self.assertIn("XBRL_URL", frame.columns)


if __name__ == "__main__":
    unittest.main()
