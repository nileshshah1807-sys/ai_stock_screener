"""Vendor statements appended to the point-in-time panel, past the filing archive."""

import unittest

import pandas as pd

from tools.extend_fundamental_panel import (
    AVAILABILITY_LAG_DAYS,
    extend,
    extend_quarters,
    overlap_report,
    vendor_basis,
    vendor_panel_rows,
    vendor_quarter_rows,
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


def statements_without_latest_eps(capital):
    return {
        "annual": {
            "income": {
                "periods": ["2025-03-31", "2026-03-31"],
                "rows": {"net_profit": [150.0, 264.0], "eps": [15.0, None]},
            },
            "balance": {
                "periods": ["2025-03-31", "2026-03-31"],
                "rows": {"equity_capital": capital},
            },
        }
    }


class MissingEpsTests(unittest.TestCase):
    def latest(self, capital):
        return vendor_panel_rows("ACME", statements_without_latest_eps(capital), "INE001A01")[-1]

    def test_a_year_without_eps_takes_the_earlier_count_scaled_by_paid_up_capital(self):
        latest = self.latest([100.0, 110.0])
        self.assertAlmostEqual(latest["Shares_Outstanding"], 11.0)
        self.assertAlmostEqual(latest["EPS_Basic"], 24.0)
        self.assertAlmostEqual(latest["EPS_Diluted"], 24.0)

    def test_without_paid_up_capital_the_earlier_count_is_carried_unchanged(self):
        latest = self.latest([100.0, None])
        self.assertAlmostEqual(latest["Shares_Outstanding"], 10.0)
        self.assertAlmostEqual(latest["EPS_Basic"], 26.4)

    def test_no_earlier_count_leaves_the_year_unreported(self):
        statements = statements_without_latest_eps([100.0, 110.0])
        statements["annual"]["income"]["rows"]["eps"] = [None, None]
        for row in vendor_panel_rows("ACME", statements, "INE001A01"):
            self.assertTrue(pd.isna(row["Shares_Outstanding"]))
            self.assertTrue(pd.isna(row["EPS_Basic"]))

    def test_a_reported_eps_is_never_replaced(self):
        rows = vendor_panel_rows("ACME", STATEMENTS, "INE001A01")
        self.assertEqual([row["EPS_Basic"] for row in rows], [10.5, 15.0])


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


QUARTER_COLUMNS = [
    "Security_ID", "ISIN", "Symbol", "Period_End", "Available_From", "Filing_Timestamp",
    "Seq_Number", "Is_Consolidated", "Revenue", "Other_Income", "PBT", "PAT",
    "EPS_Basic", "EPS_Diluted",
]


def filed_quarters(consolidated=True, scale=1.0):
    """FY2024 in full and the first three quarters of FY2025, as filed."""
    rows = []
    for period, revenue in (
        ("2023-06-30", 220.0), ("2023-09-30", 240.0), ("2023-12-31", 260.0), ("2024-03-31", 280.0),
        ("2024-06-30", 270.0), ("2024-09-30", 290.0), ("2024-12-31", 310.0),
    ):
        rows.append(
            {
                "Security_ID": "INE001A01", "ISIN": "", "Symbol": "ACME", "Period_End": period,
                "Available_From": (pd.Timestamp(period) + pd.Timedelta(days=40)).date().isoformat(),
                "Filing_Timestamp": "", "Seq_Number": period, "Is_Consolidated": consolidated,
                "Revenue": revenue * scale, "Other_Income": None, "PBT": None,
                "PAT": revenue * scale / 10, "EPS_Basic": None, "EPS_Diluted": None,
            }
        )
    frame = pd.DataFrame(rows, columns=QUARTER_COLUMNS)
    return frame.assign(_consolidated=frame["Is_Consolidated"].astype(bool))


QUARTER_STATEMENTS = {
    "annual": {
        "income": {
            "periods": ["2024-03-31", "2025-03-31"],
            # FY2024 is the sum of the four filed quarters; FY2025 implies a
            # final quarter of 330.
            "rows": {"revenue": [1000.0, 1200.0], "net_profit": [100.0, 120.0]},
        }
    },
    "quarterly": {
        "income": {
            "periods": ["2025-06-30", "2025-09-30", "2026-03-31"],
            "rows": {"revenue": [340.0, 360.0, 400.0], "net_profit": [34.0, 36.0, 40.0]},
        }
    },
}


class VendorBasisTests(unittest.TestCase):
    def test_the_basis_whose_quarters_sum_to_the_vendor_year_is_chosen(self):
        self.assertIs(vendor_basis(filed_quarters(True), 1000.0, "2024-03-31"), True)
        self.assertIs(vendor_basis(filed_quarters(False), 1000.0, "2024-03-31"), False)

    def test_no_basis_when_the_sources_disagree(self):
        # Filed quarters sum to 600 against a vendor year of 1,000: a different
        # entity, so its quarters must not be compared with the vendor's.
        self.assertIsNone(vendor_basis(filed_quarters(True, scale=0.6), 1000.0, "2024-03-31"))

    def test_no_basis_without_the_full_filed_year(self):
        partial = filed_quarters(True).iloc[1:]
        self.assertIsNone(vendor_basis(partial, 1000.0, "2024-03-31"))


class VendorQuarterRowTests(unittest.TestCase):
    def rows(self, filed=None):
        filed = filed_quarters() if filed is None else filed
        return {
            row["Period_End"]: row
            for row in vendor_quarter_rows(
                "ACME", QUARTER_STATEMENTS, "INE001A01", filed, "2024-03-31"
            )
        }

    def test_the_unreported_year_end_quarter_is_the_year_less_three_quarters(self):
        derived = self.rows()["2025-03-31"]
        self.assertAlmostEqual(derived["Revenue"], 1200.0 - (270.0 + 290.0 + 310.0))
        self.assertAlmostEqual(derived["PAT"], 120.0 - (27.0 + 29.0 + 31.0))
        # Filed with the annual accounts, so the annual deadline applies.
        self.assertEqual(derived["Available_From"], "2025-05-31")

    def test_vendor_quarters_follow_on_the_matched_basis(self):
        rows = self.rows()
        self.assertEqual(sorted(rows), ["2025-03-31", "2025-06-30", "2025-09-30", "2026-03-31"])
        self.assertEqual(rows["2025-06-30"]["Revenue"], 340.0)
        self.assertEqual(rows["2025-06-30"]["Available_From"], "2025-08-15")
        self.assertEqual(rows["2026-03-31"]["Available_From"], "2026-05-31")
        self.assertTrue(all(row["Is_Consolidated"] for row in rows.values()))

    def test_a_company_whose_basis_cannot_be_matched_is_left_out(self):
        self.assertEqual(self.rows(filed_quarters(True, scale=0.6)), {})

    def test_extend_quarters_appends_and_counts(self):
        panel = filed_quarters().drop(columns="_consolidated")
        records = [
            {"symbol": "ACME", "has_data": True, "statements": QUARTER_STATEMENTS},
            {"symbol": "OTHER", "has_data": True, "statements": QUARTER_STATEMENTS},
        ]
        extended, vendor, stitched, skipped = extend_quarters(
            panel, records, {"ACME": "INE001A01", "OTHER": "INE002A01"}
        )
        self.assertEqual((stitched, skipped), (1, 1))
        self.assertEqual(len(vendor), 4)
        self.assertEqual(len(extended), len(panel) + 4)
        self.assertEqual(list(extended.columns), QUARTER_COLUMNS)


if __name__ == "__main__":
    unittest.main()
