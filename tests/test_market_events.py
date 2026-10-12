"""Events for the notification bell, derived from what other jobs collect.

The rules worth pinning: an event is announced once, a restatement is not a
result, and a market with no filing index must not announce a result for every
company the first time it is looked at.
"""

import unittest
from datetime import UTC, datetime

from workers.market_events import (
    KIND_RESULTS,
    filed_results_events,
    run,
    statement_results_events,
    transcript_events,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
SINCE = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
COMPANIES = {"AAA": "Alpha Ltd", "BBB": "Beta Ltd"}


def filing(symbol, quarter, broadcast, *, consolidated=True):
    return {
        "symbol": symbol,
        "qe_Date": quarter,
        "broadcast_Date": broadcast,
        "consolidated": "Consolidated" if consolidated else "Standalone",
    }


class FiledResultsTests(unittest.TestCase):
    def events(self, records, universe=frozenset(COMPANIES)):
        return filed_results_events(
            records, set(universe), COMPANIES, since=SINCE, timezone="Asia/Kolkata"
        )

    def test_one_event_per_quarter_timed_at_the_first_broadcast(self):
        events = self.events(
            [
                filing("AAA", "30-SEP-2026", "08-Oct-2026 22:07:33"),
                filing("AAA", "30-SEP-2026", "08-Oct-2026 22:07:30", consolidated=False),
            ]
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(
            (event["symbol"], event["company"], event["kind"], event["event_key"]),
            ("AAA", "Alpha Ltd", KIND_RESULTS, "2026-09-30"),
        )
        # 22:07:30 in India is 16:37:30 UTC.
        self.assertEqual(event["occurred_at"], "2026-10-08T16:37:30+00:00")
        self.assertEqual(event["detail"]["period"], "2026-09-30")
        self.assertFalse(event["baseline"])

    def test_a_revision_is_not_a_result(self):
        self.assertEqual(self.events([filing("AAA", "30-JUN-2026", None)]), [])

    def test_a_filing_from_before_the_window_is_not_announced_again(self):
        self.assertEqual(
            self.events([filing("AAA", "30-JUN-2026", "20-Jul-2026 18:00:00")]), []
        )

    def test_a_late_filing_for_an_old_quarter_is_not_this_seasons_result(self):
        self.assertEqual(
            self.events([filing("AAA", "30-JUN-2025", "08-Oct-2026 10:00:00")]), []
        )

    def test_a_company_with_no_stock_page_is_left_out(self):
        self.assertEqual(
            self.events([filing("ZZZ", "30-SEP-2026", "08-Oct-2026 10:00:00")]), []
        )


class StatementResultsTests(unittest.TestCase):
    state = {
        "AAA": {"latest_quarter": "2026-09-30", "fetched_at": "2026-10-12T03:10:00+00:00"},
        "BBB": {"latest_quarter": "2026-06-30", "fetched_at": "2026-10-01T03:10:00+00:00"},
        "CCC": {"latest_quarter": None, "fetched_at": "2026-10-01T03:10:00+00:00"},
    }

    def test_a_later_quarter_than_recorded_is_announced(self):
        events = statement_results_events(
            self.state, {"AAA": "2026-06-30", "BBB": "2026-06-30"}, COMPANIES
        )
        self.assertEqual([(e["symbol"], e["event_key"]) for e in events], [("AAA", "2026-09-30")])
        self.assertFalse(events[0]["baseline"])
        # The vendor gives no publication time; it is when the job saw it.
        self.assertEqual(events[0]["occurred_at"], "2026-10-12T03:10:00+00:00")

    def test_a_first_sighting_is_recorded_but_not_announced(self):
        events = statement_results_events(self.state, {}, COMPANIES)
        self.assertEqual(sorted(e["symbol"] for e in events), ["AAA", "BBB"])
        self.assertTrue(all(e["baseline"] for e in events))


class TranscriptTests(unittest.TestCase):
    def test_keyed_by_call_date_and_timed_when_stored(self):
        events = transcript_events(
            [
                {"symbol": "aaa", "quarter": "2026-09-30", "call_date": "2026-10-09",
                 "created_at": "2026-10-09T17:37:09+00:00"},
                {"symbol": "BBB", "quarter": None, "call_date": None,
                 "created_at": "2026-10-10T08:00:00+00:00"},
                {"symbol": "", "created_at": "2026-10-10T08:00:00+00:00"},
            ],
            COMPANIES,
        )
        self.assertEqual(
            [(e["symbol"], e["event_key"]) for e in events],
            [("AAA", "2026-10-09"), ("BBB", "2026-10-10")],
        )
        self.assertEqual(events[0]["detail"], {"call_date": "2026-10-09", "quarter": "2026-09-30"})


class FakeRepository:
    def __init__(self, market="NSE", *, deployed=True):
        self.market = market
        self.deployed = deployed
        self.inserted = []
        self.pruned_before = None

    def recorded_event_keys(self, kind):
        if not self.deployed:
            raise RuntimeError("relation market_events does not exist")
        return {"AAA": "2026-06-30"}

    def snapshot_companies(self):
        return dict(COMPANIES)

    def new_listing_symbols(self):
        return ["NEW"]

    def financial_statement_state(self):
        return StatementResultsTests.state

    def recent_transcripts(self, since):
        return [{"symbol": "BBB", "quarter": "2026-09-30", "call_date": "2026-10-09",
                 "created_at": "2026-10-09T17:37:09+00:00"}]

    def insert_market_events(self, rows):
        self.inserted.extend(rows)
        return len(rows)

    def prune_market_events(self, before):
        self.pruned_before = before


class RunTests(unittest.TestCase):
    records = [
        filing("AAA", "30-SEP-2026", "08-Oct-2026 22:07:33"),
        filing("NEW", "30-SEP-2026", "09-Oct-2026 11:00:00"),
    ]

    def test_a_market_with_a_filing_index_announces_from_it(self):
        repo = FakeRepository("NSE")
        asked = []

        def loader(start, end):
            asked.append((start.isoformat(), end.isoformat()))
            return self.records

        counts = run(repo, now=NOW, index_records_loader=loader)
        self.assertEqual(asked, [("2026-10-05", "2026-10-12")])
        self.assertEqual(
            sorted((e["kind"], e["symbol"]) for e in repo.inserted),
            [("results", "AAA"), ("results", "NEW"), ("transcript", "BBB")],
        )
        self.assertEqual(counts["results"], 2)
        self.assertEqual(counts["transcript"], 1)
        self.assertEqual(counts["written"], 3)
        self.assertEqual(repo.pruned_before, "2026-04-15T12:00:00+00:00")

    def test_a_market_without_one_announces_from_the_stored_statements(self):
        repo = FakeRepository("US")

        def loader(start, end):
            raise AssertionError("no filing index for this market")

        counts = run(repo, now=NOW, index_records_loader=loader)
        results = [e for e in repo.inserted if e["kind"] == "results"]
        self.assertEqual(
            sorted((e["symbol"], e["baseline"]) for e in results),
            [("AAA", False), ("BBB", True)],
        )
        self.assertEqual(counts["results"], 1)
        self.assertEqual(counts["baseline"], 1)

    def test_an_unreadable_index_still_records_the_other_kinds(self):
        repo = FakeRepository("NSE")

        def loader(start, end):
            raise ConnectionError("blocked")

        with self.assertLogs("workers.market_events", level="WARNING"):
            run(repo, now=NOW, index_records_loader=loader)
        self.assertEqual([e["kind"] for e in repo.inserted], ["transcript"])

    def test_an_undeployed_table_warns_and_writes_nothing(self):
        repo = FakeRepository("NSE", deployed=False)
        with self.assertLogs("workers.market_events", level="WARNING") as logs:
            counts = run(repo, now=NOW, index_records_loader=lambda *_: self.records)
        self.assertIn("notifications_schema.sql", logs.output[0])
        self.assertEqual(repo.inserted, [])
        self.assertEqual(counts["written"], 0)

    def test_dry_run_writes_nothing(self):
        repo = FakeRepository("NSE")
        counts = run(repo, now=NOW, index_records_loader=lambda *_: self.records, dry_run=True)
        self.assertEqual(repo.inserted, [])
        self.assertEqual(counts["results"], 2)


if __name__ == "__main__":
    unittest.main()
