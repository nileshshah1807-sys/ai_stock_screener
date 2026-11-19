"""NSE IPOs on recorded NSE and tracker payloads (18 Nov 2026), stored in D1 (run on SQLite)."""

import json
import sqlite3
import unittest
from datetime import date
from pathlib import Path

from storage.d1_backend import D1Session
from storage.dashboard_repository import DashboardRepository
from workers import ipos

FIXTURES = Path(__file__).parent / "fixtures" / "ipos"
DDL = (Path(__file__).parent.parent / "storage" / "d1" / "ipo_issues.sql").read_text()
TODAY = date(2026, 11, 18)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


GMP_PAGE = (FIXTURES / "investorgain_gmp_18112026.html").read_text()
PAYLOADS = {
    "ipo-current-issue": fixture("current_18112026.json"),
    "all-upcoming-issues?category=ipo": fixture("upcoming_18112026.json"),
    "public-past-issues": fixture("past_18112026.json"),
    "ipo-active-category?symbol=CRYSTALCP": fixture("category_CRYSTALCP_18112026.json"),
    "ipo-active-category?symbol=VPFL": fixture("category_VPFL_18112026.json"),
    "ipo-detail?symbol=CRYSTALCP&series=EQ": fixture("detail_CRYSTALCP_18112026.json"),
    "ipo-detail?symbol=WATRANA&series=SME": fixture("detail_WATRANA_18112026.json"),
}


def fetch_from(payloads):
    def fetch(path):
        if path not in payloads:
            raise RuntimeError(f"403 {path}")
        return payloads[path]
    return fetch


class Store:
    """An R2 stand-in."""

    def __init__(self):
        self.objects = {}

    def put(self, path, body, content_type):
        self.objects[path] = json.loads(body)


def d1_repo(market="NSE"):
    db = sqlite3.connect(":memory:")
    db.executescript(DDL)

    def execute(table, sql, args):
        before = db.total_changes
        cursor = db.execute(sql, args)
        columns = [c[0] for c in cursor.description or ()]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        db.commit()
        return rows, db.total_changes - before

    repo = DashboardRepository("https://example.supabase.co", "key", market=market)
    repo.session = D1Session(execute)
    repo._r2 = Store()
    return repo, db


def run(repo, payloads=PAYLOADS, today=TODAY, page=GMP_PAGE, bars=None):
    return ipos.run(repo, today=today, fetch=fetch_from(payloads),
                    bars=bars or (lambda day: {"VPFL": (89.3, 84.8)}), gmp_page=lambda: page)


class ParseTests(unittest.TestCase):
    def test_issues_come_from_all_three_feeds_within_the_window(self):
        rows = ipos.parse_issues(PAYLOADS["ipo-current-issue"], PAYLOADS["all-upcoming-issues?category=ipo"],
                                 PAYLOADS["public-past-issues"], TODAY)
        self.assertEqual(rows["CRYSTALCP"], {
            "symbol": "CRYSTALCP", "company": "Crystal Crop Protection Limited", "board": "Mainboard",
            "open_date": "2026-11-18", "close_date": "2026-11-20", "price_low": 259.0, "price_high": 272.0,
            "book_shares": 12170076.0})
        self.assertEqual(rows["WATRANA"]["board"], "SME")
        self.assertEqual((rows["VPFL"]["listing_date"], rows["VPFL"]["issue_price"]), ("2026-11-09", 94.0))
        self.assertNotIn("THEJO", rows)  # listed in 2012
        self.assertFalse({row["board"] for row in rows.values()} - {"Mainboard", "SME"})  # no debt, REIT
        self.assertEqual(rows["BCSSL"]["company"], "Bombay Coated and Special Steels Limited")  # mainboard: "company"

    def test_a_later_issue_by_a_listed_company_is_not_an_ipo(self):
        # NSE's past feed, 19 Nov 2026: Ola Electric's partly-paid shares carry its 2024 IPO dates.
        later = {"company": "Ola Electric Mobility Limited", "ipoStartDate": "02-AUG-2024", "ipoEndDate": "06-AUG-2024",
                 "issuePrice": "11", "listingDate": "06-NOV-2026", "priceRange": "Rs.72 to Rs.76",
                 "securityType": "Equity", "symbol": "OLAPP"}
        stored = {**ipos.parse_issues([], [], [later], TODAY)["OLAPP"], "market": "NSE"}
        self.assertFalse(ipos._keep(stored, TODAY, 365))  # nor kept when an earlier run stored it

    def test_the_book_is_read_by_top_level_category(self):
        book = ipos.parse_book(PAYLOADS["ipo-active-category?symbol=CRYSTALCP"])
        self.assertEqual(book["subscription_total"], 1.4)
        self.assertEqual(book["subscription_as_of"], "2026-11-18T17:00:00+05:30")
        times = {c["category"]: c["times"] for c in book["subscription"]}
        self.assertEqual(times, {"QIB": 2.07, "NII": 0.75, "bNII": 0.62, "sNII": 1.03, "Retail": 1.28, "Employee": 2.91})

    def test_a_book_with_nothing_offered_is_unusable_not_zero(self):
        self.assertEqual(ipos.parse_book(PAYLOADS["ipo-active-category?symbol=VPFL"]), {})

    def test_detail_gives_lot_registrar_and_offer_document(self):
        detail = ipos.parse_detail(PAYLOADS["ipo-detail?symbol=CRYSTALCP&series=EQ"])
        self.assertEqual((detail["lot_size"], detail["face_value"]), (55, 10.0))
        self.assertEqual(detail["registrar"], "MUFG Intime India Private Limited")
        self.assertEqual(detail["rhp_url"], "https://nsearchives.nseindia.com/content/ipo/RHP_CRYSTALCP.zip")
        self.assertEqual(ipos.parse_detail(PAYLOADS["ipo-detail?symbol=WATRANA&series=SME"])["lot_size"], 600)

    def test_gmp_rows_are_read_from_the_flight_payload(self):
        rows = {row["name"]: row for row in ipos.parse_gmp(GMP_PAGE)}
        self.assertEqual(rows["Mahanadi Coalfields"], {
            "name": "Mahanadi Coalfields", "open_date": "2026-11-19", "gmp": 3.1, "gmp_pct": 2.28,
            "gmp_peak": 9.25, "gmp_as_of": "2026-11-18T19:37:00+05:30"})
        self.assertIsNone(rows["Antala Industries"]["gmp"])  # "--": nothing quoted
        self.assertEqual(ipos.parse_gmp("<html>changed layout</html>"), [])

    def test_gmp_matches_by_name_and_open_date(self):
        tracker = {ipos._name_key(row["name"]): row for row in ipos.parse_gmp(GMP_PAGE)}
        issue = {"company": "Mahanadi Coalfields Limited", "open_date": "2026-11-19"}
        self.assertEqual(ipos.gmp_fields(issue, tracker)["gmp"], 3.1)
        self.assertEqual(ipos.gmp_fields({**issue, "open_date": "2026-12-01"}, tracker), {})


