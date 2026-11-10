"""A hand-written view a signed-in viewer can read must gate every rating-rule column."""

import re
import unittest
from pathlib import Path

# storage/dashboard_schema.sql and multi_market_migration.sql define the earlier,
# ungated screener_movers; rating_access_schema.sql replaces it and is applied last.
SUPERSEDED = {"dashboard_schema.sql", "multi_market_migration.sql", "supabase_schema.sql"}
RATING_KEY = re.compile(
    re.search(r"RATING_KEY = /(.*)/;", Path("dashboard/lib/ratings.mjs").read_text()).group(1)
)


class RatingViewsGatedTests(unittest.TestCase):
    def test_source_columns_matching_the_rule_sit_behind_the_admin_check(self):
        checked = 0
        for path in sorted(Path("storage").glob("*.sql")):
            if path.name in SUPERSEDED:
                continue
            text = re.sub(r"--[^\n]*", "", path.read_text())
            # Only a view over a base table can leak; one over *_visible is gated already.
            if not re.search(r"\b(from|join)\s+screener_(snapshot|history|runs)\b(?!_visible)", text):
                continue
            for line in text.splitlines():
                for alias, column in re.findall(r"\b([tp])\.([a-z_0-9]+)", line):
                    if RATING_KEY.search(column) and not column.startswith("rs_rating"):
                        checked += 1
                        self.assertIn("dashboard_is_admin()", line, f"{path.name}: {alias}.{column}")
        self.assertGreater(checked, 0, "the movers view's gated columns should have been found")


if __name__ == "__main__":
    unittest.main()
