"""Behavioural spec for annual-statement collection and factor derivation."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from screener.statements import (
    STATEMENT_SCHEMA_VERSION,
    FinancialStatementCollector,
    derive_statement_factors,
)

PERIODS = [
    pd.Timestamp("2026-03-31"),
    pd.Timestamp("2025-03-31"),
    pd.Timestamp("2024-03-31"),
    pd.Timestamp("2023-03-31"),
]


def frame(rows):
    # Yahoo statements are line items down the index and periods across the
    # columns, newest first.
    return pd.DataFrame.from_dict(rows, orient="index", columns=PERIODS)


def income(**overrides):
    rows = {
        # Newest first, matching Yahoo's column ordering.
        "Total Revenue": [1331.0, 1210.0, 1100.0, 1000.0],
        "Gross Profit": [400.0, 360.0, 330.0, 300.0],
        "EBIT": [1000.0, 900.0, 800.0, 700.0],
        "EBITDA": [1200.0, 1100.0, 1000.0, 900.0],
        "Net Income": [500.0, 450.0, 400.0, 350.0],
        "Interest Expense": [100.0, 100.0, 100.0, 100.0],
        "Tax Rate For Calcs": [0.25, 0.25, 0.25, 0.25],
        "Diluted EPS": [13.31, 12.10, 11.00, 10.00],
    }
    rows.update(overrides)
    return frame(rows)


def balance(**overrides):
    rows = {
        "Total Assets": [10000.0, 9500.0, 9000.0, 8500.0],
        "Invested Capital": [5000.0, 5000.0, 4800.0, 4600.0],
        "Stockholders Equity": [4000.0, 3800.0, 3600.0, 3400.0],
        "Total Debt": [1000.0, 1000.0, 1000.0, 1000.0],
        "Cash And Cash Equivalents": [400.0, 350.0, 300.0, 250.0],
        "Ordinary Shares Number": [110.0, 105.0, 102.0, 100.0],
    }
    rows.update(overrides)
    return frame(rows)


def cashflow(**overrides):
    rows = {
        "Operating Cash Flow": [300.0, 280.0, 260.0, 240.0],
        "Free Cash Flow": [200.0, 180.0, 160.0, 140.0],
        "Capital Expenditure": [-100.0, -100.0, -100.0, -100.0],
    }
    rows.update(overrides)
    return frame(rows)


class DerivationTests(unittest.TestCase):
    def test_roic_uses_nopat_over_average_invested_capital(self):
        derived = derive_statement_factors(income(), balance(), cashflow())
        # EBIT 1000 * (1 - 0.25) = 750 NOPAT; average invested capital
        # (5000 + 5000) / 2 = 5000 -> 15%.
        self.assertAlmostEqual(derived["ROIC"], 0.15, places=6)

    def test_roic_averages_a_capital_raise_instead_of_crediting_it_fully(self):
        raised = balance(**{"Invested Capital": [8000.0, 4000.0, 3800.0, 3600.0]})
        derived = derive_statement_factors(income(), raised, cashflow())
        # Average base 6000, not the 8000 closing balance.
        self.assertAlmostEqual(derived["ROIC"], 750.0 / 6000.0, places=6)

    def test_three_year_cagr_is_compound_not_cumulative(self):
        derived = derive_statement_factors(income(), balance(), cashflow())
        self.assertAlmostEqual(derived["Revenue_CAGR_3Y"], 0.10, places=6)
        self.assertAlmostEqual(derived["EPS_CAGR_3Y"], 0.10, places=4)

    def test_cagr_from_a_negative_base_is_refused_and_flagged(self):
        # A CAGR measured from a loss is arithmetically defined and
        # economically meaningless; it is the classic way a screen ranks a
        # loss-maker as its fastest grower.
        loss = income(**{"Diluted EPS": [5.0, 1.0, -2.0, -10.0]})
        derived = derive_statement_factors(loss, balance(), cashflow())
        self.assertIsNone(derived["EPS_CAGR_3Y"])
        self.assertIn("eps_base", derived["Statement_Negative_Base_Flags"])

    def test_accruals_are_signed_so_lower_is_better(self):
        derived = derive_statement_factors(income(), balance(), cashflow())
        # (500 net income - 300 operating cash) / 10000 assets.
        self.assertAlmostEqual(derived["Accruals_To_Assets"], 0.02, places=6)
        cash_rich = cashflow(**{"Operating Cash Flow": [900.0, 280.0, 260.0, 240.0]})
        better = derive_statement_factors(income(), balance(), cash_rich)
        self.assertLess(better["Accruals_To_Assets"], derived["Accruals_To_Assets"])

    def test_asset_scaled_profitability(self):
        derived = derive_statement_factors(income(), balance(), cashflow())
        self.assertAlmostEqual(derived["Gross_Profit_To_Assets"], 0.04, places=6)
        self.assertAlmostEqual(derived["OCF_To_Assets"], 0.03, places=6)
        self.assertAlmostEqual(derived["FCF_To_Assets"], 0.02, places=6)
        self.assertAlmostEqual(derived["Cash_Conversion"], 0.6, places=6)

    def test_statement_returns_available_where_quote_metadata_is_not(self):
        derived = derive_statement_factors(income(), balance(), cashflow())
        # Net income 500 over average equity (4000 + 3800) / 2 = 3900.
        self.assertAlmostEqual(derived["ROE_Statement"], 500.0 / 3900.0, places=6)
        self.assertAlmostEqual(derived["ROA_Statement"], 500.0 / 9750.0, places=6)
        self.assertAlmostEqual(derived["Equity_To_Assets"], 0.4, places=6)

    def test_interest_coverage_is_bounded(self):
        tiny = income(**{"Interest Expense": [0.0001, 100.0, 100.0, 100.0]})
        derived = derive_statement_factors(tiny, balance(), cashflow())
        self.assertLessEqual(derived["Interest_Coverage"], 100.0)

    def test_acceleration_compares_latest_year_to_the_medium_term_trend(self):
        derived = derive_statement_factors(income(), balance(), cashflow())
        # Latest YoY 1331/1210 - 1 = 10%; CAGR 10% -> no acceleration.
        self.assertAlmostEqual(derived["Revenue_Acceleration"], 0.0, places=6)
        surging = income(**{"Total Revenue": [1800.0, 1210.0, 1100.0, 1000.0]})
        faster = derive_statement_factors(surging, balance(), cashflow())
        self.assertGreater(faster["Revenue_Acceleration"], 0.2)

    def test_dilution_is_annualised_over_three_years(self):
        derived = derive_statement_factors(income(), balance(), cashflow())
        self.assertAlmostEqual(
            derived["Share_Dilution_3Y"], (110.0 / 100.0) ** (1 / 3) - 1, places=6
        )

    def test_bank_shaped_statements_degrade_instead_of_failing(self):
        # Banks report no EBIT, gross profit or current assets. Those inputs
        # must come back missing, while the ones they do report still derive.
        bank_income = frame(
            {
                "Total Revenue": [1000.0, 900.0, 800.0, 700.0],
                "Net Income": [200.0, 180.0, 160.0, 140.0],
                "Interest Expense": [500.0, 450.0, 400.0, 350.0],
                "Tax Rate For Calcs": [0.25, 0.25, 0.25, 0.25],
                "Diluted EPS": [20.0, 18.0, 16.0, 14.0],
            }
        )
        derived = derive_statement_factors(bank_income, balance(), cashflow())
        self.assertIsNone(derived["ROIC"])
        self.assertIsNone(derived["Gross_Profit_To_Assets"])
        self.assertIsNotNone(derived["ROE_Statement"])
        self.assertIsNotNone(derived["Revenue_CAGR_3Y"])
        self.assertGreater(derived["Statement_Years"], 0)

    def test_empty_statements_produce_no_evidence(self):
        derived = derive_statement_factors(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        self.assertEqual(derived["Statement_Years"], 0)
        self.assertIsNone(derived["ROIC"])


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol
        self.income_stmt = income()
        self.balance_sheet = balance()
        self.cashflow = cashflow()


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        class Config:
            OUTPUT_DIR = Path(self._temp.name)
            STATEMENT_COLLECTION_ENABLED = True
            STATEMENT_CACHE_MAX_AGE_DAYS = 90
            STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN = 400
            STATEMENT_REQUESTS_PER_MINUTE = 10_000

        self.config = Config

    def collector(self, calls=None, clock=None):
        def factory(symbol):
            if calls is not None:
                calls.append(symbol)
            return FakeTicker(symbol)

        return FinancialStatementCollector(
            self.config, ticker_factory=factory, clock=clock or (lambda: datetime(2026, 8, 13))
        )

    def test_collect_writes_a_cache_and_reuses_it(self):
        first_calls = []
        result = self.collector(first_calls).collect(["TCS", "INFY"])
        self.assertEqual(len(result), 2)
        self.assertEqual(sorted(first_calls), ["INFY.NS", "TCS.NS"])
        self.assertTrue((Path(self._temp.name) / "statement_cache.csv").exists())

        second_calls = []
        reused = self.collector(second_calls).collect(["TCS", "INFY"])
        self.assertEqual(len(reused), 2)
        # Statements restate quarterly at most; a fresh cache must not refetch.
        self.assertEqual(second_calls, [])

    def test_expired_cache_is_refetched(self):
        self.collector([]).collect(["TCS"])
        later = []
        self.collector(later, clock=lambda: datetime(2027, 1, 1)).collect(["TCS"])
        self.assertEqual(later, ["TCS.NS"])

    def test_fetch_budget_bounds_a_cold_run(self):
        self.config.STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN = 2
        calls = []
        result = self.collector(calls).collect(["A", "B", "C", "D"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result), 2)

    def test_cache_rows_outside_todays_universe_are_retained(self):
        self.collector([]).collect(["TCS", "INFY"])
        self.collector([]).collect(["TCS"])
        cached = pd.read_csv(Path(self._temp.name) / "statement_cache.csv")
        # Dropping INFY here would force a needless refetch tomorrow.
        self.assertEqual(sorted(cached["Symbol"]), ["INFY", "TCS"])

    def test_schema_version_change_invalidates_the_cache(self):
        self.collector([]).collect(["TCS"])
        path = Path(self._temp.name) / "statement_cache.csv"
        stale = pd.read_csv(path)
        stale["Statement_Schema_Version"] = STATEMENT_SCHEMA_VERSION + 1
        stale.to_csv(path, index=False)
        calls = []
        self.collector(calls).collect(["TCS"])
        self.assertEqual(calls, ["TCS.NS"])

    def test_enrich_left_joins_without_dropping_symbols(self):
        base = pd.DataFrame({"Symbol": ["TCS", "UNKNOWNCO"], "Current_Price": [1.0, 2.0]})
        enriched = self.collector([]).enrich(base)
        self.assertEqual(len(enriched), 2)
        self.assertTrue(
            bool(enriched.loc[enriched["Symbol"] == "TCS", "Statement_Record_Available"].iloc[0])
        )


if __name__ == "__main__":
    unittest.main()
