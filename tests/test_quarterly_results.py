"""Latest-quarter growth measured from the exchange's results filings.

Regression for the September 2026 results season: companies had filed their
quarter with NSE days earlier while the vendor's quote metadata still described
June, so the growth block ranked them on the quarter before.
"""

import re
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from screener.markets import resolve
from screener.quarterly_results import (
    STATUS_DISABLED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    VENDOR_QUARTER_COLUMN,
    QuarterlyResultsCollector,
    normalise_index,
    parse_quarter_facts,
    plan_documents,
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


def _seq(url):
    return re.search(r"_(\d+)_WEB", url).group(1)


class FakeFetcher:
    """Serves documents by filing id and records what was asked for."""

    def __init__(self, documents):
        self.documents = dict(documents)
        self.calls = []

    def fetch_many(self, urls):
        self.calls.append(list(urls))
        return [self.documents.get(_seq(url)) for url in urls]

    @property
    def asked(self):
        return [_seq(url) for call in self.calls for url in call]


class CollectorCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output_dir = Path(self._tmp.name)

    def collector(self, filings, documents, *, enabled=True, index_error=None, **settings):
        config = SimpleNamespace(
            OUTPUT_DIR=self.output_dir,
            QUARTERLY_RESULTS_FILINGS_ENABLED=enabled,
            **settings,
        )
        index_calls = []

        def index_loader(start, end):
            index_calls.append((start, end))
            if index_error is not None:
                raise index_error
            return normalise_index(filings)

        fetcher = FakeFetcher(documents)
        collector = QuarterlyResultsCollector(
            config,
            provider="nse_integrated_filings",
            index_loader=index_loader,
            document_fetcher=fetcher,
            clock=lambda: datetime(2026, 10, 12, 18, 30),
        )
        collector.index_calls = index_calls
        return collector, fetcher


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


class PlanTests(unittest.TestCase):
    def plan(self, filings, **kwargs):
        kwargs.setdefault("today", TODAY)
        kwargs.setdefault("max_age_days", 200)
        plan = plan_documents(normalise_index(filings), **kwargs)
        return {symbol: (a["Seq_Id"], b["Seq_Id"]) for symbol, (a, b) in plan.items()}

    def test_the_latest_quarter_and_the_one_a_year_before_it(self):
        plan = self.plan(
            [
                _filing("AAA", "30-SEP-2026", 4),
                _filing("AAA", "30-JUN-2026", 3),
                _filing("AAA", "30-SEP-2025", 2),
                _filing("AAA", "30-JUN-2025", 1),
            ]
        )
        self.assertEqual(plan, {"AAA": ("4", "2")})

    def test_consolidated_is_preferred_when_both_bases_reach_the_same_quarter(self):
        plan = self.plan(
            [
                _filing("AAA", "30-SEP-2026", 4, consolidated=True),
                _filing("AAA", "30-SEP-2025", 3, consolidated=True),
                _filing("AAA", "30-SEP-2026", 2, consolidated=False),
                _filing("AAA", "30-SEP-2025", 1, consolidated=False),
            ]
        )
        self.assertEqual(plan, {"AAA": ("4", "3")})

    def test_a_basis_with_no_year_ago_quarter_gives_way_to_one_that_has_it(self):
        # First consolidated filing this year: nothing to compare it with.
        plan = self.plan(
            [
                _filing("AAA", "30-SEP-2026", 4, consolidated=True),
                _filing("AAA", "30-SEP-2026", 2, consolidated=False),
                _filing("AAA", "30-SEP-2025", 1, consolidated=False),
            ]
        )
        self.assertEqual(plan, {"AAA": ("2", "1")})

    def test_a_quarter_too_old_to_be_current_is_not_planned(self):
        plan = self.plan(
            [_filing("AAA", "31-DEC-2025", 2), _filing("AAA", "31-DEC-2024", 1)]
        )
        self.assertEqual(plan, {})

    def test_a_taxonomy_that_is_not_read_is_left_to_the_vendor(self):
        plan = self.plan(
            [
                _filing("AAA", "30-SEP-2026", 2, taxonomy="BANKING"),
                _filing("AAA", "30-SEP-2025", 1, taxonomy="BANKING"),
            ]
        )
        self.assertEqual(plan, {})

    def test_a_document_found_empty_sends_the_symbol_to_its_next_pair(self):
        filings = [
            _filing("AAA", "30-SEP-2026", 4, consolidated=True),
            _filing("AAA", "30-SEP-2025", 3, consolidated=True),
            _filing("AAA", "30-SEP-2026", 2, consolidated=False),
            _filing("AAA", "30-SEP-2025", 1, consolidated=False),
        ]
        self.assertEqual(
            self.plan(filings, unusable=frozenset({"4"})), {"AAA": ("2", "1")}
        )


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
        self.assertEqual(diagnostics["quarter_results_documents_fetched"], 2)
        self.assertEqual(diagnostics["quarter_results_documents_failed"], 0)

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

    def test_an_empty_document_falls_back_to_the_other_basis_in_the_same_run(self):
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
        collector, fetcher = self.collector(filings, documents)
        enriched = collector.enrich(_frame(AAA=(0.02, 0.03)))
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)
        self.assertAlmostEqual(enriched.loc[0, "Earnings_Growth"], -0.10)
        self.assertEqual(sorted(fetcher.asked), ["11", "12", "21", "22"])


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


