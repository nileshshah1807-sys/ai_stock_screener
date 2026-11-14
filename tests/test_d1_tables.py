"""tools.d1_tables against SQLite, which is what D1 is."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

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

    def fetch(self, table, keys, offset):
        return self.source[offset:offset + d1_tables.PAGE]

    def run_once(self, ceiling):
        session = D1Session(self.execute, max_rows_written=ceiling)
        return d1_tables.backfill(["valuation_basis"], session, self.state, DEFINITIONS, fetch=self.fetch)

    def test_it_stops_loudly_at_the_ceiling_and_the_day_budget_holds_across_runs(self):
        self.assertEqual(self.run_once(600), 2)
        state = json.loads(self.state.read_text())
        written = next(iter(state["days"].values()))
        self.assertGreaterEqual(written, 600)
        self.assertEqual(self.run_once(600), 2)  # same UTC day: nothing left of the budget
        self.assertEqual(next(iter(json.loads(self.state.read_text())["days"].values())), written)

    def test_it_resumes_and_finishes_and_a_rerun_writes_nothing(self):
        self.assertEqual(self.run_once(10_000), 0)
        self.assertEqual(self.db.execute("select count(*) from valuation_basis").fetchone()[0], 1200)
        detail = self.db.execute("select detail from valuation_basis where symbol='S0007'").fetchone()[0]
        self.assertEqual(json.loads(detail), {"q": 7})
        self.state.unlink()
        self.assertEqual(self.run_once(10_000), 0)
        self.assertEqual(next(iter(json.loads(self.state.read_text())["days"].values())), 0)


if __name__ == "__main__":
    unittest.main()
