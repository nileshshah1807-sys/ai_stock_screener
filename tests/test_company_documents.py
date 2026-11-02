"""Company documents: five kinds of link, a year of them, never a failed step."""

import unittest
from datetime import UTC, date, datetime

from workers.company_documents import (
    announcement_rows,
    annual_report_rows,
    kind_of,
    prune,
    record_announcements,
    sweep_annual_reports,
    sweep_slice,
)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def note(desc, text="", symbol="TCS", at="14-Oct-2026 16:00:08", url="https://nsearchives.nseindia.com/c/x.pdf"):
    return {"symbol": symbol, "desc": desc, "attchmntText": text, "an_dt": at, "attchmntFile": url}


class KindTests(unittest.TestCase):
    def test_each_kind(self):
        self.assertEqual(kind_of(note("Investor Presentation")), "presentation")
        self.assertEqual(kind_of(note("Updates", "Earning presentation for quarter ended September 30, 2026")), "presentation")
        self.assertEqual(kind_of(note("Credit Rating- Revision")), "rating")
        self.assertEqual(kind_of(note("Analysts/Institutional Investor Meet/Con. Call Updates", "X has informed the Exchange about Transcript")), "transcript")
        self.assertEqual(kind_of(note("Analysts/Institutional Investor Meet/Con. Call Updates", "X has informed the Exchange about Link of Recording")), "recording")

    def test_other_announcements_are_not_documents(self):
        self.assertIsNone(kind_of(note("Outcome of Board Meeting")))
        self.assertIsNone(kind_of(note("Press Release", "a press release dated October 29 with a presentation")))


class RowTests(unittest.TestCase):
    def test_rows_are_links_once_each_in_india_time(self):
        rows = announcement_rows([note("Investor Presentation"), note("Investor Presentation"), note("Dividend")], since=SINCE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["announced_at"], "2026-10-14T16:00:08+05:30")
        self.assertEqual((rows[0]["kind"], rows[0]["title"], rows[0]["period"]), ("presentation", "Investor presentation", None))
        self.assertEqual(set(rows[0]), {"symbol", "kind", "announced_at", "title", "url", "period"})

    def test_old_unlinked_and_out_of_universe_are_skipped(self):
        records = [note("Investor Presentation", at="01-Jan-2026 10:00:00"), note("Investor Presentation", url=""), note("Investor Presentation", symbol="ZZZ")]
        self.assertEqual(announcement_rows(records, since=SINCE, universe={"TCS"}), [])

    def test_annual_reports_keep_the_latest_three(self):
        payload = {"data": [
            {"fromYr": str(y), "toYr": str(y + 1), "broadcast_dttm": "15-MAY-2026 23:48:30" if y == 2025 else "-", "fileName": f"https://nsearchives.nseindia.com/ar{y}.pdf"}
            for y in (2022, 2023, 2024, 2025)
        ] + [{"fromYr": "2021", "toYr": "2022", "fileName": ""}]}
        rows = annual_report_rows("TCS", payload)
        self.assertEqual([r["period"] for r in rows], ["2025-26", "2024-25", "2023-24"])
        self.assertEqual(rows[0]["announced_at"], "2026-05-15T23:48:30+05:30")
        self.assertTrue(rows[1]["announced_at"].startswith("2025-03-31"))

    def test_the_sweep_visits_each_symbol_once_a_week(self):
        symbols = [f"S{i:03d}" for i in range(70)]
        week = [sweep_slice(symbols, date(2026, 11, 2 + d)) for d in range(7)]  # 2 Nov 2026 is a Monday
        self.assertEqual(sorted(sum(week, [])), symbols)


class FakeRepo:
    market = "NSE"

    def __init__(self, stored=None, fail=False):
        self.written, self.dropped, self.pruned, self.stored, self.fail = [], [], [], stored or {}, fail

    def snapshot_companies(self):
        if self.fail:
            raise RuntimeError("unreadable")
        return {"TCS": "Tata"}

    def upsert_company_documents(self, rows):
        self.written += rows
        return len(rows)

    def company_documents(self, kind):
        return self.stored

    def delete_company_documents(self, rows):
        self.dropped += rows
        return len(rows)

    def prune_company_documents(self, before):
        self.pruned.append(before)


class FakeNse:
    def annual_reports(self, symbol):
        return {"data": [{"fromYr": "2025", "toYr": "2026", "broadcast_dttm": "15-MAY-2026 23:48:30", "fileName": "https://nsearchives.nseindia.com/new.pdf"}]}


class RunTests(unittest.TestCase):
    def test_records_fresh_documents_of_the_universe(self):
        repo = FakeRepo()
        n = record_announcements(repo, [note("Investor Presentation", at="01-Nov-2026 10:00:00"), note("Investor Presentation", symbol="ZZZ", at="01-Nov-2026 10:00:00")], now=NOW)
        self.assertEqual((n, [r["symbol"] for r in repo.written]), (1, ["TCS"]))

    def test_an_unreadable_universe_warns_and_writes_nothing(self):
        repo = FakeRepo(fail=True)
        with self.assertLogs("workers.company_documents", "WARNING"):
            self.assertEqual(record_announcements(repo, [note("Investor Presentation", at="01-Nov-2026 10:00:00")], now=NOW), 0)

    def test_an_empty_universe_writes_nothing(self):
        repo = FakeRepo()
        repo.snapshot_companies = lambda: {}
        with self.assertLogs("workers.company_documents", "WARNING"):
            self.assertEqual(record_announcements(repo, [note("Investor Presentation", at="01-Nov-2026 10:00:00")], now=NOW), 0)
        self.assertEqual(repo.written, [])

    def test_the_sweep_writes_every_fifty_symbols(self):
        repo = FakeRepo()
        calls = []
        repo.upsert_company_documents = lambda rows: calls.append(len(rows)) or len(rows)
        sweep_annual_reports(repo, FakeNse(), [f"S{i}" for i in range(120)], pause=0)
        self.assertEqual(calls, [50, 50, 20])

    def test_prune_is_its_own_call(self):
        repo = FakeRepo()
        prune(repo, now=NOW)
        self.assertEqual(len(repo.pruned), 1)

    def test_dry_run_writes_nothing(self):
        repo = FakeRepo()
        record_announcements(repo, [note("Investor Presentation", at="01-Nov-2026 10:00:00")], now=NOW, dry_run=True)
        self.assertEqual(repo.written, [])

    def test_sweep_drops_a_fourth_report_and_prunes_old_links(self):
        old = [{"symbol": "TCS", "url": u} for u in ("https://x/old.pdf", "https://nsearchives.nseindia.com/new.pdf")]
        repo = FakeRepo(stored={"TCS": old})
        counts = sweep_annual_reports(repo, FakeNse(), ["TCS"], pause=0)
        self.assertEqual((counts["written"], counts["dropped"]), (1, 1))
        self.assertEqual(repo.dropped[0]["url"], "https://x/old.pdf")
        self.assertEqual(repo.pruned, [])  # pruning is the prune step's, not the sweep's


if __name__ == "__main__":
    unittest.main()
