"""Behavioural spec for Ind-AS XBRL parsing.

The load-bearing test here is ``test_annual_context_is_chosen_over_the_quarter``.
NSE labels the annual context ``FourD`` but declares it as a three-month period,
so any selection driven by the declared duration returns the quarter instead of
the year -- quietly, and with a plausible-looking number.
"""

import gzip
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from backtest.xbrl import (
    ANNUAL_CONTEXT,
    INSTANT_CONTEXT,
    QUARTER_CONTEXT,
    build_panel,
    coverage_summary,
    deduplicate_panel,
    derive_record,
    extract_fact,
    parse_document,
    read_document,
)

# Mirrors the real structure: FourD carries the annual figure while *declaring*
# the same three-month period as OneD, and dimensional contexts reuse both
# prefixes for segment and expense breakdowns.
DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin">
  <xbrli:context id="OneD"><xbrli:period>
    <xbrli:startDate>2024-01-01</xbrli:startDate>
    <xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="FourD"><xbrli:period>
    <xbrli:startDate>2024-01-01</xbrli:startDate>
    <xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="OneI"><xbrli:period>
    <xbrli:instant>2024-03-31</xbrli:instant></xbrli:period></xbrli:context>
  <in-bse-fin:RevenueFromOperations contextRef="OneD" unitRef="INR">3683116000.00</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:RevenueFromOperations contextRef="FourD" unitRef="INR">17585439000.00</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:RevenueFromOperations contextRef="FourReportableSegmentRevenue01D" unitRef="INR">999.00</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:ProfitBeforeExceptionalItemsAndTax contextRef="FourD" unitRef="INR">3187542000.00</in-bse-fin:ProfitBeforeExceptionalItemsAndTax>
  <in-bse-fin:ProfitBeforeTax contextRef="FourD" unitRef="INR">3187542000.00</in-bse-fin:ProfitBeforeTax>
  <in-bse-fin:FinanceCosts contextRef="FourD" unitRef="INR">30867000.00</in-bse-fin:FinanceCosts>
  <in-bse-fin:DepreciationDepletionAndAmortisationExpense contextRef="FourD" unitRef="INR">405636000.00</in-bse-fin:DepreciationDepletionAndAmortisationExpense>
  <in-bse-fin:TaxExpense contextRef="FourD" unitRef="INR">796617000.00</in-bse-fin:TaxExpense>
  <in-bse-fin:ProfitLossForPeriodFromContinuingOperations contextRef="FourD" unitRef="INR">2390925000.00</in-bse-fin:ProfitLossForPeriodFromContinuingOperations>
  <in-bse-fin:BasicEarningsLossPerShareFromContinuingOperations contextRef="FourD" unitRef="INR">52.46</in-bse-fin:BasicEarningsLossPerShareFromContinuingOperations>
  <in-bse-fin:PaidUpValueOfEquityShareCapital contextRef="FourD" unitRef="INR">455785000.00</in-bse-fin:PaidUpValueOfEquityShareCapital>
  <in-bse-fin:FaceValueOfEquityShareCapital contextRef="FourD" unitRef="INR">10.00</in-bse-fin:FaceValueOfEquityShareCapital>
  <in-bse-fin:CashFlowsFromUsedInOperatingActivities contextRef="FourD" unitRef="INR">1344615000.00</in-bse-fin:CashFlowsFromUsedInOperatingActivities>
  <in-bse-fin:Assets contextRef="OneI" unitRef="INR">15791289000.00</in-bse-fin:Assets>
  <in-bse-fin:Assets contextRef="OneReportableSegmentAssets01I" unitRef="INR">111.00</in-bse-fin:Assets>
  <in-bse-fin:Equity contextRef="OneI" unitRef="INR">12558658000.00</in-bse-fin:Equity>
  <in-bse-fin:BorrowingsNoncurrent contextRef="OneI" unitRef="INR">3681000.00</in-bse-fin:BorrowingsNoncurrent>
  <in-bse-fin:BorrowingsCurrent contextRef="OneI" unitRef="INR">1000000.00</in-bse-fin:BorrowingsCurrent>
</xbrl>
"""

PL_ONLY_DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin">
  <in-bse-fin:RevenueFromOperations contextRef="FourD" unitRef="INR">500.00</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:ProfitLossForPeriodFromContinuingOperations contextRef="FourD" unitRef="INR">50.00</in-bse-fin:ProfitLossForPeriodFromContinuingOperations>
</xbrl>
"""


