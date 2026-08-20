"""Behavioural spec for the point-in-time fundamental provider.

The load-bearing tests are in `PointInTimeTests`: a statement must be invisible
before the session it became available on, and a restatement must not reach back
and rewrite a decision that preceded it.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from backtest.fundamentals import (
    FundamentalPanel,
    attach_valuation_inputs,
    coverage_report,
)


def panel_frame(rows=None):
    """Five clean years for one security, newest last."""
    if rows is None:
        rows = []
        for index, year in enumerate([2020, 2021, 2022, 2023, 2024]):
            rows.append(
                {
                    "Security_ID": "INE001A01",
                    "ISIN": "INE001A01036",
                    "Symbol": "ALPHA",
                    "Fiscal_Year": year,
                    "Period_End": f"{year}-03-31",
                    "Available_From": f"{year}-05-15",
                    "Filing_Timestamp": f"{year}-05-14T18:00:00",
                    "Seq_Number": f"seq{year}",
                    "Is_Consolidated": True,
                    "Has_Balance_Sheet": True,
                    "Has_Cash_Flow": True,
                    "Revenue": 1000.0 * (1.2**index),
                    "EBIT": 200.0 * (1.2**index),
                    "EBITDA": 250.0 * (1.2**index),
                    "PBT": 180.0 * (1.2**index),
                    "PAT": 130.0 * (1.2**index),
                    "EPS_Basic": 13.0 * (1.2**index),
                    "EPS_Diluted": 13.0 * (1.2**index),
                    "Finance_Costs": 20.0,
                    "Depreciation": 50.0,
                    "Shares_Outstanding": 10.0,
                    "Effective_Tax_Rate": 0.25,
                    "OCF": 150.0 * (1.2**index),
                    "Total_Assets": 2000.0 * (1.1**index),
                    "Equity": 1200.0 * (1.1**index),
                    "Cash": 100.0,
                    "Total_Debt": 300.0,
                }
            )
    return pd.DataFrame(rows)


class PointInTimeTests(unittest.TestCase):
    def setUp(self):
        self.panel = FundamentalPanel(panel_frame())

    def test_statement_is_invisible_the_day_before_it_is_available(self):
        years = [r["Fiscal_Year"] for r in self.panel.history_as_of("INE001A01", "2024-05-14")]
        self.assertNotIn(2024, years)

    def test_statement_becomes_visible_on_its_availability_date(self):
        years = [r["Fiscal_Year"] for r in self.panel.history_as_of("INE001A01", "2024-05-15")]
        self.assertIn(2024, years)

    def test_history_is_newest_first(self):
        years = [r["Fiscal_Year"] for r in self.panel.history_as_of("INE001A01", "2024-12-31")]
        self.assertEqual(years, sorted(years, reverse=True))

    def test_history_is_bounded_by_the_requested_years(self):
        history = self.panel.history_as_of("INE001A01", "2024-12-31", years=3)
        self.assertEqual(len(history), 3)

    def test_no_visible_filings_yields_empty_history(self):
        self.assertEqual(self.panel.history_as_of("INE001A01", "2019-01-01"), [])

    def test_unknown_security_yields_empty_history(self):
        self.assertEqual(self.panel.history_as_of("NOPE", "2024-12-31"), [])

    def test_rows_without_availability_are_dropped(self):
        frame = panel_frame()
        frame.loc[0, "Available_From"] = None
        panel = FundamentalPanel(frame)
        years = [r["Fiscal_Year"] for r in panel.history_as_of("INE001A01", "2024-12-31")]
        self.assertNotIn(2020, years)


class RestatementTests(unittest.TestCase):
    def panel_with_restatement(self):
        rows = panel_frame().to_dict("records")
        original = dict(rows[2])  # FY2022, originally available 2022-05-15
        original["PAT"] = 800.0
        restated = dict(original)
        restated["PAT"] = 620.0
        restated["Available_From"] = "2024-04-20"
        restated["Seq_Number"] = "seq2022v2"
        rows = [r for r in rows if r["Fiscal_Year"] != 2022] + [original, restated]
        return FundamentalPanel(pd.DataFrame(rows))

    def test_decision_before_the_restatement_sees_the_original(self):
        """The p0.md worked example: June 2023 must see 800, not 620."""
        panel = self.panel_with_restatement()
        record = next(
            r for r in panel.history_as_of("INE001A01", "2023-06-30")
            if r["Fiscal_Year"] == 2022
        )
        self.assertAlmostEqual(record["PAT"], 800.0)

    def test_decision_after_the_restatement_sees_the_revision(self):
        panel = self.panel_with_restatement()
        record = next(
            r for r in panel.history_as_of("INE001A01", "2024-06-30")
            if r["Fiscal_Year"] == 2022
        )
        self.assertAlmostEqual(record["PAT"], 620.0)

    def test_a_restated_year_still_appears_only_once(self):
        panel = self.panel_with_restatement()
        years = [r["Fiscal_Year"] for r in panel.history_as_of("INE001A01", "2024-06-30")]
        self.assertEqual(len(years), len(set(years)))


class DerivationTests(unittest.TestCase):
    def setUp(self):
        self.panel = FundamentalPanel(panel_frame())
        self.factors = self.panel.factors_as_of("INE001A01", "2024-12-31")

    def test_derivation_runs_through_the_production_function(self):
        self.assertIsNotNone(self.factors)
        self.assertEqual(self.factors["Statement_Years"], 5)

    def test_revenue_cagr_matches_the_constructed_growth_rate(self):
        self.assertAlmostEqual(self.factors["Revenue_CAGR_3Y"], 0.20, places=6)

    def test_roic_is_computable_from_derived_invested_capital(self):
        """Invested capital is not filed; equity plus debt makes ROIC possible."""
        self.assertIsNotNone(self.factors["ROIC"])

    def test_statement_age_reflects_the_decision_date(self):
        factors = self.panel.factors_as_of("INE001A01", "2024-09-30")
        self.assertEqual(factors["Statement_Age_Days"], 138)

    def test_fiscal_year_of_the_evidence_is_recorded(self):
        self.assertEqual(self.factors["Statement_Fiscal_Year"], 2024)

    def test_no_visible_history_yields_no_factors(self):
        self.assertIsNone(self.panel.factors_as_of("INE001A01", "2019-01-01"))

    def test_free_cash_flow_is_absent_rather_than_approximated(self):
        """OCF must not stand in for FCF; that would flatter every cash ratio."""
        frame = attach_valuation_inputs(
            pd.DataFrame([dict(self.factors, Close=100.0)])
        )
        self.assertTrue(pd.isna(frame["Free_CashFlow"].iloc[0]))


class CrossSectionTests(unittest.TestCase):
    def setUp(self):
        self.panel = FundamentalPanel(panel_frame())

    def test_cross_section_returns_one_row_per_security(self):
        frame = self.panel.cross_section(["INE001A01"], "2024-12-31")
        self.assertEqual(len(frame), 1)

    def test_unknown_securities_are_skipped(self):
        frame = self.panel.cross_section(["INE001A01", "NOPE"], "2024-12-31")
        self.assertEqual(len(frame), 1)

    def test_stale_evidence_is_excluded_when_a_bound_is_set(self):
        frame = self.panel.cross_section(
            ["INE001A01"], "2027-12-31", max_age_days=365
        )
        self.assertTrue(frame.empty)

    def test_stale_evidence_is_kept_without_a_bound(self):
        frame = self.panel.cross_section(["INE001A01"], "2027-12-31")
        self.assertEqual(len(frame), 1)

    def test_empty_request_yields_empty_frame_with_schema(self):
        frame = self.panel.cross_section([], "2024-12-31")
        self.assertTrue(frame.empty)
        self.assertIn("Security_ID", frame.columns)


class ValuationInputTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame(
            [
                {
                    "Security_ID": "INE001A01",
                    "Latest_Shares": 10.0,
                    "Latest_EPS": 13.0,
                    "Latest_Equity": 1200.0,
                    "Latest_Total_Debt": 300.0,
                    "Latest_Cash": 100.0,
                    "Latest_EBIT": 200.0,
                    "Latest_Revenue": 1000.0,
                    "Close": 150.0,
                }
            ]
        )

    def test_market_cap_uses_the_point_in_time_price(self):
        out = attach_valuation_inputs(self.frame())
        self.assertAlmostEqual(out["Market_Cap"].iloc[0], 1500.0)

    def test_book_value_is_equity_per_share(self):
        out = attach_valuation_inputs(self.frame())
        self.assertAlmostEqual(out["Book_Value"].iloc[0], 120.0)

    def test_zero_price_yields_no_market_cap(self):
        frame = self.frame()
        frame.loc[0, "Close"] = 0.0
        out = attach_valuation_inputs(frame)
        self.assertTrue(pd.isna(out["Market_Cap"].iloc[0]))

    def test_missing_share_count_yields_no_market_cap(self):
        frame = self.frame()
        frame.loc[0, "Latest_Shares"] = np.nan
        out = attach_valuation_inputs(frame)
        self.assertTrue(pd.isna(out["Market_Cap"].iloc[0]))

    def test_empty_frame_passes_through(self):
        self.assertTrue(attach_valuation_inputs(pd.DataFrame()).empty)


class CoverageTests(unittest.TestCase):
    def test_report_counts_populated_inputs(self):
        frame = pd.DataFrame(
            {"Revenue_CAGR_3Y": [0.1, None], "ROIC": [0.2, 0.3]}
        )
        report = coverage_report(frame)
        self.assertEqual(report["rows"], 2)
        self.assertAlmostEqual(report["Revenue_CAGR_3Y"], 50.0)
        self.assertAlmostEqual(report["ROIC"], 100.0)

    def test_empty_frame_is_safe(self):
        self.assertEqual(coverage_report(pd.DataFrame())["rows"], 0)


class PersistenceTests(unittest.TestCase):
    def test_round_trip_through_csv(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "panel.csv"
            panel_frame().to_csv(path, index=False)
            panel = FundamentalPanel.load(path)
            self.assertEqual(len(panel), 1)
            self.assertIsNotNone(panel.factors_as_of("INE001A01", "2024-12-31"))

    def test_missing_file_yields_empty_panel(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(len(FundamentalPanel.load(Path(tmp) / "none.csv")), 0)


if __name__ == "__main__":
    unittest.main()
