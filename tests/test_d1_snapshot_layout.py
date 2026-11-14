"""storage/d1/screener_snapshot.sql keeps a real column for everything the grid filters, sorts or shows."""

import re
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DDL = (ROOT / "storage/d1/screener_snapshot.sql").read_text()
LIB = ROOT / "dashboard/lib"


def _snapshot_columns() -> set[str]:
    db = sqlite3.connect(":memory:")
    db.execute('CREATE TABLE "screener_history" (market TEXT, symbol TEXT, observed_on TEXT)')
    db.executescript(DDL)
    return {row[1] for row in db.execute("select * from pragma_table_info('screener_snapshot')")}


def _quoted(text: str) -> set[str]:
    return set(re.findall(r'"([a-z0-9_]+)"', text))


class SnapshotLayoutTest(unittest.TestCase):
    def test_fits_d1_column_cap(self):
        self.assertLessEqual(len(_snapshot_columns()), 100)

    def test_grid_fields_sorts_and_ranges_are_real_columns(self):
        columns = (LIB / "columns.ts").read_text()
        queries = (LIB / "queries.ts").read_text()
        wanted = set().union(
            *(_quoted(block) for block in re.findall(r"fields:\s*\[([^\]]*)\]", columns)),
            _quoted(re.search(r"BASE_FIELDS[^=]*=\s*\[(.*?)\]", columns, re.S).group(1)),
            _quoted(re.search(r"const SORTABLE = new Set\(\[(.*?)\]\)", queries, re.S).group(1)),
            re.findall(r'column:\s*"([a-z0-9_]+)"', (LIB / "screener-ranges.mjs").read_text()),
        )
        self.assertEqual(wanted - _snapshot_columns(), set())

    def test_default_sort_is_indexed(self):
        self.assertIn('("market", "run_date", "market_cap" DESC)', DDL)


if __name__ == "__main__":
    unittest.main()
