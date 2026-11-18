"""FII/DII flows on a recorded NSE payload (18 Nov 2026), stored in D1 (run on SQLite)."""

import json
import sqlite3
import unittest
from pathlib import Path

from storage.d1_backend import D1Session
from storage.dashboard_repository import DashboardRepository
from workers import market_flows

FLOWS = json.loads((Path(__file__).parent / "fixtures" / "market_flows" / "fiidii_18112026.json").read_text())
DDL = (Path(__file__).parent.parent / "storage" / "d1" / "market_flows.sql").read_text()


class Store:
    """An R2 stand-in."""

    def __init__(self, body=None, fail_get=False):
        self.body, self.fail_get, self.puts = body, fail_get, []

    def get(self, path):
        if self.fail_get:
            raise RuntimeError("R2 down")
        return self.body

    def put(self, path, body, content_type):
        self.puts.append(path)
        self.body = body


def d1_repo(store=None):
    db = sqlite3.connect(":memory:")
    db.executescript(DDL)

    def execute(table, sql, args):
        before = db.total_changes
        cursor = db.execute(sql, args)
        columns = [c[0] for c in cursor.description or ()]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        db.commit()
        return rows, db.total_changes - before

    repo = DashboardRepository("https://example.supabase.co", "key", market="NSE")
    repo.session = D1Session(execute)
    repo._r2 = store
    return repo, db


class ParseTests(unittest.TestCase):
    def test_flows_read_both_categories_in_crore(self):
        rows = {row["category"]: row for row in market_flows.parse_flows(FLOWS)}
        self.assertEqual(rows["FII"], {"session_date": "2026-11-18", "category": "FII",
                                       "buy_value": 17913.16, "sell_value": 12046.38, "net_value": 5866.78})
        self.assertEqual(rows["DII"]["net_value"], -3159.9)

    def test_a_starred_category_is_read(self):
        self.assertEqual(market_flows.parse_flows([{**FLOWS[1], "category": "FII/FPI **"}])[0]["category"], "FII")


class RunTests(unittest.TestCase):
    def test_a_session_is_stored_in_d1_and_on_r2_once(self):
        store = Store()
        repo, db = d1_repo(store)
        self.assertEqual(market_flows.run(repo, flows_loader=lambda: FLOWS), {"flows": 2})
        self.assertEqual(db.execute("select count(*) from fii_dii_flows where market = 'NSE'").fetchone(), (2,))
        self.assertEqual(store.puts, ["live/NSE/fii-dii-flows.json"])
        self.assertEqual(len(json.loads(store.body)["rows"]), 2)
        # the next run, same payload: nothing written, the object left alone
        self.assertEqual(market_flows.run(repo, flows_loader=lambda: FLOWS), {"flows": 0})
        self.assertEqual(len(store.puts), 1)

    def test_a_block_page_or_changed_layout_degrades(self):
        repo, db = d1_repo()
        for loader in (lambda: "<html>Access Denied</html>", lambda: [{**FLOWS[0], "date": "18/11/2026"}]):
            self.assertEqual(market_flows.run(repo, flows_loader=loader), {"flows": 0})
        self.assertEqual(db.execute("select count(*) from fii_dii_flows").fetchone(), (0,))

    def test_dry_run_writes_nothing(self):
        repo, db = d1_repo(Store())
        self.assertEqual(market_flows.run(repo, flows_loader=lambda: FLOWS, dry_run=True), {"flows": 2})
        self.assertEqual(db.execute("select count(*) from fii_dii_flows").fetchone(), (0,))

    def test_us_has_nothing(self):
        repo = DashboardRepository("https://example.supabase.co", "key", market="US")
        self.assertEqual(market_flows.run(repo, flows_loader=self.fail), {})


class LiveObjectTests(unittest.TestCase):
    def stored(self, store):
        repo, _ = d1_repo(store)
        repo.upsert_fii_dii_flows(market_flows.parse_flows(FLOWS))
        return repo

    def test_a_missed_put_heals_on_the_next_run(self):
        store = Store(body=json.dumps({"rows": [{"session_date": "2026-11-17"}]}).encode())
        self.assertTrue(self.stored(store).sync_fii_dii_object())
        self.assertEqual({row["session_date"] for row in json.loads(store.body)["rows"]}, {"2026-11-18"})

    def test_an_unreadable_object_is_rebuilt(self):
        store = Store(fail_get=True)
        self.assertTrue(self.stored(store).sync_fii_dii_object())
        self.assertEqual(store.puts, ["live/NSE/fii-dii-flows.json"])

    def test_the_object_carries_calendar_year_totals(self):
        store = Store()
        repo = self.stored(store)
        repo.upsert_fii_dii_flows([
            {"session_date": "2025-12-31", "category": "FII", "buy_value": 100.0, "sell_value": 150.5, "net_value": -50.5},
            {"session_date": "2026-01-02", "category": "FII", "buy_value": 10.0, "sell_value": 4.0, "net_value": 6.0},
        ])
        self.assertTrue(repo.sync_fii_dii_object())
        years = {(y["year"], y["category"]): y for y in json.loads(store.body)["years"]}
        self.assertEqual(years[(2026, "FII")]["net_value"], 5872.78)
        self.assertEqual(years[(2026, "FII")]["sessions"], 2)
        self.assertEqual(years[(2025, "FII")]["net_value"], -50.5)
        self.assertEqual(years[(2026, "DII")]["net_value"], -3159.9)

    def test_without_r2_nothing_is_asked(self):
        self.assertFalse(self.stored(None).sync_fii_dii_object())



class D1RegistryTests(unittest.TestCase):
    def test_the_table_is_laid_in_d1_and_never_copied(self):
        from tools import d1_tables

        self.assertEqual(d1_tables.TABLES["fii_dii_flows"], "evidence")
        self.assertIn("fii_dii_flows", d1_tables.HAND_LAID)
        self.assertNotIn("fii_dii_flows", d1_tables.ORDER)
        with self.assertRaises(SystemExit):
            d1_tables.main(["backfill", "fii_dii_flows"])


if __name__ == "__main__":
    unittest.main()
