"""Vendor statements appended to the point-in-time panel, past the filing archive."""

import unittest

import pandas as pd

from tools.extend_fundamental_panel import (
    AVAILABILITY_LAG_DAYS,
    extend,
    overlap_report,
    vendor_panel_rows,
)

STATEMENTS = {
    "annual": {
        "income": {
            "periods": ["2024-03-31", "2025-03-31"],
            "rows": {
                "revenue": [1000.0, 1200.0],
                "operating_profit": [200.0, 260.0],
                "depreciation": [50.0, 60.0],
                "interest": [10.0, 0.0],
                "pbt": [140.0, 200.0],
                "tax": [35.0, 50.0],
                "net_profit": [105.0, 150.0],
                "eps": [10.5, 15.0],
            },
        },
        "balance": {
            "periods": ["2025-03-31"],
            "rows": {"total_assets": [900.0], "shareholders_equity": [500.0], "borrowings": [None]},
        },
        "cashflow": {"periods": ["2024-03-31", "2025-03-31"], "rows": {"cfo": [120.0, 170.0]}},
    }
}


def archive_panel():
    return pd.DataFrame(
        [
            {"Security_ID": "INE001A01", "Fiscal_Year": 2023, "Available_From": "2023-05-20", "Revenue": 800.0, "PAT": 80.0},
            {"Security_ID": "INE001A01", "Fiscal_Year": 2024, "Available_From": "2024-05-18", "Revenue": 1010.0, "PAT": 105.0},
        ]
    )


class VendorPanelRowTests(unittest.TestCase):
    def setUp(self):
        self.rows = vendor_panel_rows("ACME", STATEMENTS, "INE001A01", "INE001A01012")
        self.latest = self.rows[-1]

    def test_one_row_per_annual_period(self):
        self.assertEqual([row["Fiscal_Year"] for row in self.rows], [2024, 2025])

    def test_a_statement_is_dated_at_the_filing_deadline_not_the_period_end(self):
        self.assertEqual(AVAILABILITY_LAG_DAYS, 61)
        self.assertEqual(self.latest["Available_From"], "2025-05-31")

    def test_ebit_is_operating_profit_after_depreciation(self):
        self.assertEqual(self.latest["EBITDA"], 260.0)
        self.assertEqual(self.latest["EBIT"], 200.0)
        self.assertAlmostEqual(self.latest["Operating_Margin"], 200.0 / 1200.0)

    def test_an_unreported_value_stays_missing_rather_than_zero(self):
        self.assertTrue(pd.isna(self.latest["Total_Debt"]))
        # No interest paid is not infinite coverage.
        self.assertTrue(pd.isna(self.latest["Interest_Coverage"]))
        # The balance sheet was not reported for the earlier year at all.
        self.assertFalse(self.rows[0]["Has_Balance_Sheet"])
        self.assertTrue(pd.isna(self.rows[0]["Equity"]))

    def test_shares_are_implied_by_profit_and_eps(self):
        self.assertAlmostEqual(self.latest["Shares_Outstanding"], 10.0)

    def test_an_empty_payload_yields_nothing(self):
        self.assertEqual(vendor_panel_rows("ACME", None, "INE001A01"), [])


class ExtendTests(unittest.TestCase):
    def vendor(self):
        frame = pd.DataFrame(vendor_panel_rows("ACME", STATEMENTS, "INE001A01"))
        return frame[["Security_ID", "Fiscal_Year", "Available_From", "Revenue", "PAT"]]

    def test_only_years_after_the_archive_are_added(self):
        extended, added = extend(archive_panel(), self.vendor())
        self.assertEqual(added["Fiscal_Year"].tolist(), [2025])
        self.assertEqual(len(extended), 3)

    def test_a_filed_figure_is_never_replaced_by_the_vendor_one(self):
        extended, _ = extend(archive_panel(), self.vendor())
        filed = extended[extended["Fiscal_Year"] == 2024]
        self.assertEqual(filed["Revenue"].tolist(), [1010.0])

    def test_overlap_report_compares_the_shared_year(self):
        panel = archive_panel().assign(
            EBIT=1.0, EPS_Diluted=1.0, Equity=1.0, Total_Debt=1.0, OCF=1.0
        )
        vendor = self.vendor().assign(
            EBIT=1.0, EPS_Diluted=1.0, Equity=1.0, Total_Debt=1.0, OCF=1.0
        )
        count, median, within = overlap_report(panel, vendor, 2024)["Revenue"]
        self.assertEqual(count, 1)
        self.assertAlmostEqual(median, 1000.0 / 1010.0)
        self.assertEqual(within, 1.0)


if __name__ == "__main__":
    unittest.main()
