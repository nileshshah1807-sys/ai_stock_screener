"""tools.d1_tables against SQLite, which is what D1 is."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from storage.d1_backend import D1Session
from tools import d1_tables

PK = "Note:\nThis is a Primary Key.<pk/>"
DEFINITIONS = {
    "valuation_basis": {
        "required": ["market", "symbol", "updated_at"],
        "properties": {
            "market": {"format": "text", "description": PK, "default": "NSE"},
            "symbol": {"format": "text", "description": PK},
            "profit": {"format": "numeric"},
            "eligible": {"format": "boolean", "default": False},
            "detail": {"format": "jsonb"},
            "id": {"format": "uuid", "default": "gen_random_uuid()"},
            "updated_at": {"format": "timestamp with time zone", "default": "now()"},
        },
    },
    "screener_history": {
        "properties": {
            "market": {"format": "text", "description": PK},
            "observed_on": {"format": "date", "description": PK},
            "symbol": {"format": "text", "description": PK},
            "rating": {"format": "text"},
            "payload_only": {"format": "jsonb"},
        },
    },
}


def sqlite_execute():
    db = sqlite3.connect(":memory:")

    def execute(table, sql, args):
        before = db.total_changes
        cursor = db.execute(sql, args)
        columns = [c[0] for c in cursor.description or ()]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        db.commit()
        return rows, db.total_changes - before

    return execute, db


class SchemaTests(unittest.TestCase):
    def test_the_key_is_in_postgres_order_and_a_drifted_key_is_refused(self):
        ddl = d1_tables.table_ddl("screener_history", DEFINITIONS["screener_history"])
        self.assertIn('PRIMARY KEY ("market", "observed_on", "symbol")', ddl)
        self.assertIn("screener_history_symbol_idx", ddl)
        drifted = {"properties": {**DEFINITIONS["valuation_basis"]["properties"], "id": {"description": PK}}}
        with self.assertRaises(ValueError):
            d1_tables.table_ddl("valuation_basis", drifted)

    def test_a_snapshot_row_packs_its_other_columns_into_extra_and_drops_payload(self):
        real = d1_tables.real_columns("screener_snapshot")
        self.assertLessEqual(len(real), d1_tables.D1_MAX_COLUMNS)
        row = {"market": "NSE", "run_date": "2026-11-13", "symbol": "A", "adx_14": 21.5, "payload": {"big": 1}}
        packed = d1_tables.to_d1("screener_snapshot", row)
        self.assertEqual(set(packed) - set(real), set())
        self.assertEqual(json.loads(packed["extra"]), {"adx_14": 21.5})


    def test_ddl_keys_types_defaults_and_history_columns(self):
        ddl = d1_tables.table_ddl("valuation_basis", DEFINITIONS["valuation_basis"])
        self.assertIn('PRIMARY KEY ("market", "symbol")', ddl)
        self.assertIn('"eligible" INTEGER DEFAULT 0', ddl)
        self.assertIn('"id" TEXT\n', ddl.replace(",\n", "\n"))  # a function default is not copied
        self.assertTrue(ddl.rstrip().endswith("WITHOUT ROWID;"))
        history = d1_tables.table_ddl("screener_history", DEFINITIONS["screener_history"])
        self.assertNotIn("payload_only", history)

    def test_a_table_wider_than_d1_allows_is_refused(self):
        wide = {"properties": {"k": {"format": "text", "description": PK}, **{f"c{i}": {"format": "text"} for i in range(100)}}}
        with self.assertRaises(ValueError):
            d1_tables.table_ddl("wide", wide)

    def test_generated_ddl_runs_on_sqlite(self):
        execute, db = sqlite_execute()
        for table, definition in DEFINITIONS.items():
            for statement in d1_tables.statements(d1_tables.table_ddl(table, definition)):
                execute(table, statement, [])
        db.execute("insert into valuation_basis (symbol) values ('A')")
        market, stamp = db.execute("select market, updated_at from valuation_basis").fetchone()
        self.assertEqual(market, "NSE")
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT")


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.execute, self.db = sqlite_execute()
        self.execute("valuation_basis", d1_tables.table_ddl("valuation_basis", DEFINITIONS["valuation_basis"]), [])
        self.source = [{"market": "NSE", "symbol": f"S{i:04d}", "profit": float(i), "detail": {"q": i},
                        "updated_at": "2026-11-14"} for i in range(1200)]
        self.state = Path(tempfile.mkdtemp()) / "state.json"
        self.store = d1_tables.FileState(self.state)

    def fetch(self, table, keys, after, columns=None):
        rest = [row for row in self.source if after is None or [row[key] for key in keys] > list(after)]
        return rest[:d1_tables.PAGE]

    def run_once(self, ceiling, counts=None, seek=None):
        session = D1Session(self.execute, max_rows_written=ceiling)
        return d1_tables.backfill(["valuation_basis"], session, self.store, DEFINITIONS, fetch=self.fetch,
                                  counts=counts, seek=seek)

    def test_progress_saved_by_offset_alone_resumes_at_the_last_row_copied(self):
        full, self.source = self.source, self.source[:500]
        self.run_once(10_000)
        self.state.write_text(json.dumps({"tables": {"valuation_basis": {"offset": 500, "done": False}}, "days": {}}))
        self.source = full

        def seek(table, keys, offset):
            return d1_tables.last_copied(self.execute, table, keys, offset)

        self.assertEqual(self.run_once(10_000, seek=seek), 0)
        progress = json.loads(self.state.read_text())["tables"]["valuation_basis"]
        self.assertEqual((progress["offset"], progress["sent"]), (1200, 700))  # not re-read from the start
        self.assertEqual(self.db.execute("select count(*) from valuation_basis").fetchone()[0], 1200)

    def test_a_short_copy_is_read_again_from_the_start(self):
        del self.source[3]  # deleted in Supabase behind the offset: D1 still has it
        calls = []

        def counts(table):
            calls.append(table)
            return (1199, 1199) if len(calls) > 1 else (1199, 1198)

        self.assertEqual(self.run_once(10_000, counts), 0)
        progress = json.loads(self.state.read_text())["tables"]["valuation_basis"]
        self.assertEqual((progress["pass"], progress["counts"]), (2, [1199, 1199]))

    def test_a_reread_that_rewrites_unchanged_rows_stops_the_table_not_the_day(self):
        passes = []

        def counts(table):
            passes.append(table)
            for row in self.source:  # as if a column re-serialized differently on the second read
                row["profit"] += 0.5
            return (1200, 1190)

        self.assertEqual(self.run_once(10_000, counts), 1)
        progress = json.loads(self.state.read_text())["tables"]["valuation_basis"]
        self.assertTrue(progress["stalled"])
        self.assertEqual((progress["pass"], progress["sent"], progress["written"]), (2, 500, 500))
        self.assertEqual(len(passes), 1)

    def test_a_reread_of_missing_rows_on_an_indexed_table_is_not_stalled(self):
        def counts(table):  # 400 rows missing from D1, each costing 2 written (row + index)
            if not counts.calls:
                self.db.execute("delete from valuation_basis where symbol < 'S0400'")
            counts.calls += 1
            return (1200, 800) if counts.calls == 1 else (1200, 1200)
        counts.calls = 0
        execute = self.execute

        def doubled(table, sql, args):
            rows, written = execute(table, sql, args)
            return rows, written * 2
        self.execute = doubled
        with mock.patch.object(d1_tables, "write_cost", return_value=2):
            self.assertEqual(self.run_once(100_000, counts), 0)
        progress = json.loads(self.state.read_text())["tables"]["valuation_basis"]
        self.assertFalse(progress.get("stalled"))
        self.assertEqual((progress["pass"], progress["written"]), (2, 800))

    def test_write_cost_counts_the_row_and_each_index(self):
        self.assertEqual(d1_tables.write_cost("screener_history"), 2)
        self.assertEqual(d1_tables.write_cost("screener_snapshot"), 2)
        self.assertEqual(d1_tables.write_cost("valuation_basis"), 1)

    def test_it_stops_loudly_at_the_ceiling_and_the_day_budget_holds_across_runs(self):
        self.assertEqual(self.run_once(600), 2)
        state = json.loads(self.state.read_text())
        written = next(iter(state["days"].values()))
        self.assertGreaterEqual(written, 600)
        self.assertEqual(self.run_once(600), 2)  # same UTC day: nothing left of the budget
        self.assertEqual(next(iter(json.loads(self.state.read_text())["days"].values())), written)

    def test_progress_kept_in_d1_resumes_on_a_fresh_runner(self):
        self.store = d1_tables.D1State(self.execute)
        self.assertEqual(self.run_once(600), 2)
        self.store = d1_tables.D1State(self.execute)  # the next day's runner: nothing local
        offset = self.store.load()["tables"]["valuation_basis"]["offset"]
        self.assertGreater(offset, 0)

    def test_it_resumes_and_finishes_and_a_rerun_writes_nothing(self):
        self.assertEqual(self.run_once(10_000), 0)
        self.assertEqual(self.db.execute("select count(*) from valuation_basis").fetchone()[0], 1200)
        detail = self.db.execute("select detail from valuation_basis where symbol='S0007'").fetchone()[0]
        self.assertEqual(json.loads(detail), {"q": 7})
        self.state.unlink()
        self.assertEqual(self.run_once(10_000), 0)
        self.assertEqual(next(iter(json.loads(self.state.read_text())["days"].values())), 0)


class PageTests(unittest.TestCase):
    """_page against a fake PostgREST that answers eq./gt. filters, order and limit."""

    KEYS = ["market", "observed_on", "symbol"]

    def setUp(self):
        self.table = sorted(
            ({"market": m, "observed_on": f"2026-11-{d:02d}", "symbol": s, "flag": d % 2 == 0}
             for m in ("NSE", "US") for d in (17, 18) for s in ("A", "M&M", "Z")),
            key=lambda row: [row[k] for k in self.KEYS],
        )
        self.asked = []

    def get(self, url, params, headers, timeout):
        self.asked.append(params)
        rows = self.table
        for column, condition in params.items():
            if column in self.KEYS:
                op, value = condition.split(".", 1)
                rows = [r for r in rows if (r[column] == value if op == "eq" else r[column] > value)]
        reply = mock.Mock()
        reply.json.return_value = rows[:int(params["limit"])]
        return reply

    def pages(self, size):
        with mock.patch.object(d1_tables, "PAGE", size), \
                mock.patch.object(d1_tables, "_supabase", return_value=("https://sb/rest/v1", {})), \
                mock.patch.object(d1_tables.requests, "get", side_effect=self.get):
            after, out = None, []
            while True:
                page = d1_tables._page("screener_history", self.KEYS, after)
                out += page
                if len(page) < size:
                    return out
                after = [page[-1][k] for k in self.KEYS]

    def test_pages_by_key_cover_every_row_once_in_order_across_group_ends(self):
        self.assertEqual(self.pages(4), self.table)  # 4 does not divide a 3-row date or 6-row market
        self.assertFalse(any("offset" in params for params in self.asked))

    def test_the_rest_of_a_group_is_asked_before_the_next_group(self):
        self.pages(4)
        second = [p for p in self.asked if "symbol" in p][0]
        self.assertEqual((second["market"], second["observed_on"], second["symbol"]), ("eq.NSE", "eq.2026-11-18", "gt.A"))

    def test_a_boolean_key_is_written_as_postgres_reads_it(self):
        self.assertEqual((d1_tables._literal(True), d1_tables._literal(False), d1_tables._literal(7)), ("true", "false", "7"))


if __name__ == "__main__":
    unittest.main()