class CacheTests(CollectorCase):
    FILINGS = (
        _filing("AAA", "30-JUN-2026", 12, broadcast="20-Jul-2026 18:00:00"),
        _filing("AAA", "30-JUN-2025", 11, broadcast="21-Jul-2025 18:00:00"),
    )
    DOCUMENTS = {"12": _document(1100.0, 220.0), "11": _document(1000.0, 200.0)}

    def test_a_cached_filing_is_not_fetched_again(self):
        first, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        first.enrich(_frame(AAA=(0.0, 0.0)))
        second, fetcher = self.collector(self.FILINGS, self.DOCUMENTS)
        enriched = second.enrich(_frame(AAA=(0.0, 0.0)))
        self.assertEqual(fetcher.calls, [])
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)

    def test_a_new_quarter_fetches_only_its_own_pair(self):
        first, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        first.enrich(_frame(AAA=(0.0, 0.0)))
        filings = [
            *self.FILINGS,
            _filing("AAA", "30-SEP-2026", 14),
            _filing("AAA", "30-SEP-2025", 13, broadcast="09-Oct-2025 19:00:00"),
        ]
        documents = {
            **self.DOCUMENTS,
            "14": _document(1300.0, 150.0),
            "13": _document(1000.0, 200.0),
        }
        second, fetcher = self.collector(filings, documents)
        enriched = second.enrich(_frame(AAA=(0.0, 0.0)))
        self.assertEqual(sorted(fetcher.asked), ["13", "14"])
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.30)
        self.assertAlmostEqual(enriched.loc[0, "Earnings_Growth"], -0.25)

    def test_a_revision_is_fetched_and_replaces_the_cached_figures(self):
        first, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        first.enrich(_frame(AAA=(0.0, 0.0)))
        filings = [
            *self.FILINGS,
            _filing(
                "AAA", "30-JUN-2026", 19, broadcast=None,
                revised="05-OCT-2026 10:00:00",
            ),
        ]
        documents = {**self.DOCUMENTS, "19": _document(1200.0, 220.0)}
        second, fetcher = self.collector(filings, documents)
        enriched = second.enrich(_frame(AAA=(0.0, 0.0)))
        self.assertEqual(fetcher.asked, ["19"])
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.20)

    def test_an_unreadable_index_still_scores_the_cached_filings(self):
        first, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        first.enrich(_frame(AAA=(0.0, 0.0)))
        second, fetcher = self.collector(
            self.FILINGS, self.DOCUMENTS, index_error=ConnectionError("blocked")
        )
        with self.assertLogs("screener.quarterly_results", level="WARNING"):
            enriched = second.enrich(_frame(AAA=(0.0, 0.0), BBB=(0.07, 0.09)))
        self.assertEqual(fetcher.calls, [])
        self.assertEqual(
            second.diagnostics["quarter_results_source_status"], STATUS_UNAVAILABLE
        )
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)
        self.assertAlmostEqual(enriched.loc[1, "Revenue_Growth"], 0.07)

    def test_an_unreadable_index_with_no_cache_leaves_the_frame_as_served(self):
        collector, _ = self.collector(
            self.FILINGS, self.DOCUMENTS, index_error=ConnectionError("blocked")
        )
        frame = _frame(AAA=(0.02, 0.03))
        with self.assertLogs("screener.quarterly_results", level="WARNING"):
            enriched = collector.enrich(frame)
        pd.testing.assert_frame_equal(enriched, frame)

    def test_a_failed_document_is_asked_for_again_on_the_next_run(self):
        first, _ = self.collector(self.FILINGS, {"11": _document(1000.0, 200.0)})
        with self.assertLogs("screener.quarterly_results", level="WARNING"):
            enriched = first.enrich(_frame(AAA=(0.02, 0.03)))
        self.assertEqual(first.diagnostics["quarter_results_documents_failed"], 1)
        # Half a pair is not a growth rate: the vendor's figure stands.
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.02)
        second, fetcher = self.collector(self.FILINGS, self.DOCUMENTS)
        enriched = second.enrich(_frame(AAA=(0.02, 0.03)))
        self.assertEqual(fetcher.asked, ["12"])
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.10)

    def test_a_capped_cold_build_fetches_the_most_traded_names_first(self):
        filings = [
            *self.FILINGS,
            _filing("BBB", "30-JUN-2026", 32, broadcast="20-Jul-2026 18:00:00"),
            _filing("BBB", "30-JUN-2025", 31, broadcast="21-Jul-2025 18:00:00"),
        ]
        documents = {
            **self.DOCUMENTS,
            "32": _document(900.0, 90.0),
            "31": _document(600.0, 60.0),
        }
        # BBB is listed first and so carries the larger turnover.
        frame = _frame(BBB=(0.01, 0.01), AAA=(0.02, 0.03))
        first, fetcher = self.collector(
            filings, documents, QUARTERLY_RESULTS_MAX_DOCUMENTS_PER_RUN=2
        )
        with self.assertLogs("screener.quarterly_results", level="WARNING"):
            enriched = first.enrich(frame)
        self.assertEqual(sorted(fetcher.asked), ["31", "32"])
        self.assertEqual(first.diagnostics["quarter_results_documents_deferred"], 2)
        self.assertAlmostEqual(enriched.loc[0, "Revenue_Growth"], 0.50)
        self.assertAlmostEqual(enriched.loc[1, "Revenue_Growth"], 0.02)
        second, fetcher = self.collector(
            filings, documents, QUARTERLY_RESULTS_MAX_DOCUMENTS_PER_RUN=2
        )
        enriched = second.enrich(frame)
        self.assertEqual(sorted(fetcher.asked), ["11", "12"])
        self.assertAlmostEqual(enriched.loc[1, "Revenue_Growth"], 0.10)

    def test_a_cache_from_another_schema_is_rebuilt(self):
        first, _ = self.collector(self.FILINGS, self.DOCUMENTS)
        first.enrich(_frame(AAA=(0.0, 0.0)))
        path = self.output_dir / "quarterly_results_cache.csv"
        cached = pd.read_csv(path)
        cached["Schema_Version"] = 0
        cached.to_csv(path, index=False)
        second, fetcher = self.collector(self.FILINGS, self.DOCUMENTS)
        second.enrich(_frame(AAA=(0.0, 0.0)))
        self.assertEqual(sorted(fetcher.asked), ["11", "12"])


