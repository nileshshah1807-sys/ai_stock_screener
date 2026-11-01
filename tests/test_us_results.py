"""The US Results page's rows: derived from stored statements, written once, never mixed with NSE's."""

import unittest

from workers.us_results import filing_rows, quarter_lines, run, stocks_to_read

PERIODS = ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]


def statement(symbol="AAPL", revenue=(94, 102, 143, 111, 109), net_profit=(23, 27, 42, 29, 29), fetched_at="2026-10-31T03:00:00+00:00"):
    return {
        "symbol": symbol,
        "fetched_at": fetched_at,
        "statements": {"quarterly": {"income": {"periods": PERIODS, "rows": {
            "revenue": list(revenue), "net_profit": list(net_profit), "pbt": [28, 32, 51, 35, 36],
            "interest": [None] * 5, "eps": [1.5] * 5,
        }}}},
    }


class QuarterLinesTests(unittest.TestCase):
    def test_lines_are_the_vendors_rows_with_pat(self):
        lines = quarter_lines(statement()["statements"]["quarterly"]["income"]["rows"], 4)
        self.assertEqual((lines["revenue"], lines["net_profit"], lines["pat"], lines["interest"]), (109, 29, 29, None))
        self.assertIsNone(lines["depreciation"])

    def test_a_nan_or_text_value_is_not_reported(self):
        lines = quarter_lines({"revenue": [float("nan")], "net_profit": ["n/a"]}, 0)
        self.assertEqual((lines["revenue"], lines["net_profit"], lines["pat"]), (None, None, None))


class FilingRowTests(unittest.TestCase):
    def rows(self, stored=(), first_seen=None, **kwargs):
        return filing_rows(statement(**kwargs), set(stored), first_seen or {}, "Apple Inc.")

    def test_each_new_quarter_is_one_consolidated_row_without_a_document(self):
        rows = self.rows()
        self.assertEqual([r["period_end"] for r in rows], PERIODS)
        row = rows[-1]
        self.assertEqual((row["is_consolidated"], row["document_url"], row["viewer_url"], row["company"]), (True, "", None, "Apple Inc."))
        self.assertEqual(row["lines"]["revenue"], 109)

    def test_a_stored_quarter_is_not_rewritten(self):
        self.assertEqual([r["period_end"] for r in self.rows(stored=PERIODS[:4])], ["2026-09-30"])

    def test_first_seen_is_the_bells_time_else_the_fetch(self):
        rows = self.rows(first_seen={("AAPL", "2026-09-30"): "2026-10-31T03:37:35+00:00"})
        self.assertEqual(rows[-1]["broadcast_at"], "2026-10-31T03:37:35+00:00")
        self.assertEqual(rows[0]["broadcast_at"], "2026-10-31T03:00:00+00:00")
        self.assertEqual(rows[-1]["filed_at"], rows[-1]["broadcast_at"])

    def test_a_quarter_with_neither_revenue_nor_profit_is_not_a_result(self):
        rows = self.rows(revenue=(None,) * 5, net_profit=(None, None, None, None, 5))
        self.assertEqual([r["period_end"] for r in rows], ["2026-09-30"])


class StocksToReadTests(unittest.TestCase):
    def test_only_stocks_with_a_later_quarter_than_stored(self):
        state = {
            "AAA": {"has_data": True, "latest_quarter": "2026-09-30"},
            "BBB": {"has_data": True, "latest_quarter": "2026-06-30"},
            "CCC": {"has_data": False, "latest_quarter": None},
            "DDD": {"has_data": True, "latest_quarter": "2026-06-30"},
        }
        self.assertEqual(stocks_to_read(state, {"AAA": "2026-06-30", "BBB": "2026-06-30"}), ["AAA", "DDD"])


class FakeRepo:
    def __init__(self, market="US", unreadable=False):
        self.market, self.unreadable, self.written = market, unreadable, []

    def quarterly_filing_state(self):
        if self.unreadable:
            raise RuntimeError("relation does not exist")
        return {("MSFT", "2026-06-30", True): {}}

    def financial_statement_state(self):
        return {"AAPL": {"has_data": True, "latest_quarter": "2026-09-30"}, "MSFT": {"has_data": True, "latest_quarter": "2026-06-30"}}

    def result_first_seen(self):
        return {}

    def snapshot_companies(self):
        return {"AAPL": "Apple Inc."}

    def financial_statement_rows(self, symbols):
        return [statement(symbol) for symbol in symbols]

    def upsert_quarterly_filings(self, rows):
        self.written += rows
        return len(rows)


class RunTests(unittest.TestCase):
    def test_new_quarters_are_written_for_the_stocks_that_gained_one(self):
        repo = FakeRepo()
        counts = run(repo)
        self.assertEqual((counts["stocks"], counts["written"]), (1, 5))
        self.assertEqual({row["symbol"] for row in repo.written}, {"AAPL"})

    def test_a_dry_run_writes_nothing(self):
        repo = FakeRepo()
        self.assertEqual((run(repo, dry_run=True)["rows"], repo.written), (5, []))

    def test_it_refuses_the_nse_market(self):
        repo = FakeRepo(market="NSE")
        with self.assertLogs("workers.us_results", "WARNING"):
            self.assertEqual(run(repo)["written"], 0)

    def test_a_missing_table_is_a_warning_not_a_failure(self):
        with self.assertLogs("workers.us_results", "WARNING"):
            self.assertEqual(run(FakeRepo(unreadable=True))["written"], 0)


if __name__ == "__main__":
    unittest.main()
