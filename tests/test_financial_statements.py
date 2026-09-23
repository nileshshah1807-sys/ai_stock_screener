"""Normalising vendor statements for the stock page's Financials tab.

The rules worth pinning are the ones a display layer would silently get wrong:
an unreported line must stay null rather than read as zero, a derived line must
not be computed from a missing input, and the refresh selector must re-ask a
symbol only when its statements can actually have changed.
"""

import unittest
from datetime import date

import numpy as np
import pandas as pd

from workers.financial_statements import (
    BALANCE_LINES,
    INCOME_LINES,
    build_payload,
    extract_statement,
    run,
    select_due,
)


def frame(rows, periods):
    """A Yahoo-shaped frame: line items down, newest period first across."""
    columns = [pd.Timestamp(p) for p in periods]
    return pd.DataFrame(rows, index=columns).T


QUARTERS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]


class ExtractStatementTests(unittest.TestCase):
    def test_periods_ascend_and_rows_align(self):
        income = frame(
            {
                "Total Revenue": [500, 400, 300, 200, 100],
                "EBITDA": [50, 40, 30, 20, 10],
                "Net Income": [25, 20, 15, 10, 5],
            },
            QUARTERS,
        )
        out = extract_statement(income, INCOME_LINES, "income")
        self.assertEqual(out["periods"], sorted(QUARTERS))
        self.assertEqual(out["rows"]["revenue"], [100, 200, 300, 400, 500])
        self.assertEqual(out["rows"]["expenses"], [90, 180, 270, 360, 450])

    def test_unreported_value_stays_null_and_blocks_derivation(self):
        income = frame(
            {
                "Total Revenue": [500, 400],
                "EBITDA": [np.nan, 40],
                "Net Income": [25, 20],
            },
            QUARTERS[:2],
        )
        out = extract_statement(income, INCOME_LINES, "income")
        # Ascending: Mar then Jun. Jun's EBITDA is missing, so its operating
        # profit is null and its expenses are not guessed as the whole revenue.
        self.assertEqual(out["rows"]["operating_profit"], [40, None])
        self.assertEqual(out["rows"]["expenses"], [360, None])

    def test_first_available_label_wins(self):
        income = frame(
            {"Operating Revenue": [10, 20], "Net Income Common Stockholders": [1, 2]},
            QUARTERS[:2],
        )
        out = extract_statement(income, INCOME_LINES, "income")
        self.assertEqual(out["rows"]["revenue"], [20, 10])
        self.assertEqual(out["rows"]["net_profit"], [2, 1])

    def test_padding_column_without_an_anchor_is_dropped(self):
        income = frame(
            {
                "Total Revenue": [500, np.nan],
                "Net Income": [25, np.nan],
                "Tax Provision": [5, 3],
            },
            QUARTERS[:2],
        )
        out = extract_statement(income, INCOME_LINES, "income")
        self.assertEqual(out["periods"], ["2026-06-30"])

    def test_lines_null_everywhere_are_omitted(self):
        income = frame(
            {"Total Revenue": [5, 6], "Net Income": [1, 1], "EBITDA": [np.nan, np.nan]},
            QUARTERS[:2],
        )
        out = extract_statement(income, INCOME_LINES, "income")
        self.assertNotIn("operating_profit", out["rows"])
        self.assertNotIn("expenses", out["rows"])

    def test_rounds_half_up_to_whole_units_and_eps_to_two_places(self):
        income = frame(
            {"Total Revenue": [2.5], "Net Income": [1.0], "Diluted EPS": [1.005]},
            QUARTERS[:1],
        )
        out = extract_statement(income, INCOME_LINES, "income")
        self.assertEqual(out["rows"]["revenue"], [3])
        self.assertEqual(out["rows"]["eps"], [1.01])

    def test_net_interest_income_is_kept_only_for_lenders(self):
        industrial = frame(
            {"Total Revenue": [10], "EBITDA": [3], "Net Income": [1],
             "Net Interest Income": [2]},
            QUARTERS[:1],
        )
        bank = frame(
            {"Total Revenue": [10], "Net Income": [1], "Net Interest Income": [6]},
            QUARTERS[:1],
        )
        self.assertNotIn(
            "net_interest_income",
            extract_statement(industrial, INCOME_LINES, "income")["rows"],
        )
        self.assertEqual(
            extract_statement(bank, INCOME_LINES, "income")["rows"]["net_interest_income"],
            [6],
        )

    def test_balance_sheet_derivations_need_every_input(self):
        balance = frame(
            {
                "Total Assets": [1000, 900],
                "Stockholders Equity": [600, 500],
                "Capital Stock": [100, 100],
                "Total Debt": [150, 200],
                "Net PPE": [300, 280],
                "Investments And Advances": [200, 180],
                "Construction In Progress": [50, np.nan],
            },
            ["2026-03-31", "2025-03-31"],
        )
        out = extract_statement(balance, BALANCE_LINES, "balance")
        self.assertEqual(out["rows"]["reserves"], [400, 500])
        self.assertEqual(out["rows"]["other_liabilities"], [200, 250])
        # 2025 has no CWIP reported, so "other assets" is unknown, not 440.
        self.assertEqual(out["rows"]["other_assets"], [None, 450])

    def test_empty_or_missing_frame(self):
        self.assertEqual(
            extract_statement(None, INCOME_LINES, "income"), {"periods": [], "rows": {}}
        )
        self.assertEqual(
            extract_statement(pd.DataFrame(), INCOME_LINES, "income"),
            {"periods": [], "rows": {}},
        )


