"""Latest-quarter growth measured from the exchange's results filings.

Regression for the September 2026 results season: companies had filed their
quarter with NSE days earlier while the vendor's quote metadata still described
June, so the growth block ranked them on the quarter before.
"""

import re
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from screener.markets import resolve
from screener.quarterly_results import (
    STATUS_DISABLED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    SUPPORTED_TAXONOMIES,
    VENDOR_QUARTER_COLUMN,
    QuarterlyResultsCollector,
    facts_frame,
    normalise_index,
    parse_filing,
    parse_quarter_facts,
    quarter_growth,
    taxonomy_of,
    vendor_quarter_end,
)
from tests.test_markets import config_with_env_cleared

TODAY = date(2026, 10, 12)
ARCHIVE = "https://archive.example/xbrl"


def _filing(
    symbol,
    quarter,
    seq,
    *,
    consolidated=True,
    taxonomy="INDAS",
    broadcast="08-Oct-2026 22:07:33",
    revised=None,
):
    """One row of the exchange's filing index, as it is served."""
    return {
        "symbol": symbol,
        "qe_Date": quarter,
        "consolidated": "Consolidated" if consolidated else "Standalone",
        "seq_Id": str(seq),
        "broadcast_Date": broadcast,
        "revised_Date": revised,
        "creation_Date": broadcast or revised,
        "type_Sub": "Revision" if revised else "Original",
        "xbrl": f"{ARCHIVE}/INTEGRATED_FILING_{taxonomy}_{seq}_WEB.xml",
    }


def _document(revenue=None, profit=None, *, profit_tag="ProfitLossForPeriod"):
    """A results document: the quarter, the year to date and one segment."""
    facts = []
    if revenue is not None:
        facts += [
            f'<in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR" '
            f'decimals="-5">{revenue}</in-capmkt:RevenueFromOperations>',
            # The year to date and a segment share the tag; neither is the quarter.
            f'<in-capmkt:RevenueFromOperations contextRef="FourD" unitRef="INR">'
            f"{revenue * 2}</in-capmkt:RevenueFromOperations>",
            f'<in-capmkt:RevenueFromOperations contextRef="OneReportable1D" '
            f'unitRef="INR">{revenue / 4}</in-capmkt:RevenueFromOperations>',
        ]
    if profit is not None:
        facts.append(
            f'<in-capmkt:{profit_tag} unitRef="INR" contextRef="OneD">'
            f"{profit}</in-capmkt:{profit_tag}>"
        )
    return "<xbrli:xbrl>" + "".join(facts) + "</xbrli:xbrl>"


def _stored(filings, documents):
    """What `workers.quarterly_filings` would have stored from these filings.

    A document that could not be fetched (absent from ``documents``) is not
    stored; a taxonomy that is not read is never fetched.
    """
    rows = []
    for row in normalise_index(filings).to_dict("records"):
        text = documents.get(row["Seq_Id"])
        if text is None or row["Taxonomy"] not in SUPPORTED_TAXONOMIES:
            continue
        lines = parse_filing(text)
        rows.append(
            {
                "symbol": row["Symbol"],
                "period_end": row["Period_End"].isoformat(),
                "is_consolidated": row["Is_Consolidated"],
                "seq_id": row["Seq_Id"],
                "filed_at": row["Filed_At"]
                .replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                .isoformat(),
                "taxonomy": row["Taxonomy"],
                "revenue": lines["revenue"],
                "pat": lines["pat"],
            }
        )
    return rows


class CollectorCase(unittest.TestCase):
    def collector(self, filings, documents, *, enabled=True, store_error=None, **settings):
        config = SimpleNamespace(QUARTERLY_RESULTS_FILINGS_ENABLED=enabled, **settings)
        loads = []

        def filings_loader(since):
            loads.append(since)
            if store_error is not None:
                raise store_error
            return _stored(filings, documents)

        collector = QuarterlyResultsCollector(
            config,
            provider="nse_integrated_filings",
            filings_loader=filings_loader,
            clock=lambda: datetime(2026, 10, 12, 18, 30),
        )
        collector.loads = loads
        return collector, loads


