"""FII/DII flows and participant OI, on recorded NSE files (18 and 17 Nov 2026)."""

import json
import unittest
from datetime import date
from pathlib import Path

from workers import market_flows

FIXTURES = Path(__file__).parent / "fixtures" / "market_flows"
FLOWS = json.loads((FIXTURES / "fiidii_18112026.json").read_text())
OI_TEXT = (FIXTURES / "fao_participant_oi_17112026.csv").read_text()


class FakeRepo:
    market = "NSE"

    def __init__(self, latest=None):
        self.latest = latest or {}
        self.written = {}

    def latest_flow_session(self, table):
        return self.latest.get(table)

    def upsert_market_flows(self, table, rows):
        self.written.setdefault(table, []).extend(rows)
        return len(rows)


class ParseTests(unittest.TestCase):
    def test_flows_read_both_categories_in_crore(self):
        rows = {row["category"]: row for row in market_flows.parse_flows(FLOWS)}
        self.assertEqual(set(rows), {"FII", "DII"})
        self.assertEqual(rows["FII"], {"session_date": "2026-11-18", "category": "FII",
                                       "buy_value": 17913.16, "sell_value": 12046.38, "net_value": 5866.78})
        self.assertEqual(rows["DII"]["net_value"], -3159.9)

    def test_a_starred_category_is_read(self):
        rows = market_flows.parse_flows([{**FLOWS[1], "category": "FII/FPI **"}])
        self.assertEqual(rows[0]["category"], "FII")

    def test_oi_reads_four_participants_without_the_total(self):
        rows = {row["category"]: row for row in market_flows.parse_oi(OI_TEXT, date(2026, 11, 17))}
        self.assertEqual(set(rows), {"Client", "DII", "FII", "Pro"})
        fii = rows["FII"]
        self.assertEqual((fii["future_index_long"], fii["future_index_short"]), (65568, 130691))
        self.assertEqual((fii["total_long"], fii["total_short"]), (6157158, 5025104))
        self.assertEqual(fii["session_date"], "2026-11-17")

    def test_an_unknown_layout_is_refused(self):
        with self.assertRaises(ValueError):
            market_flows.parse_oi("Client Type,Something Else\nFII,1\n", date(2026, 11, 17))


class RunTests(unittest.TestCase):
    def run_with(self, repo, oi_days, **kwargs):
        asked = []

        def oi_loader(day):
            asked.append(day)
            return OI_TEXT if day in oi_days else None

        counts = market_flows.run(repo, today=date(2026, 11, 18), flows_loader=lambda: FLOWS,
                                  oi_loader=oi_loader, sleep=lambda _: None, **kwargs)
        return counts, asked

    def test_new_sessions_are_stored(self):
        repo = FakeRepo({"fii_dii_flows": "2026-11-17", "participant_oi": "2026-11-16"})
        counts, asked = self.run_with(repo, {date(2026, 11, 17)})
        self.assertEqual(asked, [date(2026, 11, 17), date(2026, 11, 18)])  # today not out yet
        self.assertEqual(counts, {"flows": 2, "oi": 4, "oi_sessions": 1})
        self.assertEqual(len(repo.written["participant_oi"]), 4)

    def test_a_stored_session_is_not_written_again(self):
        repo = FakeRepo({"fii_dii_flows": "2026-11-18", "participant_oi": "2026-11-18"})
        counts, asked = self.run_with(repo, set())
        self.assertEqual((counts["flows"], counts["oi"], asked, repo.written), (0, 0, [], {}))

    def test_backfill_reads_a_year_of_weekdays(self):
        counts, asked = self.run_with(FakeRepo({"participant_oi": "2026-11-18"}), set(), backfill=True)
        self.assertGreater(len(asked), 250)
        self.assertTrue(all(day.weekday() < 5 for day in asked))
        self.assertEqual(asked[0], date(2025, 11, 14))

    def test_a_refused_fetch_keeps_the_rest(self):
        def oi_loader(day):
            if day == date(2026, 11, 18):
                raise RuntimeError("403")
            return OI_TEXT

        def refused():
            raise RuntimeError("403")

        repo = FakeRepo({"participant_oi": "2026-11-16"})
        counts = market_flows.run(repo, today=date(2026, 11, 18), flows_loader=refused,
                                  oi_loader=oi_loader, sleep=lambda _: None)
        self.assertEqual((counts["flows"], counts["oi_sessions"]), (0, 1))

    def test_dry_run_writes_nothing(self):
        repo = FakeRepo()
        counts, _ = self.run_with(repo, {date(2026, 11, 17)}, dry_run=True)
        self.assertEqual((counts["flows"], counts["oi"], repo.written), (2, 4, {}))

    def test_us_has_nothing(self):
        repo = FakeRepo()
        repo.market = "US"
        self.assertEqual(market_flows.run(repo, flows_loader=self.fail), {})


class LiveObjectTests(unittest.TestCase):
    def test_the_object_overlays_and_keeps_the_newest_sessions(self):
        from storage.dashboard_repository import DashboardRepository

        class Store:
            body = json.dumps({"rows": [{"session_date": "2026-11-16", "category": "FII", "net_value": 1},
                                        {"session_date": "2026-11-17", "category": "FII", "net_value": 2}]}).encode()

            def get(self, path):
                return self.body

            def put(self, path, body, content_type):
                self.path, self.written = path, json.loads(body)

        repo = DashboardRepository("https://example.supabase.co", "key", market="NSE")
        repo._r2 = store = Store()
        repo.put_live_series_object("fii-dii-flows", [{"session_date": "2026-11-17", "category": "FII", "net_value": 3},
                                                      {"session_date": "2026-11-18", "category": "FII", "net_value": 4}],
                                    keep_sessions=2)
        self.assertEqual(store.path, "live/NSE/fii-dii-flows.json")
        self.assertEqual([(r["session_date"], r["net_value"]) for r in store.written["rows"]],
                         [("2026-11-17", 3), ("2026-11-18", 4)])


if __name__ == "__main__":
    unittest.main()
