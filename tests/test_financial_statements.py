"""Normalising vendor statements for the stock page's Financials tab.

The rules worth pinning are the ones a display layer would silently get wrong:
an unreported line must stay null rather than read as zero, a derived line must
not be computed from a missing input, and the refresh selector must re-ask a
symbol only when its statements can actually have changed.
"""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

from screener.quarterly_results import normalise_index, parse_quarter_statement
from workers.financial_statements import (
    BALANCE_LINES,
    INCOME_LINES,
    SOURCE,
    SOURCE_WITH_FILINGS,
    FiledQuarters,
    build_payload,
    extract_statement,
    load_filed_quarters,
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

    def test_time_budget_stops_cleanly_and_reports_the_remainder(self):
        repo = FakeRepository()
        repo.latest_snapshot_symbols = lambda: ["A", "B", "C", "D"]
        ticks = iter([0, 0, 10, 20, 30, 40])  # start, then one tick per symbol check
        counts = run(
            repo,
            ticker_factory=FakeTicker,
            pause_seconds=0,
            time_budget_seconds=15,
            clock=lambda: next(ticks),
            today=date(2026, 9, 23),
        )
        self.assertEqual([row["symbol"] for row in repo.written], ["A", "B"])
        self.assertEqual(counts["deferred"], 2)

    def test_dry_run_writes_nothing(self):
        repo = FakeRepository()
        run(repo, ticker_factory=FakeTicker, pause_seconds=0, dry_run=True,
            today=date(2026, 9, 23))
        self.assertEqual(repo.written, [])


ARCHIVE = "https://archive.example/xbrl"


def filing(symbol, quarter, seq, *, consolidated=True, taxonomy="INDAS"):
    """One row of the exchange's filing index, as it is served."""
    return {
        "symbol": symbol,
        "qe_Date": quarter,
        "consolidated": "Consolidated" if consolidated else "Standalone",
        "seq_Id": str(seq),
        "broadcast_Date": "08-Oct-2026 22:07:33",
        "xbrl": f"{ARCHIVE}/INTEGRATED_FILING_{taxonomy}_{seq}_WEB.xml",
    }


def document(**lines):
    """A results document carrying the named lines in the quarter's context."""
    tags = {
        "revenue": "RevenueFromOperations",
        "other_income": "OtherIncome",
        "interest": "FinanceCosts",
        "depreciation": "DepreciationDepletionAndAmortisationExpense",
        "pbt": "ProfitBeforeTax",
        "tax": "TaxExpense",
        "profit": "ProfitLossForPeriod",
        "owners_profit": "ProfitOrLossAttributableToOwnersOfParent",
        "eps": "DilutedEarningsLossPerShareFromContinuingOperations",
    }
    facts = "".join(
        f'<in-capmkt:{tags[key]} contextRef="OneD" unitRef="INR">{value}'
        f"</in-capmkt:{tags[key]}>"
        for key, value in lines.items()
    )
    return f"<xbrli:xbrl>{facts}</xbrli:xbrl>"


def statement(periods, **rows):
    """A stored quarterly income statement, periods ascending."""
    rows.setdefault(
        "expenses",
        [r - o for r, o in zip(rows["revenue"], rows["operating_profit"], strict=True)]
        if "operating_profit" in rows
        else [None] * len(periods),
    )
    return {"periods": list(periods), "rows": rows}


def filed_quarters(filings, documents):
    asked = []

    def fetch_document(url):
        asked.append(url.rsplit("_", 2)[-2])
        return documents.get(asked[-1])

    quarters = FiledQuarters(normalise_index(filings), fetch_document=fetch_document)
    quarters.asked = asked
    return quarters


# Vendor through June; the company has since filed September.
VENDOR = {
    "revenue": [900, 1000],
    "operating_profit": [190, 215],
    "pbt": [170, 200],
    "interest": [5, 5],
    "depreciation": [15, 10],
    "net_profit": [120, 150],
    "eps": [1.2, 1.5],
}
JUNE = document(
    revenue=1000, pbt=200, interest=5, depreciation=10, profit=155,
    owners_profit=150, eps=1.5,
)
SEPTEMBER = document(
    revenue=1100, pbt=230, interest=6, depreciation=11, profit=176,
    owners_profit=170, eps=1.7,
)


class FiledQuarterTests(unittest.TestCase):
    def test_a_filed_quarter_the_vendor_lacks_is_added(self):
        quarters = filed_quarters(
            [filing("AAA", "30-JUN-2026", 1), filing("AAA", "30-SEP-2026", 2)],
            {"1": JUNE, "2": SEPTEMBER},
        )
        extended = quarters.extend(
            "AAA", statement(["2026-03-31", "2026-06-30"], **VENDOR)
        )
        self.assertEqual(
            extended["periods"], ["2026-03-31", "2026-06-30", "2026-09-30"]
        )
        self.assertEqual(extended["filed_periods"], ["2026-09-30"])
        rows = extended["rows"]
        self.assertEqual(rows["revenue"], [900, 1000, 1100])
        self.assertEqual(rows["pbt"], [170, 200, 230])
        # Profit is the owners' share, as the vendor's net income is.
        self.assertEqual(rows["net_profit"], [120, 150, 170])
        self.assertEqual(rows["eps"], [1.2, 1.5, 1.7])
        # Operating profit is profit before tax, interest and depreciation.
        self.assertEqual(rows["operating_profit"], [190, 215, 247])
        self.assertEqual(rows["expenses"], [710, 785, 853])

    def test_a_hole_in_the_vendors_history_is_filled(self):
        quarters = filed_quarters(
            [filing("AAA", "30-JUN-2026", 1), filing("AAA", "31-MAR-2026", 3)],
            {"1": JUNE, "3": document(revenue=950, pbt=180, interest=5, depreciation=12,
                                      profit=130, eps=1.3)},
        )
        extended = quarters.extend(
            "AAA", statement(["2025-12-31", "2026-06-30"], **VENDOR)
        )
        self.assertEqual(
            extended["periods"], ["2025-12-31", "2026-03-31", "2026-06-30"]
        )
        self.assertEqual(extended["rows"]["revenue"], [900, 950, 1000])
        # No owners' share was filed for that quarter: the period's profit.
        self.assertEqual(extended["rows"]["net_profit"], [120, 130, 150])

    def test_a_line_that_means_something_else_at_the_vendor_stays_unreported(self):
        # The vendor's operating profit leaves depreciation out, so the filed
        # figure is not the same line and cannot sit beside it.
        vendor = {**VENDOR, "operating_profit": [175, 205]}
        quarters = filed_quarters(
            [filing("AAA", "30-JUN-2026", 1), filing("AAA", "30-SEP-2026", 2)],
            {"1": JUNE, "2": SEPTEMBER},
        )
        extended = quarters.extend(
            "AAA", statement(["2026-03-31", "2026-06-30"], **vendor)
        )
        self.assertEqual(extended["rows"]["revenue"], [900, 1000, 1100])
        self.assertEqual(extended["rows"]["operating_profit"], [175, 205, None])
        self.assertEqual(extended["rows"]["expenses"], [725, 795, None])

    def test_a_line_the_vendor_does_not_report_is_not_introduced(self):
        vendor = {k: v for k, v in VENDOR.items() if k != "depreciation"}
        quarters = filed_quarters(
            [filing("AAA", "30-JUN-2026", 1), filing("AAA", "30-SEP-2026", 2)],
            {"1": JUNE, "2": SEPTEMBER},
        )
        extended = quarters.extend(
            "AAA", statement(["2026-03-31", "2026-06-30"], **vendor)
        )
        self.assertNotIn("depreciation", extended["rows"])

    def test_the_basis_is_the_one_that_reproduces_the_vendors_revenue(self):
        standalone = document(revenue=1000, pbt=200, interest=5, depreciation=10,
                              profit=150, eps=1.5)
        quarters = filed_quarters(
            [
                filing("AAA", "30-JUN-2026", 1, consolidated=True),
                filing("AAA", "30-JUN-2026", 2, consolidated=False),
                filing("AAA", "30-SEP-2026", 3, consolidated=True),
                filing("AAA", "30-SEP-2026", 4, consolidated=False),
            ],
            {
                "1": document(revenue=4000, pbt=900, profit=700),
                "2": standalone,
                "3": document(revenue=4400, pbt=990, profit=770),
                "4": document(revenue=1100, pbt=230, interest=6, depreciation=11,
                              profit=170, eps=1.7),
            },
        )
        extended = quarters.extend(
            "AAA", statement(["2026-03-31", "2026-06-30"], **VENDOR)
        )
        self.assertEqual(extended["rows"]["revenue"], [900, 1000, 1100])
        self.assertNotIn("3", quarters.asked)

    def test_a_filing_that_cannot_be_reconciled_adds_nothing(self):
        vendor = statement(["2026-03-31", "2026-06-30"], **VENDOR)
        quarters = filed_quarters(
            [filing("AAA", "30-JUN-2026", 1), filing("AAA", "30-SEP-2026", 2)],
            {"1": document(revenue=1200, pbt=200, profit=150), "2": SEPTEMBER},
        )
        self.assertIs(quarters.extend("AAA", vendor), vendor)

    def test_nothing_is_added_without_a_quarter_both_sources_have(self):
        vendor = statement(["2025-12-31", "2026-03-31"], **VENDOR)
        quarters = filed_quarters(
            [filing("AAA", "30-SEP-2026", 2)], {"2": SEPTEMBER}
        )
        self.assertIs(quarters.extend("AAA", vendor), vendor)
        self.assertEqual(quarters.asked, [])

    def test_a_company_with_nothing_new_filed_costs_no_request(self):
        vendor = statement(["2026-03-31", "2026-06-30"], **VENDOR)
        quarters = filed_quarters([filing("AAA", "30-JUN-2026", 1)], {"1": JUNE})
        self.assertIs(quarters.extend("AAA", vendor), vendor)
        self.assertIs(quarters.extend("BBB", vendor), vendor)
        self.assertEqual(quarters.asked, [])

    def test_a_document_that_cannot_be_fetched_adds_nothing(self):
        vendor = statement(["2026-03-31", "2026-06-30"], **VENDOR)
        quarters = filed_quarters(
            [filing("AAA", "30-JUN-2026", 1), filing("AAA", "30-SEP-2026", 2)],
            {"1": JUNE},
        )
        self.assertIs(quarters.extend("AAA", vendor), vendor)

    def test_a_taxonomy_that_is_not_read_is_never_due_or_added(self):
        quarters = filed_quarters(
            [filing("AAA", "30-SEP-2026", 2, taxonomy="BANKING")], {"2": SEPTEMBER}
        )
        self.assertEqual(quarters.latest(), {})

    def test_an_empty_owners_share_falls_back_to_the_periods_profit(self):
        lines = parse_quarter_statement(document(revenue=10, profit=3, owners_profit=0))
        self.assertEqual(lines["net_profit"], 3)
        # Without interest and depreciation there is no operating profit.
        self.assertIsNone(lines["operating_profit"])


class FiledQuarterSelectionTests(unittest.TestCase):
    today = date(2026, 10, 12)
    state = {
        "FILED": {"fetched_at": "2026-10-09T00:00:00+00:00", "latest_quarter": "2026-06-30"},
        "TODAY": {"fetched_at": "2026-10-12T03:00:00+00:00", "latest_quarter": "2026-06-30"},
        "CURRENT": {"fetched_at": "2026-10-09T00:00:00+00:00", "latest_quarter": "2026-09-30"},
        "NOQUARTERS": {"fetched_at": "2026-10-09T00:00:00+00:00", "latest_quarter": None},
        "OLD": {"fetched_at": "2026-08-01T00:00:00+00:00", "latest_quarter": "2026-06-30"},
    }
    filed = {symbol: date(2026, 9, 30) for symbol in ("FILED", "TODAY", "CURRENT", "NOQUARTERS")}

    def test_a_filing_ahead_of_the_stored_quarter_is_due_and_goes_first(self):
        due = select_due(list(self.state), self.state, self.today, filed_latest=self.filed)
        # TODAY was already tried today; CURRENT has the quarter; NOQUARTERS has
        # no vendor history to reconcile a filing against.
        self.assertEqual(due, ["FILED", "OLD"])

    def test_without_a_filing_index_selection_is_unchanged(self):
        self.assertEqual(select_due(list(self.state), self.state, self.today), ["OLD"])


class FiledTicker(FakeTicker):
    def __init__(self, symbol):
        super().__init__(symbol)
        self.quarterly_income_stmt = frame(
            {"Total Revenue": [1000, 900], "Net Income": [150, 120]},
            ["2026-06-30", "2026-03-31"],
        )


class FiledQuarterRunTests(unittest.TestCase):
    def run_worker(self, quarters):
        repo = FakeRepository()
        repo.latest_snapshot_symbols = lambda: ["AAA"]
        repo.financial_statement_state = lambda: {}
        counts = run(
            repo, ticker_factory=FiledTicker, pause_seconds=0,
            today=date(2026, 10, 12), filed_quarters=quarters,
        )
        return counts, repo.written[0]

    def test_the_stored_row_carries_the_filed_quarter_and_names_its_source(self):
        quarters = filed_quarters(
            [filing("AAA", "30-JUN-2026", 1), filing("AAA", "30-SEP-2026", 2)],
            {"1": JUNE, "2": SEPTEMBER},
        )
        counts, row = self.run_worker(quarters)
        income = row["statements"]["quarterly"]["income"]
        self.assertEqual(income["periods"][-1], "2026-09-30")
        self.assertEqual(income["rows"]["revenue"], [900, 1000, 1100])
        self.assertEqual(income["filed_periods"], ["2026-09-30"])
        self.assertEqual(row["latest_quarter"], "2026-09-30")
        self.assertEqual(row["source"], SOURCE_WITH_FILINGS)
        self.assertEqual(counts["with_filed_quarters"], 1)

    def test_a_row_with_nothing_filed_is_the_vendors_alone(self):
        counts, row = self.run_worker(filed_quarters([], {}))
        self.assertEqual(row["latest_quarter"], "2026-06-30")
        self.assertEqual(row["source"], SOURCE)
        self.assertNotIn("filed_periods", row["statements"]["quarterly"]["income"])
        self.assertEqual(counts["with_filed_quarters"], 0)

    def test_a_market_with_no_filing_index_loads_none(self):
        with mock.patch("screener.quarterly_results.fetch_index") as fetch_index:
            self.assertIsNone(
                load_filed_quarters(
                    SimpleNamespace(quarterly_results_provider=None), date(2026, 10, 12)
                )
            )
        fetch_index.assert_not_called()

    def test_an_unreadable_index_publishes_the_vendors_quarters_only(self):
        profile = SimpleNamespace(quarterly_results_provider="nse_integrated_filings")
        with mock.patch(
            "screener.quarterly_results.fetch_index", side_effect=ConnectionError("blocked")
        ), self.assertLogs("workers.financial_statements", level="WARNING"):
            self.assertIsNone(load_filed_quarters(profile, date(2026, 10, 12)))


if __name__ == "__main__":
    unittest.main()