def _frame(**growth):
    """A merged research frame carrying the vendor's two figures."""
    symbols = list(growth)
    return pd.DataFrame(
        {
            "Symbol": symbols,
            "Revenue_Growth": [growth[s][0] for s in symbols],
            "Earnings_Growth": [growth[s][1] for s in symbols],
            "Avg_Turnover_INR": [float(len(symbols) - i) for i in range(len(symbols))],
        }
    )


class IndexTests(unittest.TestCase):
    def test_a_revision_replaces_the_filing_it_revises(self):
        index = normalise_index(
            [
                _filing("AAA", "30-JUN-2026", 100, broadcast="20-Jul-2026 18:00:00"),
                # A revision is served with no broadcast time at all.
                _filing(
                    "AAA", "30-JUN-2026", 180, broadcast=None,
                    revised="05-OCT-2026 13:50:56",
                ),
            ]
        )
        self.assertEqual(index["Seq_Id"].tolist(), ["180"])
        self.assertEqual(index.loc[0, "Period_End"], date(2026, 6, 30))
        self.assertEqual(index.loc[0, "Filed_At"], datetime(2026, 10, 5, 13, 50, 56))

    def test_each_basis_of_a_quarter_is_its_own_row(self):
        index = normalise_index(
            [
                _filing("AAA", "30-SEP-2026", 1, consolidated=True),
                _filing("AAA", "30-SEP-2026", 2, consolidated=False),
            ]
        )
        self.assertEqual(sorted(index["Is_Consolidated"]), [False, True])

    def test_a_filing_that_cannot_be_placed_is_dropped(self):
        no_quarter = _filing("AAA", None, 1)
        no_document = {**_filing("AAA", "30-SEP-2026", 2), "xbrl": None}
        no_symbol = _filing("", "30-SEP-2026", 3)
        self.assertTrue(normalise_index([no_quarter, no_document, no_symbol]).empty)
        self.assertTrue(normalise_index([]).empty)

    def test_the_taxonomy_is_read_from_the_document_link(self):
        self.assertEqual(
            taxonomy_of(f"{ARCHIVE}/INTEGRATED_FILING_BANKING_7_WEB.xml"), "BANKING"
        )
        self.assertEqual(taxonomy_of(f"{ARCHIVE}/something_else.xml"), "")


class DocumentTests(unittest.TestCase):
    def test_only_the_quarters_own_context_is_read(self):
        facts = parse_quarter_facts(_document(revenue=400.0, profit=50.0))
        self.assertEqual(facts, {"Revenue": 400.0, "PAT": 50.0})

    def test_the_indian_gaap_profit_tag_is_read(self):
        facts = parse_quarter_facts(
            _document(revenue=400.0, profit=30.0, profit_tag="ProfitLossForThePeriod")
        )
        self.assertEqual(facts["PAT"], 30.0)

    def test_an_unreported_line_is_absent_not_zero(self):
        facts = parse_quarter_facts(_document(revenue=400.0))
        self.assertIsNone(facts["PAT"])