class WiringTests(CollectorCase):
    def test_disabled_touches_neither_the_exchange_nor_the_frame(self):
        collector, fetcher = self.collector(
            OverlayTests.FILINGS, OverlayTests.DOCUMENTS, enabled=False
        )
        frame = _frame(AAA=(0.02, 0.03))
        self.assertIs(collector.enrich(frame), frame)
        self.assertEqual(collector.index_calls, [])
        self.assertEqual(fetcher.calls, [])
        self.assertEqual(
            collector.diagnostics, {"quarter_results_source_status": STATUS_DISABLED}
        )

    def test_a_market_with_no_filing_index_is_disabled_even_when_switched_on(self):
        config = SimpleNamespace(
            OUTPUT_DIR=self.output_dir,
            QUARTERLY_RESULTS_FILINGS_ENABLED=True,
            MARKET="US",
        )
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

    def test_the_nse_workflow_opts_in_and_keeps_the_cache(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        text = (workflows / "daily-stock-screener.yml").read_text()
        self.assertRegex(
            text, re.compile(r'QUARTERLY_RESULTS_FILINGS_ENABLED:\s*"True"')
        )
        # Restored before the run and saved after it; without both, every run
        # would be a cold build of the whole universe.
        self.assertGreaterEqual(
            text.count("reports_advanced/quarterly_results_cache.csv"), 2
        )

    def test_the_us_workflow_does_not_opt_in(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        text = (workflows / "daily-us-screener.yml").read_text()
        self.assertNotIn("QUARTERLY_RESULTS_FILINGS_ENABLED", text)


if __name__ == "__main__":
    unittest.main()
