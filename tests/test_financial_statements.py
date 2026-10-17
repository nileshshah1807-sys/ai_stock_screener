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

from screener.quarterly_results import parse_quarter_statement
from workers.financial_statements import (
    BALANCE_LINES,
    INCOME_LINES,
    MAX_QUARTERS,
    SOURCE,
    SOURCE_WITH_FILINGS,
    apply_filings,
    build_payload,
    compose_quarters,
    extract_statement,
    recompose_quarters,
    run,
    select_due,
    vendor_quarters,
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

    def test_results_due_rechecks_daily_not_every_run(self):
        stale_quarter = {"latest_quarter": "2026-03-31"}  # 176 days ago
        state = {
            "YESTERDAY": {**stale_quarter, "fetched_at": "2026-09-22T23:00:00+00:00"},
            "TODAY": {**stale_quarter, "fetched_at": "2026-09-23T01:00:00+00:00"},
        }
        self.assertEqual(select_due(["YESTERDAY", "TODAY"], state, self.today), ["YESTERDAY"])

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

    def quarterly_filings(self, symbols):
        return {}


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


def document(**lines):
    """A results document carrying the named lines in the quarter's context."""
    tags = {
        "revenue": "RevenueFromOperations",
        "profit": "ProfitLossForPeriod",
        "owners_profit": "ProfitOrLossAttributableToOwnersOfParent",
        "minority_profit": "ProfitOrLossAttributableToNonControllingInterests",
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


def stored(symbol, period, *, consolidated=True, **lines):
    """One row of quarterly_filings as the repository serves it."""
    return {
        "symbol": symbol,
        "period_end": period,
        "is_consolidated": consolidated,
        "filed_at": "2026-10-08T22:07:33+05:30",
        "lines": lines,
    }


def quarter(period, revenue, pbt, interest, depreciation, profit, eps, **extra):
    return stored(
        "AAA", period, revenue=revenue, pbt=pbt, interest=interest,
        depreciation=depreciation, net_profit=profit, eps=eps,
        operating_profit=pbt + interest + depreciation, **extra,
    )


# Vendor through June; the company has filed June and September.
VENDOR = statement(
    ["2026-03-31", "2026-06-30"],
    revenue=[900, 1000],
    operating_profit=[190, 215],
    pbt=[170, 200],
    interest=[5, 5],
    depreciation=[15, 10],
    net_profit=[120, 150],
    eps=[1.2, 1.5],
)
JUNE = quarter("2026-06-30", 1000, 200, 5, 10, 150, 1.5)
SEPTEMBER = quarter("2026-09-30", 1100, 230, 6, 11, 170, 1.7)


class ComposeQuarterTests(unittest.TestCase):
    def test_filed_quarters_are_drawn_from_the_filings(self):
        composed = compose_quarters(VENDOR, [JUNE, SEPTEMBER])
        self.assertEqual(composed["periods"], ["2026-03-31", "2026-06-30", "2026-09-30"])
        self.assertEqual(composed["filed_periods"], ["2026-06-30", "2026-09-30"])
        rows = composed["rows"]
        self.assertEqual(rows["revenue"], [900, 1000, 1100])
        self.assertEqual(rows["pbt"], [170, 200, 230])
        self.assertEqual(rows["net_profit"], [120, 150, 170])
        self.assertEqual(rows["eps"], [1.2, 1.5, 1.7])
        self.assertEqual(rows["operating_profit"], [190, 215, 247])
        self.assertEqual(rows["expenses"], [710, 785, 853])

    def test_a_filed_quarter_replaces_the_vendors_figures_for_it(self):
        # The vendor's June pretax profit counts the associates' share; the
        # filing's does not. June is filed, so the filing's figure stands.
        vendor = statement(VENDOR["periods"], **{**VENDOR["rows"], "pbt": [170, 212]})
        composed = compose_quarters(vendor, [JUNE, SEPTEMBER])
        self.assertEqual(composed["rows"]["pbt"][1:], [200, 230])

    def test_a_vendor_line_that_means_something_else_is_left_out_of_its_quarters(self):
        # A broker's revenue at the vendor is net of its fees: nothing like the
        # filed figure, so it does not sit in the same row as the filings.
        vendor = statement(
            VENDOR["periods"],
            **{**VENDOR["rows"], "revenue": [500, 560], "operating_profit": [190, 215]},
        )
        composed = compose_quarters(vendor, [JUNE, SEPTEMBER])
        self.assertEqual(composed["rows"]["revenue"], [None, 1000, 1100])
        # Lines that agree on June keep the vendor's March.
        self.assertEqual(composed["rows"]["net_profit"], [120, 150, 170])
        self.assertEqual(composed["rows"]["expenses"], [None, 785, 853])

    def test_a_quarter_with_no_filing_keeps_the_vendors_figures(self):
        # The exchange's index has no March filing; the vendor has March.
        composed = compose_quarters(VENDOR, [JUNE, SEPTEMBER])
        self.assertNotIn("2026-03-31", composed["filed_periods"])
        self.assertEqual(composed["rows"]["revenue"][0], 900)
        self.assertEqual(composed["rows"]["operating_profit"][0], 190)
        # And a vendor quarter between two filed ones fills the gap.
        march = quarter("2026-03-31", 900, 170, 5, 15, 120, 1.2)
        gap = compose_quarters(VENDOR, [march, SEPTEMBER])
        self.assertEqual(gap["periods"], ["2026-03-31", "2026-06-30", "2026-09-30"])
        self.assertEqual(gap["filed_periods"], ["2026-03-31", "2026-09-30"])
        self.assertEqual(gap["rows"]["revenue"], [900, 1000, 1100])

    def test_a_quarter_the_vendor_never_had_is_added(self):
        composed = compose_quarters({"periods": [], "rows": {}}, [JUNE, SEPTEMBER])
        self.assertEqual(composed["periods"], ["2026-06-30", "2026-09-30"])
        self.assertEqual(composed["rows"]["revenue"], [1000, 1100])

    def test_one_basis_consolidated_where_the_latest_quarter_was_filed_so(self):
        standalone_june = stored("AAA", "2026-06-30", consolidated=False, revenue=600,
                                 net_profit=80)
        standalone_sept = stored("AAA", "2026-09-30", consolidated=False, revenue=650,
                                 net_profit=90)
        composed = compose_quarters(
            VENDOR, [standalone_june, standalone_sept, JUNE, SEPTEMBER]
        )
        self.assertEqual(composed["rows"]["revenue"], [900, 1000, 1100])
        # A company that files standalone alone is drawn standalone.
        only = compose_quarters({"periods": [], "rows": {}}, [standalone_june, standalone_sept])
        self.assertEqual(only["rows"]["revenue"], [600, 650])

    def test_a_company_that_has_just_begun_to_consolidate_is_drawn_standalone(self):
        # SGFIN, Oct 2026: its first consolidated filing beside a year of
        # standalone ones. Drawn consolidated, the year-ago quarter the vendor
        # never had would vanish from the page.
        standalone = [
            stored("AAA", period, consolidated=False, revenue=revenue, net_profit=10)
            for period, revenue in [("2025-09-30", 500), ("2026-06-30", 600),
                                    ("2026-09-30", 650)]
        ]
        empty = {"periods": [], "rows": {}}
        composed = compose_quarters(empty, [*standalone, SEPTEMBER])
        self.assertEqual(composed["rows"]["revenue"], [500, 600, 650])
        # A year on, with a consolidated year-ago quarter, it is consolidated.
        year_ago = quarter("2025-09-30", 900, 100, 5, 10, 80, 0.8)
        composed = compose_quarters(empty, [*standalone, year_ago, SEPTEMBER])
        self.assertEqual(composed["rows"]["revenue"], [900, 1100])

    def test_a_banks_net_interest_income_is_drawn_from_its_filing(self):
        bank = stored("AAA", "2026-09-30", revenue=1584, net_interest_income=1116,
                      net_profit=426)
        composed = compose_quarters({"periods": [], "rows": {}}, [bank])
        self.assertEqual(composed["rows"]["net_interest_income"], [1116])

    def test_a_filing_that_parsed_to_nothing_is_not_a_quarter(self):
        empty = stored("AAA", "2026-09-30", revenue=None, net_profit=None)
        composed = compose_quarters(VENDOR, [JUNE, empty])
        self.assertEqual(composed["periods"], ["2026-03-31", "2026-06-30"])

    def test_no_filings_leaves_the_vendors_statement_as_it_was(self):
        self.assertIs(compose_quarters(VENDOR, []), VENDOR)

    def test_an_unreported_line_stays_null_not_zero(self):
        composed = compose_quarters(
            VENDOR, [JUNE, stored("AAA", "2026-09-30", revenue=1100, net_profit=170)]
        )
        self.assertIsNone(composed["rows"]["pbt"][-1])
        self.assertIsNone(composed["rows"]["expenses"][-1])

    def test_the_table_keeps_the_latest_three_years(self):
        periods = pd.date_range("2022-03-31", periods=16, freq="QE").date
        filings = [stored("AAA", p.isoformat(), revenue=100 + i, net_profit=10)
                   for i, p in enumerate(periods)]
        composed = compose_quarters({"periods": [], "rows": {}}, filings)
        self.assertEqual(len(composed["periods"]), MAX_QUARTERS)
        self.assertEqual(composed["periods"][-1], periods[-1].isoformat())

    def test_an_empty_owners_share_falls_back_to_the_periods_profit(self):
        lines = parse_quarter_statement(document(revenue=10, profit=3, owners_profit=0))
        self.assertEqual(lines["net_profit"], 3)
        # Without interest and depreciation there is no operating profit.
        self.assertIsNone(lines["operating_profit"])

    def test_the_owners_share_is_net_profit_when_the_shares_add_up(self):
        lines = parse_quarter_statement(document(
            revenue=4e10, profit=1.12e9, owners_profit=1.05e9, minority_profit=0.07e9
        ))
        self.assertEqual(lines["net_profit"], 1.05e9)

    def test_an_owners_share_that_does_not_add_up_is_not_taken(self):
        # Owners 26 crore and a nil minority beside a profit of 112: the
        # owners' line is mis-tagged, and the period's profit stands.
        lines = parse_quarter_statement(document(
            revenue=4e10, profit=1.12e9, owners_profit=2.6e8, minority_profit=0
        ))
        self.assertEqual(lines["net_profit"], 1.12e9)


class StoredPayloadTests(unittest.TestCase):
    def payload(self):
        return {
            "statements": {"annual": {}, "quarterly": {"income": VENDOR}},
            "has_data": True,
            "latest_quarter": "2026-06-30",
        }

    def test_the_vendors_quarters_are_kept_beside_the_drawn_ones(self):
        payload = self.payload()
        self.assertTrue(apply_filings(payload, [JUNE, SEPTEMBER]))
        quarterly = payload["statements"]["quarterly"]
        self.assertEqual(quarterly["vendor_income"], VENDOR)
        self.assertEqual(quarterly["income"]["filed_periods"], ["2026-06-30", "2026-09-30"])
        self.assertEqual(payload["latest_quarter"], "2026-09-30")
        # Drawn again from the stored payload, the result is the same.
        again = {**payload, "statements": {**payload["statements"]}}
        self.assertTrue(apply_filings(again, [JUNE, SEPTEMBER]))
        self.assertEqual(again["statements"]["quarterly"], quarterly)

    def test_a_row_written_before_the_vendors_copy_was_kept_gives_it_back(self):
        legacy = {
            "income": {
                "periods": ["2026-03-31", "2026-06-30", "2026-09-30"],
                "rows": {"revenue": [900, 1000, 1100], "net_profit": [120, 150, 170],
                         "operating_profit": [190, 215, None]},
                "filed_periods": ["2026-09-30"],
            }
        }
        vendor = vendor_quarters(legacy)
        self.assertEqual(vendor["periods"], ["2026-03-31", "2026-06-30"])
        self.assertEqual(vendor["rows"]["revenue"], [900, 1000])
        self.assertEqual(vendor["rows"]["expenses"], [710, 785])

    def test_no_filings_leaves_the_vendors_quarters_alone(self):
        payload = self.payload()
        self.assertFalse(apply_filings(payload, []))
        self.assertEqual(payload["statements"]["quarterly"], {"income": VENDOR})
        self.assertEqual(payload["latest_quarter"], "2026-06-30")


class FilingRepository(FakeRepository):
    def __init__(self, filings=None, rows=None):
        super().__init__()
        self.filings = filings or {}
        self.rows = rows or []

    def quarterly_filings(self, symbols):
        return {s: self.filings[s] for s in symbols if s in self.filings}

    def financial_statement_rows(self, symbols):
        return [row for row in self.rows if row["symbol"] in symbols]


class RecomposeTests(unittest.TestCase):
    def test_a_stored_row_is_redrawn_without_asking_the_vendor(self):
        row = {
            "symbol": "AAA",
            "statements": {"annual": {}, "quarterly": {"income": VENDOR}},
            "has_data": True,
            "currency": "INR",
            "source": SOURCE,
            "latest_annual": "2026-03-31",
            "latest_quarter": "2026-06-30",
            "fetched_at": "2026-10-01T03:00:00+00:00",
        }
        repo = FilingRepository({"AAA": [JUNE, SEPTEMBER]}, [row])
        self.assertEqual(recompose_quarters(repo, ["AAA", "BBB"]), 1)
        written = repo.written[0]
        self.assertEqual(written["latest_quarter"], "2026-09-30")
        self.assertEqual(written["source"], SOURCE_WITH_FILINGS)
        # When the vendor was last asked is unchanged: its refresh is still due
        # on its own schedule.
        self.assertEqual(written["fetched_at"], "2026-10-01T03:00:00+00:00")
        self.assertEqual(written["latest_annual"], "2026-03-31")

    def test_dry_run_writes_nothing(self):
        repo = FilingRepository({"AAA": [JUNE]}, [])
        recompose_quarters(repo, ["AAA"], dry_run=True)
        self.assertEqual(repo.written, [])


class FiledTicker(FakeTicker):
    def __init__(self, symbol):
        super().__init__(symbol)
        self.quarterly_income_stmt = frame(
            {"Total Revenue": [1000, 900], "Net Income": [150, 120]},
            ["2026-06-30", "2026-03-31"],
        )


class FiledQuarterRunTests(unittest.TestCase):
    def run_worker(self, repo):
        repo.latest_snapshot_symbols = lambda: ["AAA"]
        repo.financial_statement_state = lambda: {}
        counts = run(repo, ticker_factory=FiledTicker, pause_seconds=0,
                     today=date(2026, 10, 12))
        return counts, repo.written[0]

    def test_the_stored_row_draws_the_filed_quarters_and_names_its_source(self):
        counts, row = self.run_worker(FilingRepository({"AAA": [JUNE, SEPTEMBER]}))
        income = row["statements"]["quarterly"]["income"]
        self.assertEqual(income["periods"], ["2026-03-31", "2026-06-30", "2026-09-30"])
        self.assertEqual(income["rows"]["revenue"], [900, 1000, 1100])
        self.assertEqual(row["latest_quarter"], "2026-09-30")
        self.assertEqual(row["source"], SOURCE_WITH_FILINGS)
        self.assertEqual(counts["with_filed_quarters"], 1)

    def test_a_result_filed_while_the_run_is_fetching_is_not_overwritten(self):
        # The Quarterly filings job stores September after this run began and
        # draws it onto the page; this run's write must carry it too, or the
        # quarter vanishes until the vendor is next asked.
        repo = FilingRepository()

        def ticker_then_filing(ticker):
            repo.filings["AAA"] = [JUNE, SEPTEMBER]
            return FiledTicker(ticker)

        repo.latest_snapshot_symbols = lambda: ["AAA"]
        repo.financial_statement_state = lambda: {}
        run(repo, ticker_factory=ticker_then_filing, pause_seconds=0,
            today=date(2026, 10, 12))
        self.assertEqual(repo.written[0]["latest_quarter"], "2026-09-30")

    def test_a_row_with_nothing_filed_is_the_vendors_alone(self):
        counts, row = self.run_worker(FilingRepository())
        self.assertEqual(row["latest_quarter"], "2026-06-30")
        self.assertEqual(row["source"], SOURCE)
        self.assertNotIn("filed_periods", row["statements"]["quarterly"]["income"])
        self.assertEqual(counts["with_filed_quarters"], 0)

    def test_a_market_with_no_filing_index_never_reads_the_filings(self):
        repo = FilingRepository()
        repo.market = "US"
        repo.quarterly_filings = lambda symbols: self.fail("no filings for this market")
        _, row = self.run_worker(repo)
        self.assertEqual(row["source"], SOURCE)

    def test_unreadable_filings_publish_the_vendors_quarters_only(self):
        repo = FilingRepository()

        def missing(symbols):
            raise RuntimeError("relation quarterly_filings does not exist")

        repo.quarterly_filings = missing
        with self.assertLogs("workers.financial_statements", level="WARNING"):
            _, row = self.run_worker(repo)
        self.assertEqual(row["latest_quarter"], "2026-06-30")


if __name__ == "__main__":
    unittest.main()