class StoredFilingTests(unittest.TestCase):
    def test_everything_the_page_and_the_growth_block_read_is_parsed(self):
        lines = parse_filing(_document(revenue=400.0, profit=50.0))
        self.assertEqual(lines["revenue"], 400.0)
        self.assertEqual(lines["net_profit"], 50.0)
        self.assertEqual(lines["pat"], 50.0)
        self.assertIsNone(lines["pbt"])

    def test_a_banks_lines_mean_what_the_vendor_means_by_them(self):
        # SOUTHBANK, June 2026 quarter, in lakh: the vendor's revenue is net
        # interest income plus other income, its interest is interest expended.
        tags = {
            "InterestEarned": 2627.8, "InterestExpended": 1603.1, "OtherIncome": 379.5,
            "ProfitLossFromOrdinaryActivitiesBeforeTax": 507.5, "TaxExpense": 129.8,
            "ProfitLossForThePeriod": 377.6,
            # A consolidated filer that leaves the owners' share at nil.
            "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates": 0,
            "DilutedEarningsPerShareAfterExtraordinaryItems": 1.44,
        }
        text = "<xbrli:xbrl>" + "".join(
            f'<in-capmkt:{tag} contextRef="OneD">{value}</in-capmkt:{tag}>'
            for tag, value in tags.items()
        ) + "</xbrli:xbrl>"
        lines = parse_filing(text, "BANKING")
        self.assertAlmostEqual(lines["net_interest_income"], 1024.7)
        self.assertAlmostEqual(lines["revenue"], 1404.2)
        self.assertEqual(lines["interest"], 1603.1)
        self.assertEqual((lines["pbt"], lines["tax"], lines["eps"]), (507.5, 129.8, 1.44))
        self.assertEqual(lines["net_profit"], 377.6)
        self.assertIsNone(lines["operating_profit"])

    def test_an_insurers_profit_is_the_shareholders_account(self):
        # A life insurer files a policyholders' tax line too; it is not the company's.
        text = (
            '<xbrli:xbrl><in-capmkt:NetPremiumIncome contextRef="OneD">2553'
            '</in-capmkt:NetPremiumIncome><in-capmkt:ProvisionForTax contextRef="OneD">0'
            '</in-capmkt:ProvisionForTax><in-capmkt:ProvisionsForTaxes contextRef="OneD">5'
            '</in-capmkt:ProvisionsForTaxes><in-capmkt:ProfitLossAfterTaxAndExtraordinaryItems'
            ' contextRef="OneD">43</in-capmkt:ProfitLossAfterTaxAndExtraordinaryItems>'
            "</xbrli:xbrl>"
        )
        lines = parse_filing(text, "LI")
        self.assertEqual((lines["revenue"], lines["tax"], lines["net_profit"]), (2553, 5, 43))
        self.assertIsNone(lines["pbt"])

    def test_banks_and_insurers_keep_the_vendors_growth(self):
        facts = facts_frame(
            [{"symbol": "BNK", "period_end": "2026-09-30", "is_consolidated": True,
              "seq_id": "1", "filed_at": "2026-10-12T19:00:00+00:00",
              "taxonomy": "BANKING", "revenue": 1.0, "pat": 1.0}],
            "Asia/Kolkata",
        )
        self.assertTrue(facts.empty)

    def test_the_filing_date_is_the_exchanges_local_date(self):
        # 00:30 in India on the 13th is still the 12th in UTC.
        facts = facts_frame(
            [{"symbol": "aaa", "period_end": "2026-09-30", "is_consolidated": True,
              "seq_id": "1", "filed_at": "2026-10-12T19:00:00+00:00",
              "taxonomy": "INDAS", "revenue": 1.0, "pat": None}],
            "Asia/Kolkata",
        )
        self.assertEqual(facts.loc[0, "Symbol"], "AAA")
        self.assertEqual(facts.loc[0, "Filed_On"], date(2026, 10, 13))
        self.assertEqual(facts.loc[0, "Period_End"], date(2026, 9, 30))

    def test_no_rows_is_an_empty_frame_with_the_fact_columns(self):
        self.assertIn("Revenue", facts_frame([], "Asia/Kolkata").columns)


class GrowthTests(unittest.TestCase):
    def test_a_filing_made_today_is_visible_today(self):
        facts = pd.DataFrame(
            {
                "Symbol": ["AAA", "AAA"],
                "Period_End": ["2026-09-30", "2025-09-30"],
                "Is_Consolidated": [True, True],
                "Filed_On": [TODAY.isoformat(), "2025-10-10"],
                "Revenue": [120.0, 100.0],
                "PAT": [30.0, 20.0],
            }
        )
        growth = quarter_growth(facts, ["AAA"], today=TODAY, max_age_days=200)
        row = growth.iloc[0]
        self.assertAlmostEqual(row["Revenue_Growth"], 0.2)
        self.assertAlmostEqual(row["Earnings_Growth"], 0.5)
        self.assertEqual(row["Quarter_Period_End"], "2026-09-30")
        self.assertEqual(row["Quarter_Basis"], "consolidated")

    def test_no_facts_is_an_empty_frame_with_the_growth_columns(self):
        growth = quarter_growth(None, ["AAA"], today=TODAY, max_age_days=200)
        self.assertTrue(growth.empty)
        self.assertIn("Revenue_Growth", growth.columns)