class ContextSelectionTests(unittest.TestCase):
    def test_annual_context_is_chosen_over_the_quarter(self):
        """FourD declares a 3-month period but holds the 12-month figure."""
        value = extract_fact(DOCUMENT, ("RevenueFromOperations",), ANNUAL_CONTEXT)
        self.assertAlmostEqual(value, 17585439000.00)

    def test_quarter_context_is_addressable_separately(self):
        value = extract_fact(DOCUMENT, ("RevenueFromOperations",), QUARTER_CONTEXT)
        self.assertAlmostEqual(value, 3683116000.00)

    def test_annual_and_quarter_are_not_confused(self):
        annual = extract_fact(DOCUMENT, ("RevenueFromOperations",), ANNUAL_CONTEXT)
        quarter = extract_fact(DOCUMENT, ("RevenueFromOperations",), QUARTER_CONTEXT)
        self.assertGreater(annual / quarter, 3.5)

    def test_dimensional_context_is_never_matched_by_prefix(self):
        """FourReportableSegmentRevenue01D starts with 'Four' but is a segment."""
        value = extract_fact(DOCUMENT, ("RevenueFromOperations",), ANNUAL_CONTEXT)
        self.assertNotAlmostEqual(value, 999.00)

    def test_dimensional_instant_context_is_not_matched(self):
        value = extract_fact(DOCUMENT, ("Assets",), INSTANT_CONTEXT)
        self.assertAlmostEqual(value, 15791289000.00)

    def test_hyphenated_namespace_prefix_is_matched(self):
        """in-bse-fin contains hyphens; a \\w+ prefix silently matches nothing."""
        self.assertIsNotNone(
            extract_fact(DOCUMENT, ("ProfitBeforeTax",), ANNUAL_CONTEXT)
        )

    def test_absent_tag_returns_none(self):
        self.assertIsNone(
            extract_fact(DOCUMENT, ("NotARealTag",), ANNUAL_CONTEXT)
        )

    def test_absent_context_returns_none(self):
        self.assertIsNone(
            extract_fact(DOCUMENT, ("Assets",), "NoSuchContext")
        )

    def test_tag_fallback_order_is_honoured(self):
        value = extract_fact(
            DOCUMENT,
            ("MissingPrimary", "RevenueFromOperations"),
            ANNUAL_CONTEXT,
        )
        self.assertAlmostEqual(value, 17585439000.00)


class DeriveTests(unittest.TestCase):
    def setUp(self):
        self.record = derive_record(parse_document(DOCUMENT))

    def test_revenue_is_the_annual_figure(self):
        self.assertAlmostEqual(self.record["Revenue"], 17585439000.00)

    def test_ebit_adds_finance_costs_back(self):
        self.assertAlmostEqual(self.record["EBIT"], 3187542000.00 + 30867000.00)

    def test_ebitda_adds_depreciation_to_ebit(self):
        self.assertAlmostEqual(
            self.record["EBITDA"], self.record["EBIT"] + 405636000.00
        )

    def test_share_count_is_paid_up_over_face_value(self):
        self.assertAlmostEqual(self.record["Shares_Outstanding"], 45578500.0)

    def test_derived_shares_reproduce_the_reported_eps(self):
        """Cross-check: PAT / derived shares must equal the filed EPS."""
        implied = self.record["PAT"] / self.record["Shares_Outstanding"]
        self.assertAlmostEqual(implied, self.record["EPS_Basic"], places=2)

    def test_total_debt_sums_current_and_noncurrent_borrowings(self):
        self.assertAlmostEqual(self.record["Total_Debt"], 4681000.00)

    def test_operating_margin_uses_ebit_over_revenue(self):
        self.assertAlmostEqual(
            self.record["Operating_Margin"],
            self.record["EBIT"] / self.record["Revenue"],
        )

    def test_interest_coverage_is_ebit_over_finance_costs(self):
        self.assertAlmostEqual(self.record["Interest_Coverage"], 3218409000.0 / 30867000.0)

    def test_balance_sheet_presence_is_flagged(self):
        self.assertTrue(self.record["Has_Balance_Sheet"])
        self.assertTrue(self.record["Has_Cash_Flow"])

    def test_pl_only_document_reports_absent_balance_sheet(self):
        record = derive_record(parse_document(PL_ONLY_DOCUMENT))
        self.assertFalse(record["Has_Balance_Sheet"])
        self.assertIsNone(record["Total_Assets"])
        self.assertAlmostEqual(record["Revenue"], 500.0)

    def test_missing_denominator_yields_none_not_infinity(self):
        record = derive_record(parse_document(PL_ONLY_DOCUMENT))
        self.assertIsNone(record["Interest_Coverage"])
        self.assertIsNone(record["Shares_Outstanding"])

    def test_empty_document_produces_no_facts(self):
        record = derive_record(parse_document("<xbrl></xbrl>"))
        self.assertIsNone(record["Revenue"])


