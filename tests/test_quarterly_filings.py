"""Storing the exchange's results filings once, for every job that reads them.

Regression for the October 2026 results season: the notification bell
announced a result from the exchange's index while the stock page, which drew
its quarters from the vendor and only reconciled a filing against it, showed
nothing for that quarter.
"""

import json
import re
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from screener.quarterly_results import PARSER_VERSION
from workers.quarterly_filings import (
    DEFAULT_LOOKBACK_DAYS,
    FULL_LOOKBACK_DAYS,
    run,
)

TODAY = date(2026, 10, 13)
ARCHIVE = "https://archive.example/xbrl"


def filing(symbol, quarter, seq, *, consolidated=True, taxonomy="INDAS",
           broadcast="13-Oct-2026 17:23:17", revised=None):
    """One row of the exchange's filing index, as it is served."""
    return {
        "symbol": symbol,
        "qe_Date": quarter,
        "consolidated": "Consolidated" if consolidated else "Standalone",
        "seq_Id": str(seq),
        "broadcast_Date": broadcast,
        "revised_Date": revised,
        "xbrl": f"{ARCHIVE}/INTEGRATED_FILING_{taxonomy}_{seq}_WEB.xml",
        "ixbrl": f"{ARCHIVE}/INTEGRATED_FILING_{taxonomy}_{seq}_iXBRL_WEB.html",
        "cmName": f"{symbol} Limited",
    }


def document(revenue, profit):
    return (
        "<xbrli:xbrl>"
        f'<in-capmkt:RevenueFromOperations contextRef="OneD">{revenue}'
        "</in-capmkt:RevenueFromOperations>"
        f'<in-capmkt:ProfitLossForPeriod contextRef="OneD">{profit}'
        "</in-capmkt:ProfitLossForPeriod>"
        "</xbrli:xbrl>"
    )


def _seq(url):
    return re.search(r"_(\d+)_WEB", url).group(1)


class FakeFetcher:
    def __init__(self, documents):
        self.documents = documents
        self.asked = []

    def fetch_many(self, urls):
        self.asked += [_seq(url) for url in urls]
        return [self.documents.get(_seq(url)) for url in urls]


class FakeRepository:
    def __init__(self, market="NSE", stored=None):
        self.market = market
        self.stored = dict(stored or {})
        self.upserted = []
        self.redrawn = []

    def quarterly_filing_state(self):
        return self.stored

    def upsert_quarterly_filings(self, rows):
        self.upserted += rows
        return len(rows)

    # What `recompose_quarters` reads and writes.
    def quarterly_filings(self, symbols):
        self.redrawn += list(symbols)
        return {}

    def financial_statement_rows(self, symbols):
        return []

    def upsert_financial_statements(self, rows):
        return len(rows)


class FilingsRun(unittest.TestCase):
    def run_worker(self, records, documents, repo=None, **kwargs):
        repo = repo or FakeRepository()
        fetcher = FakeFetcher(documents)
        windows = []

        def loader(start, end):
            windows.append((end - start).days)
            return records

        counts = run(
            repo, index_records_loader=loader, fetcher=fetcher, today=TODAY, **kwargs
        )
        return counts, repo, fetcher, windows


class StoreTests(FilingsRun):
    RECORDS = [
        filing("AAA", "30-SEP-2026", 2, broadcast="13-Oct-2026 17:24:12"),
        filing("AAA", "30-SEP-2026", 1, consolidated=False),
    ]
    DOCUMENTS = {"1": document(2700, 420), "2": document(2732, 419)}

    def test_an_empty_table_is_built_from_the_whole_index(self):
        _, _, _, windows = self.run_worker(self.RECORDS, self.DOCUMENTS)
        self.assertEqual(windows, [FULL_LOOKBACK_DAYS])

    def test_each_filing_is_stored_parsed_and_stamped_in_exchange_time(self):
        counts, repo, _, _ = self.run_worker(self.RECORDS, self.DOCUMENTS)
        self.assertEqual(counts["stored"], 2)
        row = next(r for r in repo.upserted if r["is_consolidated"])
        self.assertEqual(
            (row["symbol"], row["period_end"], row["seq_id"], row["taxonomy"]),
            ("AAA", "2026-09-30", "2", "INDAS"),
        )
        self.assertEqual(row["lines"]["revenue"], 2732)
        self.assertEqual(row["lines"]["pat"], 419)
        self.assertIsNone(row["lines"]["pbt"])
        self.assertEqual(row["filed_at"], "2026-10-13T17:24:12+05:30")
        # The quarter was first announced by the standalone filing a minute
        # earlier; both bases carry that time.
        self.assertEqual(row["broadcast_at"], "2026-10-13T17:23:17+05:30")
        self.assertEqual(row["parser_version"], PARSER_VERSION)
        # What the Results page shows and links to.
        self.assertEqual(row["company"], "AAA Limited")
        self.assertEqual(row["viewer_url"], f"{ARCHIVE}/INTEGRATED_FILING_INDAS_2_iXBRL_WEB.html")

    def test_a_filing_without_a_name_or_rendering_beside_one_with_them_is_written(self):
        # One row with both fields and one without: pandas would give the
        # second NaN, which no JSON body can carry.
        bare = {**self.RECORDS[1], "cmName": None, "ixbrl": None}
        _, repo, _, _ = self.run_worker([self.RECORDS[0], bare], self.DOCUMENTS)
        row = next(r for r in repo.upserted if not r["is_consolidated"])
        self.assertIsNone(row["company"])
        self.assertIsNone(row["viewer_url"])
        json.dumps(repo.upserted, allow_nan=False)

    def test_an_absent_rendering_is_stored_as_none_not_as_the_archive_folder(self):
        records = [{**self.RECORDS[0], "ixbrl": "https://archive.example/corporate/null"}]
        _, repo, _, _ = self.run_worker(records, self.DOCUMENTS)
        self.assertIsNone(repo.upserted[0]["viewer_url"])

    def test_the_companies_stored_for_are_redrawn_on_the_stock_page(self):
        _, repo, _, _ = self.run_worker(self.RECORDS, self.DOCUMENTS)
        self.assertEqual(repo.redrawn, ["AAA"])

    def test_a_taxonomy_that_is_not_read_is_never_fetched(self):
        records = [filing("BNK", "30-SEP-2026", 9, taxonomy="BANKING")]
        _, repo, fetcher, _ = self.run_worker(records, {"9": document(1, 1)})
        self.assertEqual(fetcher.asked, [])
        self.assertEqual(repo.upserted, [])

    def test_a_document_that_cannot_be_fetched_is_asked_for_next_run(self):
        counts, repo, _, _ = self.run_worker(self.RECORDS, {"2": document(2732, 419)})
        self.assertEqual(counts["failed"], 1)
        self.assertEqual([r["seq_id"] for r in repo.upserted], ["2"])

    def test_dry_run_writes_nothing(self):
        counts, repo, _, _ = self.run_worker(self.RECORDS, self.DOCUMENTS, dry_run=True)
        self.assertEqual(counts["stored"], 2)
        self.assertEqual(repo.upserted, [])
        self.assertEqual(repo.redrawn, [])

    def test_a_market_with_no_filing_index_does_nothing(self):
        _, repo, fetcher, windows = self.run_worker(
            self.RECORDS, self.DOCUMENTS, repo=FakeRepository("US")
        )
        self.assertEqual((windows, fetcher.asked, repo.upserted), ([], [], []))