class OverlayTests(CollectorCase):
    FILINGS = (
        _filing("AAA", "30-SEP-2026", 12),
        _filing("AAA", "30-SEP-2025", 11, broadcast="09-Oct-2025 19:00:00"),
    )
    DOCUMENTS = {"12": _document(1150.0, 240.0), "11": _document(1000.0, 200.0)}

    def test_a_reported_quarter_replaces_the_vendors_stale_figures(self):
        collector, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        enriched = collector.enrich(_frame(AAA=(0.02, 0.03), BBB=(0.08, -0.04)))
        by_symbol = enriched.set_index("Symbol")
        self.assertAlmostEqual(by_symbol.loc["AAA", "Revenue_Growth"], 0.15)
        self.assertAlmostEqual(by_symbol.loc["AAA", "Earnings_Growth"], 0.20)
        # No filings for this one: the vendor's figures are scored as served.
        self.assertAlmostEqual(by_symbol.loc["BBB", "Revenue_Growth"], 0.08)
        self.assertAlmostEqual(by_symbol.loc["BBB", "Earnings_Growth"], -0.04)

    def test_the_run_diagnostics_name_what_the_filings_served(self):
        collector, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        collector.enrich(_frame(AAA=(0.02, 0.03), BBB=(0.08, -0.04)))
        diagnostics = collector.diagnostics
        self.assertEqual(diagnostics["quarter_results_source_status"], STATUS_OK)
        self.assertEqual(diagnostics["quarter_results_filing_symbols"], ["AAA"])
        self.assertEqual(
            diagnostics["quarter_results_latest_quarter_counts"], {"2026-09-30": 1}
        )
        self.assertEqual(diagnostics["quarter_results_filings_read"], 2)
        self.assertEqual(diagnostics["quarter_results_latest_filed_on"], "2026-10-08")

    def test_a_loss_in_the_base_quarter_is_unreported_not_the_vendors_figure(self):
        documents = {"12": _document(1150.0, 240.0), "11": _document(1000.0, -50.0)}
        collector, _ = self.collector(self.FILINGS, documents)
        enriched = collector.enrich(_frame(AAA=(0.02, 0.03)))
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.15)
        # The vendor's 0.03 describes another quarter; it is not carried over.
        self.assertTrue(np.isnan(enriched.loc[0, "Earnings_Growth"]))

    def test_the_frame_keeps_its_rows_order_and_other_columns(self):
        collector, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        frame = _frame(BBB=(0.08, -0.04), AAA=(0.02, 0.03))
        enriched = collector.enrich(frame)
        self.assertEqual(enriched["Symbol"].tolist(), ["BBB", "AAA"])
        self.assertEqual(list(enriched.columns), list(frame.columns))
        # The caller's frame is not modified in place.
        self.assertAlmostEqual(frame.loc[1, "Revenue_Growth"], 0.02)

    def test_a_frame_without_the_vendor_columns_still_gets_the_figures(self):
        collector, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        enriched = collector.enrich(pd.DataFrame({"Symbol": ["AAA", "BBB"]}))
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.15)
        self.assertTrue(np.isnan(enriched.loc[1, "Revenue_Growth"]))

    def test_an_empty_filing_falls_back_to_the_other_basis(self):
        filings = [
            *self.FILINGS,
            _filing("AAA", "30-SEP-2026", 22, consolidated=False),
            _filing("AAA", "30-SEP-2025", 21, consolidated=False),
        ]
        documents = {
            "12": _document(),  # the consolidated filing carries neither figure
            "11": _document(1000.0, 200.0),
            "22": _document(550.0, 90.0),
            "21": _document(500.0, 100.0),
        }
        collector, _ = self.collector(filings, documents)
        enriched = collector.enrich(_frame(AAA=(0.02, 0.03)))
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)
        self.assertAlmostEqual(enriched.loc[0, "Earnings_Growth"], -0.10)