class BuildPayloadTests(unittest.TestCase):
    def test_reports_latest_periods_and_has_data(self):
        payload = build_payload({
            "income_stmt": frame(
                {"Total Revenue": [10, 8], "Net Income": [2, 1]},
                ["2026-03-31", "2025-03-31"],
            ),
            "quarterly_income_stmt": frame(
                {"Total Revenue": [3, 2], "Net Income": [1, 1]}, QUARTERS[:2]
            ),
            "balance_sheet": None,
            "cashflow": None,
        })
        self.assertTrue(payload["has_data"])
        self.assertEqual(payload["latest_annual"], "2026-03-31")
        self.assertEqual(payload["latest_quarter"], "2026-06-30")
        self.assertEqual(payload["statements"]["annual"]["balance"]["periods"], [])

    def test_nothing_reported(self):
        payload = build_payload({})
        self.assertFalse(payload["has_data"])
        self.assertIsNone(payload["latest_annual"])
        self.assertIsNone(payload["latest_quarter"])


class SelectDueTests(unittest.TestCase):
    today = date(2026, 9, 23)

    def test_never_fetched_first_then_oldest(self):
        state = {
            "OLD": {"fetched_at": "2026-07-01T00:00:00+00:00", "latest_quarter": "2026-06-30"},
            "OLDER": {"fetched_at": "2026-06-01T00:00:00+00:00", "latest_quarter": "2026-06-30"},
            "FRESH": {"fetched_at": "2026-09-20T00:00:00+00:00", "latest_quarter": "2026-06-30"},
        }
        due = select_due(["OLD", "FRESH", "NEW", "OLDER"], state, self.today)
        self.assertEqual(due, ["NEW", "OLDER", "OLD"])

    def test_results_due_rechecks_weekly_not_daily(self):
        stale_quarter = {"latest_quarter": "2026-03-31"}  # 176 days ago
        state = {
            "WEEK": {**stale_quarter, "fetched_at": "2026-09-10T00:00:00+00:00"},
            "YESTERDAY": {**stale_quarter, "fetched_at": "2026-09-22T00:00:00+00:00"},
        }
        self.assertEqual(select_due(["WEEK", "YESTERDAY"], state, self.today), ["WEEK"])

    def test_limit_bounds_the_run(self):
        self.assertEqual(select_due(["A", "B", "C"], {}, self.today, limit=2), ["A", "B"])


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol
        self.income_stmt = frame(
            {"Total Revenue": [10], "Net Income": [1]}, ["2026-03-31"]
        )
        self.quarterly_income_stmt = pd.DataFrame()
        self.balance_sheet = pd.DataFrame()

    @property
    def cashflow(self):
        raise RuntimeError("blocked")


class FakeRepository:
    market = "NSE"

    def __init__(self):
        self.written = []

    def latest_snapshot_symbols(self):
        return ["TCS", "INFY"]

    def financial_statement_state(self):
        return {"INFY": {"fetched_at": "2026-09-22T00:00:00+00:00", "latest_quarter": "2026-06-30"}}

    def upsert_financial_statements(self, rows):
        self.written.extend(rows)
        return len(rows)


class RunTests(unittest.TestCase):
    def test_fetches_only_due_symbols_and_survives_a_failing_statement(self):
        repo = FakeRepository()
        seen = []

        def factory(ticker):
            seen.append(ticker)
            return FakeTicker(ticker)

        counts = run(repo, ticker_factory=factory, pause_seconds=0, today=date(2026, 9, 23))
        self.assertEqual(seen, ["TCS.NS"])
        self.assertEqual(counts["written"], 1)
        row = repo.written[0]
        self.assertEqual(row["symbol"], "TCS")
        self.assertEqual(row["currency"], "INR")
        self.assertTrue(row["has_data"])
        self.assertEqual(row["statements"]["annual"]["cashflow"]["periods"], [])

    def test_dry_run_writes_nothing(self):
        repo = FakeRepository()
        run(repo, ticker_factory=FakeTicker, pause_seconds=0, dry_run=True,
            today=date(2026, 9, 23))
        self.assertEqual(repo.written, [])


if __name__ == "__main__":
    unittest.main()
