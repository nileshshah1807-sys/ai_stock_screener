"""A BSE-only company's filings reach the tables the NSE workers write."""

import unittest
from datetime import date, datetime
from unittest import mock

from tests.test_quarterly_results import _document
from tests.test_shareholding import ONWARD, ONWARD_HOLDERS, document
from workers import bse_filings, bse_source

TODAY = date(2026, 10, 25)
RESULTS_URL = "https://bse.example/results.xml"
PATTERN_URL = "https://bse.example/pattern.xml"


def _results(start, end):
    common = {"period_end": date(2026, 9, 30), "consolidated": False, "taxonomy": "INDAS",
              "filed_at": datetime(2026, 10, 24, 18, 5), "company": "Tanfac Industries"}
    return [
        {**common, "symbol": "TANFACIND", "filing_id": "a1", "xbrl_url": RESULTS_URL},
        # Listed on NSE too: its NSE filing is the one stored.
        {**common, "symbol": "RELIANCE", "filing_id": "b2", "xbrl_url": "https://bse.example/r.xml"},
    ]


def _patterns(start, end):
    return [{"symbol": "TANFACIND", "period_end": date(2026, 9, 30), "filing_id": "s1",
             "filed_at": datetime(2026, 10, 20, 11, 0), "xbrl_url": PATTERN_URL,
             "company": "Tanfac Industries"}]


DOCUMENTS = {
    RESULTS_URL: _document(revenue=400.0, profit=50.0),
    PATTERN_URL: document(ONWARD, ONWARD_HOLDERS),
}


class FakeRepository:
    market = "NSE"

    def __init__(self):
        self.filings, self.patterns = [], []

    def latest_snapshot_symbols(self):
        return ["RELIANCE", "TANFACIND.BO"]

    def quarterly_filing_state(self):
        return {("RELIANCE", "2026-09-30", True): {"seq_id": "1", "parser_version": 99}}

    def upsert_quarterly_filings(self, rows):
        self.filings += rows

    def shareholding_state(self):
        return {}

    def upsert_shareholding_patterns(self, rows):
        self.patterns += rows


class BseFilingsTests(unittest.TestCase):
    def test_bse_only_filings_are_stored_under_the_run_symbol(self):
        repo = FakeRepository()
        with mock.patch.object(bse_source, "results_filings", _results), \
                mock.patch.object(bse_source, "shareholding_filings", _patterns), \
                mock.patch.object(bse_source, "fetch_document", DOCUMENTS.get), \
                self.assertLogs("workers", level="WARNING"):  # redraw and basis need a real repo
            counts = bse_filings.run(repo, today=TODAY)

        self.assertEqual([row["symbol"] for row in repo.filings], ["TANFACIND.BO"])
        filing = repo.filings[0]
        self.assertEqual((filing["period_end"], filing["is_consolidated"]), ("2026-09-30", False))
        self.assertEqual(filing["broadcast_at"], "2026-10-24T18:05:00+05:30")
        self.assertIsNotNone(filing["lines"].get("revenue"))
        self.assertEqual([row["symbol"] for row in repo.patterns], ["TANFACIND.BO"])
        self.assertEqual(counts["shareholding"]["stored"], 1)

    def test_an_unwritten_source_stores_nothing_and_says_so(self):
        repo = FakeRepository()
        with self.assertLogs("workers.bse_filings", level="WARNING") as logs:
            counts = bse_filings.run(repo, today=TODAY)
        self.assertEqual(counts["status"], "source_not_written")
        self.assertIn("bse_source.py", logs.output[0])
        self.assertEqual((repo.filings, repo.patterns), ([], []))


if __name__ == "__main__":
    unittest.main()