class VendorQuarterTests(CollectorCase):
    """A filing is preferred only when it is at least as recent as the vendor."""

    FILINGS = (
        _filing("AAA", "30-JUN-2026", 12, broadcast="20-Jul-2026 18:00:00"),
        _filing("AAA", "30-JUN-2025", 11, broadcast="21-Jul-2025 18:00:00"),
    )
    DOCUMENTS = {"12": _document(1100.0, 220.0), "11": _document(1000.0, 200.0)}

    def enrich(self, vendor_quarter):
        collector, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        frame = _frame(AAA=(0.02, 0.03))
        frame[VENDOR_QUARTER_COLUMN] = [vendor_quarter]
        return collector, collector.enrich(frame)

    def test_a_vendor_already_on_a_later_quarter_keeps_its_figures(self):
        # The September filing is missing from the index; the vendor has it.
        collector, enriched = self.enrich("2026-09-30")
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.02)
        self.assertAlmostEqual(enriched.loc[0, "Earnings_Growth"], 0.03)
        self.assertEqual(collector.diagnostics["quarter_results_filing_symbols"], [])
        self.assertEqual(
            collector.diagnostics["quarter_results_vendor_newer_symbols"], ["AAA"]
        )

    def test_the_same_quarter_is_measured_from_the_filing(self):
        _, enriched = self.enrich("2026-06-30")
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)

    def test_a_vendor_on_an_earlier_quarter_gives_way(self):
        collector, enriched = self.enrich("2026-03-31")
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)
        self.assertEqual(
            collector.diagnostics["quarter_results_vendor_newer_symbols"], []
        )

    def test_an_unknown_vendor_quarter_gives_way(self):
        for unknown in (None, np.nan, ""):
            with self.subTest(unknown=unknown):
                _, enriched = self.enrich(unknown)
                self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)

    def test_the_vendor_quarter_never_reaches_the_export(self):
        _, enriched = self.enrich("2026-06-30")
        self.assertNotIn(VENDOR_QUARTER_COLUMN, enriched.columns)
        _, kept = self.enrich("2026-09-30")
        self.assertNotIn(VENDOR_QUARTER_COLUMN, kept.columns)
        disabled, _ = self.collector(self.FILINGS, self.DOCUMENTS, enabled=False)
        frame = _frame(AAA=(0.02, 0.03))
        frame[VENDOR_QUARTER_COLUMN] = ["2026-06-30"]
        untouched = disabled.enrich(frame)
        self.assertNotIn(VENDOR_QUARTER_COLUMN, untouched.columns)
        self.assertAlmostEqual(untouched.loc[0, "Revenue_Growth"], 0.02)

    def test_the_vendors_epoch_is_read_as_a_quarter_end(self):
        self.assertEqual(vendor_quarter_end(1790726400), "2026-09-30")
        for unusable in (None, "", "n/a", float("nan")):
            with self.subTest(unusable=unusable):
                self.assertIsNone(vendor_quarter_end(unusable))


