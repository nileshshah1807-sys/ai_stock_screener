"""The D1 table backend, run against SQLite: what D1 itself is."""

import sqlite3
import unittest
from unittest import mock

import requests

from storage.d1_backend import D1Session, DualSession, UnsupportedQuery, table_session, translate
from storage.dashboard_repository import DashboardRepository

SCHEMA = """
create table valuation_basis (market text, symbol text, profit real, detail text,
    updated_at text, primary key (market, symbol));
create table bulk_block_deals (market text, kind text, deal_date text, symbol text,
    client_name text, side text, quantity integer, price real, remarks text,
    primary key (market, kind, deal_date, symbol, client_name, side, quantity, price));
"""


def sqlite_session():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)

    def execute(table, sql, args):
        before = db.total_changes
        cursor = db.execute(sql, args)
        columns = [c[0] for c in cursor.description or ()]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        db.commit()
        return rows, db.total_changes - before

    return D1Session(execute), db


def repository(session):
    repo = DashboardRepository("https://example.supabase.co", "key", market="NSE")
    repo.session = session
    return repo


class BackendChoiceTests(unittest.TestCase):
    def test_unset_is_supabase_as_before(self):
        self.assertIs(type(table_session({})), requests.Session)
        self.assertIs(type(table_session({"TABLE_BACKEND": ""})), requests.Session)

    def test_unknown_backend_is_refused(self):
        with self.assertRaises(ValueError):
            table_session({"TABLE_BACKEND": "postgres"})

    def test_d1_needs_its_credentials(self):
        with self.assertRaises(ValueError):
            table_session({"TABLE_BACKEND": "d1"})


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.session, self.db = sqlite_session()
        self.repo = repository(self.session)

    def test_an_unchanged_upsert_writes_nothing(self):
        rows = [
            {"symbol": "A", "profit": 10.5, "detail": {"q": [1, 2]}, "updated_at": "2026-11-13"},
            {"symbol": "B", "profit": 7.0, "detail": None, "updated_at": "2026-11-13"},
        ]
        self.repo.upsert_valuation_basis(rows)
        self.assertEqual(self.session.rows_written, 2)
        # The next run sends the same rows, stamped again; only B changed.
        again = [{**rows[0], "updated_at": "2026-11-14"}, {**rows[1], "profit": 8.0, "updated_at": "2026-11-14"}]
        self.repo.upsert_valuation_basis(again)
        self.assertEqual(self.session.rows_written, 3)
        stored = dict(self.db.execute("select symbol, updated_at from valuation_basis").fetchall())
        self.assertEqual(stored, {"A": "2026-11-13", "B": "2026-11-14"})

    def test_a_stored_deal_is_never_rewritten(self):
        deal = {"kind": "bulk", "deal_date": "2026-11-13", "symbol": "A", "client_name": "X",
                "side": "BUY", "quantity": 100, "price": 12.5, "remarks": None}
        self.repo.upsert_bulk_block_deals([deal])
        self.repo.upsert_bulk_block_deals([deal, {**deal, "quantity": 200}])
        self.assertEqual(self.session.rows_written, 2)

    def test_the_ceiling_stops_writes_loudly(self):
        self.session.max_rows_written = 1
        self.repo.upsert_valuation_basis([{"symbol": "A", "profit": 1.0}, {"symbol": "B", "profit": 2.0}])
        with self.assertRaisesRegex(RuntimeError, "ceiling"):
            self.repo.upsert_valuation_basis([{"symbol": "C", "profit": 3.0}])

    def test_reads_filter_order_and_page_as_postgrest(self):
        self.repo.upsert_valuation_basis(
            [{"symbol": s, "profit": p, "detail": {"k": s}} for s, p in (("A", 3.0), ("B", None), ("C", 1.0))]
        )
        rows = self.repo._paged("valuation_basis", {"select": "symbol,profit,detail", "order": "profit.desc"}, page=2)
        self.assertEqual([r["symbol"] for r in rows], ["B", "A", "C"])  # nulls first descending
        self.assertEqual(rows[1]["detail"], {"k": "A"})
        picked = self.repo._request(
            "GET", "valuation_basis", params={"symbol": 'in.(A,"C")', "profit": "not.is.null", "select": "symbol"}
        )
        self.assertEqual(sorted(r["symbol"] for r in picked), ["A", "C"])


class TranslateTests(unittest.TestCase):
    def test_embedded_resources_are_refused_not_guessed(self):
        with self.assertRaises(UnsupportedQuery):
            translate("GET", "https://x/rest/v1/transcripts", {"select": "id,transcript_documents!inner(x)"}, None)

    def test_an_unfiltered_delete_is_refused(self):
        with self.assertRaises(UnsupportedQuery):
            translate("DELETE", "https://x/rest/v1/live_quotes", {}, None)

    def test_rpc_has_no_d1_form_yet(self):
        with self.assertRaises(UnsupportedQuery):
            translate("POST", "https://x/rest/v1/rpc/prune_screener_snapshots", {}, {})


class DualTests(unittest.TestCase):
    def test_writes_are_copied_and_a_failed_copy_never_fails_the_run(self):
        primary = mock.Mock()
        primary.request.return_value = mock.Mock(ok=True)
        mirror = mock.Mock()
        mirror.request.side_effect = RuntimeError("D1 down")
        session = DualSession(primary, mirror)
        self.assertTrue(session.request("POST", "https://x/rest/v1/live_quotes", json=[{}]).ok)
        mirror.request.assert_called_once()

    def test_reads_stay_on_supabase(self):
        primary, mirror = mock.Mock(), mock.Mock()
        DualSession(primary, mirror).request("GET", "https://x/rest/v1/live_quotes")
        mirror.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
