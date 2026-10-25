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


def filing(symbol, quarter, broadcast, *, consolidated=True, revenue=100, net_profit=10):
    """One stored filing, as `recent_filed_results` serves it (times in UTC)."""
    return {
        "symbol": symbol,
        "period_end": quarter,
        "is_consolidated": consolidated,
        "broadcast_at": broadcast,
        "revenue": revenue,
        "net_profit": net_profit,
    }


class FiledResultsTests(unittest.TestCase):
    def events(self, rows, universe=frozenset(COMPANIES)):
        return filed_results_events(rows, set(universe), COMPANIES, since=SINCE)

    def test_one_event_per_quarter_timed_at_the_first_broadcast(self):
        events = self.events(
            [
                filing("AAA", "2026-09-30", "2026-10-08T16:37:33+00:00"),
                filing("AAA", "2026-09-30", "2026-10-08T22:07:30+05:30", consolidated=False),
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
        # Stored from a revision alone: no broadcast to time it by.
        self.assertEqual(self.events([filing("AAA", "2026-06-30", None)]), [])

    def test_a_filing_that_parsed_to_nothing_is_not_announced(self):
        # The stock page would have nothing to show for it.
        self.assertEqual(
            self.events(
                [filing("AAA", "2026-09-30", "2026-10-08T10:00:00+00:00",
                        revenue=None, net_profit=None)]
            ),
            [],
        )

    def test_a_filing_from_before_the_window_is_not_announced_again(self):
        self.assertEqual(
            self.events([filing("AAA", "2026-06-30", "2026-07-20T12:30:00+00:00")]), []
        )

    def test_a_late_filing_for_an_old_quarter_is_not_this_seasons_result(self):
        self.assertEqual(
            self.events([filing("AAA", "2025-06-30", "2026-10-08T04:30:00+00:00")]), []
        )

    def test_a_company_with_no_stock_page_is_left_out(self):
        self.assertEqual(
            self.events([filing("ZZZ", "2026-09-30", "2026-10-08T04:30:00+00:00")]), []
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
    def __init__(self, market="NSE", *, deployed=True, filings=(), filings_error=None):
        self.market = market
        self.deployed = deployed
        self.filings = list(filings)
        self.filings_error = filings_error
        self.filings_asked = []
        self.inserted = []
        self.pruned_before = None

    def recent_filed_results(self, since):
        self.filings_asked.append(since)
        if self.filings_error is not None:
            raise self.filings_error
        return self.filings

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
    filings = [
        filing("AAA", "2026-09-30", "2026-10-08T16:37:33+00:00"),
        filing("NEW", "2026-09-30", "2026-10-09T05:30:00+00:00"),
    ]

    def test_a_market_with_a_filing_index_announces_from_the_stored_filings(self):
        repo = FakeRepository("NSE", filings=self.filings)
        counts = run(repo, now=NOW)
        self.assertEqual(repo.filings_asked, ["2026-10-05T12:00:00+00:00"])
        self.assertEqual(
            sorted((e["kind"], e["symbol"]) for e in repo.inserted),
            [("results", "AAA"), ("results", "NEW"), ("transcript", "BBB")],
        )
        self.assertEqual(counts["results"], 2)
        self.assertEqual(counts["transcript"], 1)
        self.assertEqual(counts["written"], 3)
        self.assertEqual(repo.pruned_before, "2026-04-15T12:00:00+00:00")

    def test_a_market_without_one_announces_from_the_stored_statements(self):
        repo = FakeRepository("US", filings_error=AssertionError("no filings here"))
        counts = run(repo, now=NOW)
        self.assertEqual(repo.filings_asked, [])
        results = [e for e in repo.inserted if e["kind"] == "results"]
        self.assertEqual(
            sorted((e["symbol"], e["baseline"]) for e in results),
            [("AAA", False), ("BBB", True)],
        )
        self.assertEqual(counts["results"], 1)
        self.assertEqual(counts["baseline"], 1)

    def test_a_bse_only_company_announces_from_its_stored_statements(self):
        repo = FakeRepository("NSE", filings=self.filings)
        repo.financial_statement_state = lambda: {
            # An NSE company's statements are not an event; its filings are.
            "AAA": {"latest_quarter": "2026-09-30", "fetched_at": "2026-10-10T00:00:00+00:00"},
            "BSEONLY.BO": {"latest_quarter": "2026-09-30", "fetched_at": "2026-10-10T00:00:00+00:00"},
        }
        repo.recorded_event_keys = lambda kind: {"BSEONLY.BO": "2026-06-30"}
        run(repo, now=NOW)
        vendor = [e for e in repo.inserted if e["detail"].get("source") == "vendor"]
        self.assertEqual([(e["symbol"], e["baseline"]) for e in vendor], [("BSEONLY.BO", False)])

    def test_unreadable_filings_still_record_the_other_kinds(self):
        repo = FakeRepository("NSE", filings_error=RuntimeError("relation does not exist"))
        with self.assertLogs("workers.market_events", level="WARNING") as logs:
            run(repo, now=NOW)
        self.assertIn("quarterly_filings_schema.sql", logs.output[0])
        self.assertEqual([e["kind"] for e in repo.inserted], ["transcript"])

    def test_an_undeployed_table_warns_and_writes_nothing(self):
        repo = FakeRepository("NSE", deployed=False, filings=self.filings)
        with self.assertLogs("workers.market_events", level="WARNING") as logs:
            counts = run(repo, now=NOW)
        self.assertIn("notifications_schema.sql", logs.output[0])
        self.assertEqual(repo.inserted, [])
        self.assertEqual(counts["written"], 0)

    def test_dry_run_writes_nothing(self):
        repo = FakeRepository("NSE", filings=self.filings)
        counts = run(repo, now=NOW, dry_run=True)
        self.assertEqual(repo.inserted, [])
        self.assertEqual(counts["results"], 2)


if __name__ == "__main__":
    unittest.main()