class StoreTests(CollectorCase):
    FILINGS = (
        _filing("AAA", "30-JUN-2026", 12, broadcast="20-Jul-2026 18:00:00"),
        _filing("AAA", "30-JUN-2025", 11, broadcast="21-Jul-2025 18:00:00"),
    )
    DOCUMENTS = {"12": _document(1100.0, 220.0), "11": _document(1000.0, 200.0)}

    def test_the_store_is_read_far_enough_back_for_a_year_ago_quarter(self):
        collector, loads = self.collector(self.FILINGS, self.DOCUMENTS)
        enriched = collector.enrich(_frame(AAA=(0.0, 0.0)))
        self.assertEqual(loads, [TODAY - timedelta(days=200 + 400)])
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)

    def test_a_revision_is_read_as_the_store_holds_it(self):
        filings = [
            *self.FILINGS,
            _filing(
                "AAA", "30-JUN-2026", 19, broadcast=None,
                revised="05-OCT-2026 10:00:00",
            ),
        ]
        documents = {**self.DOCUMENTS, "19": _document(1200.0, 220.0)}
        collector, _ = self.collector(filings, documents)
        enriched = collector.enrich(_frame(AAA=(0.0, 0.0)))
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.20)

    def test_a_filing_not_yet_stored_leaves_the_vendors_figures(self):
        # The worker could not fetch June 2026's document yet: half a pair is
        # not a growth rate.
        collector, _ = self.collector(self.FILINGS, {"11": _document(1000.0, 200.0)})
        enriched = collector.enrich(_frame(AAA=(0.02, 0.03)))
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.02)

    def test_a_filing_made_after_the_run_is_not_read(self):
        filings = [
            _filing("AAA", "30-SEP-2026", 14, broadcast="13-Oct-2026 17:00:00"),
            _filing("AAA", "30-SEP-2025", 13, broadcast="09-Oct-2025 19:00:00"),
        ]
        documents = {"14": _document(1300.0, 150.0), "13": _document(1000.0, 200.0)}
        collector, _ = self.collector(filings, documents)
        enriched = collector.enrich(_frame(AAA=(0.02, 0.03)))
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.02)

    def test_an_unreadable_store_leaves_the_frame_as_served(self):
        collector, _ = self.collector(
            self.FILINGS, self.DOCUMENTS, store_error=ConnectionError("blocked")
        )
        frame = _frame(AAA=(0.02, 0.03))
        with self.assertLogs("screener.quarterly_results", level="WARNING"):
            enriched = collector.enrich(frame)
        pd.testing.assert_frame_equal(enriched, frame)
        self.assertEqual(
            collector.diagnostics["quarter_results_source_status"], STATUS_UNAVAILABLE
        )

    def test_without_store_credentials_the_vendors_figures_stand(self):
        # A validation dispatch runs with no Supabase credentials.
        config = SimpleNamespace(
            QUARTERLY_RESULTS_FILINGS_ENABLED=True, SUPABASE_URL="",
            SUPABASE_SERVICE_ROLE_KEY="",
        )
        collector = QuarterlyResultsCollector(config, provider="nse_integrated_filings")
        frame = _frame(AAA=(0.02, 0.03))
        with self.assertLogs("screener.quarterly_results", level="WARNING"):
            enriched = collector.enrich(frame)
        pd.testing.assert_frame_equal(enriched, frame)
        self.assertEqual(
            collector.diagnostics["quarter_results_source_status"], STATUS_UNAVAILABLE
        )


class WiringTests(CollectorCase):
    def test_disabled_touches_neither_the_exchange_nor_the_frame(self):
        collector, loads = self.collector(
            OverlayTests.FILINGS, OverlayTests.DOCUMENTS, enabled=False
        )
        frame = _frame(AAA=(0.02, 0.03))
        self.assertIs(collector.enrich(frame), frame)
        self.assertEqual(loads, [])
        self.assertEqual(
            collector.diagnostics, {"quarter_results_source_status": STATUS_DISABLED}
        )

    def test_a_market_with_no_filing_index_is_disabled_even_when_switched_on(self):
        config = SimpleNamespace(QUARTERLY_RESULTS_FILINGS_ENABLED=True, MARKET="US")
        self.assertFalse(QuarterlyResultsCollector(config).enabled)

    def test_off_unless_a_workflow_opts_in(self):
        # The NSE workflow sets the flag at job level and it leaks into its
        # regression-test step, so the default is read with the variable cleared.
        Config = config_with_env_cleared("QUARTERLY_RESULTS_FILINGS_ENABLED")
        self.assertIs(Config.QUARTERLY_RESULTS_FILINGS_ENABLED, False)

    def test_only_nse_has_a_filing_index(self):
        self.assertEqual(
            resolve("NSE").quarterly_results_provider, "nse_integrated_filings"
        )
        self.assertIsNone(resolve("US").quarterly_results_provider)

    def test_the_nse_workflow_opts_in_and_can_read_the_store(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        text = (workflows / "daily-stock-screener.yml").read_text()
        self.assertRegex(
            text, re.compile(r'QUARTERLY_RESULTS_FILINGS_ENABLED:\s*"True"')
        )
        self.assertRegex(text, re.compile(r"\n      SUPABASE_URL:"))

    def test_the_us_workflow_does_not_opt_in(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        text = (workflows / "daily-us-screener.yml").read_text()
        self.assertNotIn("QUARTERLY_RESULTS_FILINGS_ENABLED", text)


if __name__ == "__main__":
    unittest.main()
