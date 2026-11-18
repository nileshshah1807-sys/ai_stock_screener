"""IPOs on recorded NSE pages (18 Nov 2026), stored in D1 (run on SQLite)."""

import json
import sqlite3
import unittest
from datetime import date
from pathlib import Path

from storage.d1_backend import D1Session
from storage.dashboard_repository import DashboardRepository
from workers import ipos

FIXTURES = Path(__file__).parent / "fixtures" / "ipos"
DDL = (Path(__file__).parent.parent / "storage" / "d1" / "ipos.sql").read_text()


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Source:
    def __init__(self):
        self.details, self.bar_days = [], []

    def lists(self):
        return {"current": load("current"), "upcoming": load("upcoming"), "past": load("past")}

    def detail(self, symbol, board):
        self.details.append(symbol)
        return load("detail_active" if symbol == "CRYSTALCP" else "detail_past")

    def listing_bars(self, day):
        self.bar_days.append(day)
        return {"VPFL": {"Open": 98.0, "Close": 102.9}}


class Store:
    def __init__(self):
        self.body = None

    def put(self, path, body, content_type):
        self.path, self.body = path, json.loads(body)


def d1_repo():
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
    repo._r2 = Store()
    return repo, db


class ParseTests(unittest.TestCase):
    def test_list_pages(self):
        issues = ipos.gather(Source().lists(), today=date(2026, 11, 18), window_days=45)
        crystal, coal, vedant = issues[("CRYSTALCP", "mainboard")], issues[("MAHACOAL", "mainboard")], issues[("VPFL", "sme")]
        self.assertEqual((crystal["status"], crystal["price_low"], crystal["price_high"]), ("open", 259.0, 272.0))
        self.assertEqual((crystal["issue_start"], crystal["issue_end"], crystal["issue_size_shares"]),
                         ("2026-11-18", "2026-11-20", 12170076))
        self.assertEqual(coal["status"], "forthcoming")
        self.assertEqual(issues[("WATRANA", "sme")]["board"], "sme")
        self.assertEqual((vedant["status"], vedant["issue_price"], vedant["listing_date"]), ("listed", 94.0, "2026-11-09"))
        self.assertFalse(any(key[0] == "DEBTISSUE" for key in issues))
        self.assertTrue(all(key[1] in ("mainboard", "sme") for key in issues))

    def test_detail_gives_lot_and_categories(self):
        fields, as_of, rows = ipos.parse_detail(load("detail_active"))
        self.assertEqual((fields["lot_size"], as_of), (55, "2026-11-18"))
        by = {row["category"]: row for row in rows}
        self.assertEqual(set(by), {"qib", "nii", "nii_big", "nii_small", "retail", "employee", "total"})
        self.assertEqual((by["qib"]["shares_offered"], by["qib"]["shares_bid"]), (3406814, 7042035))
        self.assertAlmostEqual(by["total"]["times"], 1.4036, places=3)
        self.assertEqual(ipos.parse_detail(load("detail_past"))[0]["lot_size"], 1200)


class RunTests(unittest.TestCase):
    def test_stored_in_d1_and_on_r2_and_not_refetched(self):
        repo, db = d1_repo()
        source = Source()
        counts = ipos.run(repo, source=source, today=date(2026, 11, 18))
        self.assertGreater(counts["issues"], 3)
        self.assertNotIn("MAHACOAL", source.details)  # forthcoming: nothing to read yet
        row = db.execute("select status, lot_size, listing_open, listing_close from ipos where symbol='VPFL'").fetchone()
        self.assertEqual(row, ("listed", 1200, 98.0, 102.9))
        self.assertEqual(db.execute("select count(*) from ipo_subscriptions where symbol='CRYSTALCP' "
                                    "and as_of='2026-11-18'").fetchone(), (7,))
        self.assertEqual(repo._r2.path, "live/NSE/ipos.json")
        crystal = next(r for r in repo._r2.body["rows"] if r["symbol"] == "CRYSTALCP")
        self.assertEqual(len(crystal["subscriptions"]), 7)

        # the next run: a listed, complete issue is not read again, nor its listing day
        again = Source()
        ipos.run(repo, source=again, today=date(2026, 11, 18))
        self.assertNotIn("VPFL", again.details)
        self.assertEqual(again.bar_days, [])
        self.assertIn("CRYSTALCP", again.details)  # still open: today's figures

    def test_a_refused_list_page_writes_nothing(self):
        repo, db = d1_repo()

        class Refused(Source):
            def lists(self):
                raise RuntimeError("403")

        self.assertEqual(ipos.run(repo, source=Refused(), today=date(2026, 11, 18)), {"issues": 0, "subscriptions": 0})
        self.assertEqual(db.execute("select count(*) from ipos").fetchone(), (0,))

    def test_dry_run_writes_nothing(self):
        repo, db = d1_repo()
        ipos.run(repo, source=Source(), today=date(2026, 11, 18), dry_run=True)
        self.assertEqual(db.execute("select count(*) from ipos").fetchone(), (0,))


if __name__ == "__main__":
    unittest.main()