class RunTests(unittest.TestCase):
    def test_a_run_stores_the_issues_and_writes_the_object(self):
        repo, db = d1_repo()
        self.assertEqual(run(repo)["issues"], db.execute("select count(*) from ipo_issues").fetchone()[0])
        rows = {row["symbol"]: row for row in repo._r2.objects["live/NSE/ipos.json"]["rows"]}
        crystal = rows["CRYSTALCP"]
        self.assertEqual((crystal["subscription_total"], crystal["lot_size"], crystal["gmp"]), (1.4, 55, 19.0))
        self.assertEqual(crystal["subscription"][0], {"category": "QIB", "offered": 3406814.0, "bid": 7042035.0, "times": 2.07})
        self.assertEqual((rows["MAHACOAL"]["gmp"], rows["WATRANA"]["gmp_peak"]), (3.1, 37.0))
        self.assertEqual((rows["VPFL"]["listing_open"], rows["VPFL"]["listing_close"]), (89.3, 84.8))
        self.assertIsNone(rows["VPFL"]["gmp"])  # a listed issue takes no grey-market figure
        self.assertFalse(set(ipos.INTERNAL) & set(crystal))

    def test_a_second_run_changes_nothing_and_keeps_what_it_read(self):
        repo, db = d1_repo()
        run(repo)
        # The exchange refuses everything, its bhavcopy too; the tracker shows nothing.
        def refused(day):
            raise RuntimeError("403")
        self.assertEqual(run(repo, payloads={}, page=None, bars=refused)["changed"], 0)
        crystal = repo._r2.objects["live/NSE/ipos.json"]["rows"]
        self.assertEqual({row["symbol"]: row["subscription_total"] for row in crystal}["CRYSTALCP"], 1.4)

    def test_a_settled_book_and_a_read_listing_day_are_not_asked_again(self):
        repo, _ = d1_repo()
        run(repo, today=date(2026, 11, 22))
        asked = []
        ipos.run(repo, today=date(2026, 11, 23), fetch=lambda path: asked.append(path) or PAYLOADS.get(path, []),
                 bars=lambda day: asked.append(day) or {}, gmp_page=lambda: None)
        self.assertNotIn("ipo-active-category?symbol=CRYSTALCP", asked)
        self.assertNotIn(date(2026, 11, 9), asked)

    def test_other_markets_store_nothing(self):
        repo, _ = d1_repo("US")
        self.assertEqual(ipos.run(repo, fetch=fetch_from({}), gmp_page=lambda: None), {})
        self.assertEqual(repo._r2.objects, {})


if __name__ == "__main__":
    unittest.main()