def stored_row(seq, *, version=PARSER_VERSION, broadcast="2026-07-14T19:04:04+05:30"):
    return {"seq_id": str(seq), "parser_version": version, "broadcast_at": broadcast}


class IncrementalTests(FilingsRun):
    def test_a_stored_filing_is_not_fetched_again(self):
        repo = FakeRepository(stored={("AAA", "2026-09-30", True): stored_row(2)})
        counts, _, fetcher, windows = self.run_worker(
            [filing("AAA", "30-SEP-2026", 2)], {"2": document(1, 1)}, repo=repo
        )
        self.assertEqual(windows, [DEFAULT_LOOKBACK_DAYS])
        self.assertEqual(fetcher.asked, [])
        self.assertEqual(counts["due"], 0)

    def test_a_revision_replaces_the_stored_filing_and_keeps_its_first_broadcast(self):
        repo = FakeRepository(stored={("AAA", "2026-06-30", True): stored_row(1)})
        records = [
            filing("AAA", "30-JUN-2026", 5, broadcast=None, revised="12-Oct-2026 16:37:14")
        ]
        _, repo, fetcher, _ = self.run_worker(records, {"5": document(9, 1)}, repo=repo)
        self.assertEqual(fetcher.asked, ["5"])
        row = repo.upserted[0]
        self.assertEqual(row["filed_at"], "2026-10-12T16:37:14+05:30")
        self.assertEqual(row["broadcast_at"], "2026-07-14T19:04:04+05:30")

    def test_a_filing_parsed_by_an_older_parser_is_read_again(self):
        repo = FakeRepository(
            stored={("AAA", "2026-09-30", True): stored_row(2, version=PARSER_VERSION - 1)}
        )
        _, _, fetcher, _ = self.run_worker(
            [filing("AAA", "30-SEP-2026", 2)], {"2": document(1, 1)}, repo=repo
        )
        self.assertEqual(fetcher.asked, ["2"])

    def test_full_reads_the_whole_index_even_when_the_table_is_built(self):
        repo = FakeRepository(stored={("AAA", "2026-09-30", True): stored_row(2)})
        _, _, _, windows = self.run_worker([], {}, repo=repo, full=True)
        self.assertEqual(windows, [FULL_LOOKBACK_DAYS])

    def test_tonights_results_come_before_older_filings_when_time_runs_out(self):
        records = [
            filing("OLD", "30-JUN-2026", 1, broadcast="14-Jul-2026 19:00:00"),
            filing("NEW", "30-SEP-2026", 2, broadcast="13-Oct-2026 17:00:00"),
        ]
        ticks = iter([0, 0, 100])
        with mock.patch("workers.quarterly_filings.BATCH_SIZE", 1):
            counts, _, fetcher, _ = self.run_worker(
                records,
                {"1": document(1, 1), "2": document(2, 2)},
                time_budget_seconds=50,
                clock=lambda: next(ticks),
            )
        self.assertEqual(fetcher.asked, ["2"])
        self.assertEqual(counts["deferred"], 1)


class WorkflowTests(unittest.TestCase):
    def text(self, name):
        return (Path(__file__).resolve().parents[1] / ".github" / "workflows" / name).read_text()

    def test_the_filings_workflow_stores_then_records_events(self):
        text = self.text("quarterly-filings.yml")
        self.assertIn("python -m workers.quarterly_filings", text)
        self.assertLess(
            text.index("python -m workers.quarterly_filings"),
            text.index("python -m workers.market_events"),
        )

    def test_the_filings_workflow_is_dispatched_from_outside_only(self):
        # cron-job.org dispatches it; a GitHub schedule beside that would run
        # every slot twice.
        text = self.text("quarterly-filings.yml")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)
        self.assertIn("inputs.full && '--full'", text)

    def test_the_screener_reads_the_store_and_keeps_no_filings_cache(self):
        text = self.text("daily-stock-screener.yml")
        self.assertNotIn("quarterly_results_cache", text)


if __name__ == "__main__":
    unittest.main()