class PanelTests(unittest.TestCase):
    def write(self, root, seq, period, text):
        path = Path(root) / f"{seq}.xml.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_build_panel_parses_cached_documents(self):
        with TemporaryDirectory() as tmp:
            self.write(tmp, "1", "2024-03-31", DOCUMENT)
            filings = pd.DataFrame(
                [
                    {
                        "Seq_Number": "1",
                        "Period_End": "2024-03-31",
                        "Security_ID": "INE001A01",
                        "ISIN": "INE001A01036",
                        "Symbol": "ALPHA",
                        "Available_From": "2024-05-02",
                        "Filing_Timestamp": "2024-04-30T18:00:00",
                        "Is_Consolidated": True,
                    }
                ]
            )
            panel = build_panel(
                filings, lambda seq, period: Path(tmp) / f"{seq}.xml.gz"
            )
            self.assertEqual(len(panel), 1)
            self.assertEqual(panel["Fiscal_Year"].iloc[0], 2024)
            self.assertAlmostEqual(panel["Revenue"].iloc[0], 17585439000.00)

    def test_missing_document_is_skipped_not_fatal(self):
        with TemporaryDirectory() as tmp:
            filings = pd.DataFrame(
                [{"Seq_Number": "missing", "Period_End": "2024-03-31"}]
            )
            panel = build_panel(
                filings, lambda seq, period: Path(tmp) / f"{seq}.xml.gz"
            )
            self.assertTrue(panel.empty)

    def test_read_document_on_a_missing_path_returns_none(self):
        self.assertIsNone(read_document(Path("no-such-file.xml.gz")))


class DeduplicationTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame(
            [
                {
                    "Security_ID": "INE001A01", "Fiscal_Year": 2024,
                    "Is_Consolidated": False, "Has_Balance_Sheet": True,
                    "Available_From": "2024-05-02", "Revenue": 100.0,
                },
                {
                    "Security_ID": "INE001A01", "Fiscal_Year": 2024,
                    "Is_Consolidated": True, "Has_Balance_Sheet": False,
                    "Available_From": "2024-05-02", "Revenue": 200.0,
                },
                {
                    "Security_ID": "INE001A01", "Fiscal_Year": 2023,
                    "Is_Consolidated": True, "Has_Balance_Sheet": True,
                    "Available_From": "2023-05-02", "Revenue": 90.0,
                },
            ]
        )

    def test_one_row_per_security_and_year(self):
        deduped = deduplicate_panel(self.frame())
        self.assertEqual(len(deduped), 2)

    def test_consolidated_is_preferred(self):
        deduped = deduplicate_panel(self.frame())
        row = deduped[deduped["Fiscal_Year"] == 2024].iloc[0]
        self.assertAlmostEqual(row["Revenue"], 200.0)

    def test_balance_sheet_breaks_ties_within_the_same_basis(self):
        frame = self.frame()
        frame.loc[0, "Is_Consolidated"] = True
        frame.loc[1, "Has_Balance_Sheet"] = False
        deduped = deduplicate_panel(frame)
        row = deduped[deduped["Fiscal_Year"] == 2024].iloc[0]
        self.assertTrue(bool(row["Has_Balance_Sheet"]))

    def test_empty_frame_passes_through(self):
        self.assertTrue(deduplicate_panel(pd.DataFrame()).empty)


class CoverageTests(unittest.TestCase):
    def test_summary_reports_field_coverage(self):
        panel = pd.DataFrame(
            {
                "Security_ID": ["A", "B"],
                "Fiscal_Year": [2024, 2024],
                "Revenue": [1.0, 2.0],
                "Total_Assets": [1.0, None],
            }
        )
        summary = coverage_summary(panel)
        self.assertEqual(summary["company_years"], 2)
        self.assertEqual(summary["securities"], 2)
        self.assertAlmostEqual(summary["pct_revenue"], 100.0)
        self.assertAlmostEqual(summary["pct_total_assets"], 50.0)

    def test_summary_carries_the_coverage_caveat(self):
        panel = pd.DataFrame(
            {"Security_ID": ["A"], "Fiscal_Year": [2024], "Revenue": [1.0]}
        )
        self.assertIn("balance sheet", coverage_summary(panel)["note"].lower())

    def test_empty_panel_is_safe(self):
        self.assertEqual(coverage_summary(pd.DataFrame())["company_years"], 0)


if __name__ == "__main__":
    unittest.main()
