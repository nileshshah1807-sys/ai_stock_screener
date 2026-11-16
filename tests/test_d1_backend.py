"""The D1 table backend, run against SQLite: what D1 itself is."""

import sqlite3
import unittest
from unittest import mock

import requests

from storage.d1_backend import (
    D1Session,
    DualSession,
    TableRouter,
    UnsupportedQuery,
    WriteCeilingReached,
    table_session,
    translate,
)
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

    def test_a_listed_table_takes_its_own_mode_and_the_rest_the_default(self):
        creds = {"D1_ACCOUNT_ID": "a", "D1_API_TOKEN": "t", "D1_DATABASE_ID": "d"}
        session = table_session({**creds, "TABLE_BACKEND_DUAL": "concall_feed",
                                 "TABLE_BACKEND_DUAL_D1": " Valuation_Basis ", "TABLE_BACKEND_D1": "live_quotes"})
        self.assertIsInstance(session, TableRouter)
        self.assertIs(type(session.default), requests.Session)
        self.assertFalse(session.by_table["concall_feed"].read_mirror)
        self.assertTrue(session.by_table["valuation_basis"].read_mirror)
        self.assertIsInstance(session.by_table["live_quotes"], D1Session)
        # one D1 session, so one write ceiling for the run
        self.assertIs(session.by_table["concall_feed"].mirror, session.by_table["live_quotes"])

    def test_a_table_in_two_lists_is_refused(self):
        with self.assertRaises(ValueError):
            table_session({"TABLE_BACKEND_DUAL": "a", "TABLE_BACKEND_D1": "a"})


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
        with self.assertRaises(WriteCeilingReached):
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


    def test_an_unchanged_merge_still_returns_its_row(self):
        # upsert_filing, the transcript writers and save_sentiment read rows[0].
        prefer = {"Prefer": "resolution=merge-duplicates,return=representation"}
        row = [{"market": "NSE", "symbol": "A", "profit": 1.0}]
        for _ in range(2):
            got = self.repo._request("POST", "valuation_basis?on_conflict=market,symbol", json=row, headers=prefer)
            self.assertEqual(got[0]["symbol"], "A")

    def test_boolean_filters_match_stored_zero_and_one(self):
        self.db.execute("alter table valuation_basis add column eligible integer")
        self.repo.upsert_valuation_basis([{"symbol": "A", "eligible": True}, {"symbol": "B", "eligible": False}])
        got = self.repo._request("GET", "valuation_basis", params={"eligible": "eq.true", "select": "symbol"})
        self.assertEqual([r["symbol"] for r in got], ["A"])

    def test_a_long_in_list_binds_one_parameter(self):
        sql, args = translate("GET", "https://x/rest/v1/t", {"symbol": "in.(" + ",".join(f"S{i}" for i in range(500)) + ")"}, None)
        self.assertEqual(len(args), 1)


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

    def test_the_mirror_is_switched_off_after_three_failures(self):
        primary = mock.Mock()
        primary.request.return_value = mock.Mock(ok=True)
        mirror = mock.Mock()
        mirror.request.side_effect = RuntimeError("D1 down")
        session = DualSession(primary, mirror)
        for _ in range(5):
            session.request("POST", "https://x/rest/v1/live_quotes", json=[{}])
        self.assertEqual(mirror.request.call_count, 3)
        self.assertEqual(primary.request.call_count, 5)

    def test_the_ceiling_switches_the_mirror_off_at_once(self):
        primary = mock.Mock()
        primary.request.return_value = mock.Mock(ok=True)
        mirror = mock.Mock()
        mirror.request.side_effect = WriteCeilingReached("ceiling")
        session = DualSession(primary, mirror)
        session.request("POST", "https://x/rest/v1/a", json=[{}])
        session.request("POST", "https://x/rest/v1/a", json=[{}])
        self.assertEqual(mirror.request.call_count, 1)

    def test_reads_stay_on_supabase(self):
        primary, mirror = mock.Mock(), mock.Mock()
        DualSession(primary, mirror).request("GET", "https://x/rest/v1/live_quotes")
        mirror.request.assert_not_called()


    def test_dual_d1_reads_d1_and_writes_both(self):
        primary, mirror = mock.Mock(), mock.Mock()
        primary.request.return_value = mock.Mock(ok=True)
        session = DualSession(primary, mirror, read_mirror=True)
        session.request("GET", "https://x/rest/v1/valuation_basis")
        primary.request.assert_not_called()
        session.request("POST", "https://x/rest/v1/valuation_basis", json=[{}])
        primary.request.assert_called_once()
        self.assertEqual(mirror.request.call_count, 2)

    def test_dual_d1_reads_supabase_once_a_copy_is_missed(self):
        for failure in (WriteCeilingReached("ceiling"), RuntimeError("D1 down")):
            primary, mirror = mock.Mock(), mock.Mock()
            primary.request.return_value = mock.Mock(ok=True)
            mirror.request.side_effect = failure
            session = DualSession(primary, mirror, read_mirror=True)
            session.request("POST", "https://x/rest/v1/valuation_basis", json=[{}])
            session.request("GET", "https://x/rest/v1/valuation_basis")
            self.assertEqual(mirror.request.call_count, 1)
            self.assertEqual(primary.request.call_count, 2)

    def test_the_router_sends_each_table_to_its_session(self):
        default, moved = mock.Mock(), mock.Mock()
        router = TableRouter(default, {"valuation_basis": moved})
        router.request("GET", "https://x/rest/v1/valuation_basis", params={"select": "*"})
        router.request("GET", "https://x/rest/v1/screener_runs")
        moved.request.assert_called_once_with("GET", "https://x/rest/v1/valuation_basis", params={"select": "*"})
        default.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
