"""Behavioural spec for the Stage 3/4 break section of the daily email."""

import unittest

import numpy as np
import pandas as pd

from screener.reporting import (
    STAGE_BREAK_MAX_AGE_DAYS,
    STAGE_BREAK_TOP_N,
    stage_break_rows,
    stage_break_section_html,
)


def run(*rows):
    columns = ["Symbol", "Company", "Investment_Rank", "Stage",
               "Breakdown_Date", "Breakdown_Age_Days", "Breakdown_From"]
    return pd.DataFrame([dict(zip(columns, row)) for row in rows])


class StageBreakRowsTests(unittest.TestCase):
    def test_recent_break_in_the_top_list_is_reported(self):
        rows = stage_break_rows(run(
            ("AAA", "Alpha Ltd", 3, "Stage 3", "2026-09-16", 2, "Stage 2"),
        ))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rank"], 3)
        self.assertEqual(rows[0]["from"], "Stage 2")

    def test_old_breaks_and_names_outside_the_top_are_left_out(self):
        rows = stage_break_rows(run(
            ("OLD", "Old Ltd", 5, "Stage 4", "2026-08-01", STAGE_BREAK_MAX_AGE_DAYS + 1, "Stage 3"),
            ("DEEP", "Deep Ltd", STAGE_BREAK_TOP_N + 1, "Stage 3", "2026-09-17", 1, "Stage 2"),
            ("FINE", "Fine Ltd", 1, "Stage 2", None, np.nan, None),
        ))
        self.assertEqual(rows, [])

    def test_most_recent_break_first(self):
        rows = stage_break_rows(run(
            ("B", "Beta", 2, "Stage 3", "2026-09-12", 6, "Stage 2"),
            ("A", "Alpha", 9, "Stage 3", "2026-09-17", 1, "S2 Candidate"),
        ))
        self.assertEqual([r["company"] for r in rows], ["Alpha", "Beta"])

    def test_a_run_without_stage_columns_has_no_section(self):
        frame = pd.DataFrame([{"Symbol": "X", "Investment_Rank": 1}])
        self.assertEqual(stage_break_rows(frame), [])
        self.assertEqual(stage_break_section_html(frame), "")


class StageBreakSectionTests(unittest.TestCase):
    def test_section_names_the_stock_and_escapes_it(self):
        html = stage_break_section_html(run(
            ("AB", "A & B Industries", 4, "Stage 3", "2026-09-17", 1, "Stage 2"),
        ))
        self.assertIn("Stage 3/4 breaks", html)
        self.assertIn("A &amp; B Industries", html)
        self.assertIn("2026-09-17 (1d)", html)


if __name__ == "__main__":
    unittest.main()
