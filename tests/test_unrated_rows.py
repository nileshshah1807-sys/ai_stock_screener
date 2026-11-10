"""SME names the run cannot score are published UNRATED, without touching the scored frame."""

import unittest

import numpy as np
import pandas as pd

from screener.recommendation import unrated_rows


class UnratedRowsTests(unittest.TestCase):
    def setUp(self):
        self.held_out = pd.DataFrame({"Symbol": ["NOSTMT"], "Company": ["No Statement Ltd"], "Current_Price": [10.0]})
        self.short = pd.DataFrame(
            {"Symbol": ["NEWCO"], "Company": ["New Co"], "Current_Price": [20.0], "Price_History_Sessions": [41]}
        )

    def test_rows_carry_unrated_and_a_reason_each(self):
        rows = unrated_rows(self.held_out, self.short, 60).set_index("Symbol")
        self.assertEqual(set(rows["Rating"]), {"UNRATED"})
        self.assertTrue(rows["Rating_Capped"].all())
        self.assertFalse(rows["Buy_Eligible"].any())
        self.assertEqual(rows.at["NOSTMT", "Rating_Cap_Reason"], "Not rated: no annual financial statements yet")
        self.assertEqual(rows.at["NEWCO", "Rating_Cap_Reason"], "Not rated: 41 of 60 sessions of price history")

    def test_decision_columns_are_absent_not_zero(self):
        scored = pd.DataFrame(
            {"Symbol": ["TCS"], "Rating": ["BUY"], "Investment_Rank": [1], "Final_Score": [70.0]}
        )
        export = pd.concat([scored, unrated_rows(self.held_out, None, 60)], ignore_index=True)
        row = export.set_index("Symbol").loc["NOSTMT"]
        self.assertTrue(np.isnan(row["Investment_Rank"]))
        self.assertTrue(np.isnan(row["Final_Score"]))
        # The scored rows are exactly as they were.
        pd.testing.assert_frame_equal(export.iloc[:1].reset_index(drop=True)[list(scored.columns)], scored, check_dtype=False)

    def test_nothing_to_show_gives_an_empty_frame(self):
        self.assertTrue(unrated_rows(pd.DataFrame(), pd.DataFrame(), 60).empty)
        self.assertTrue(unrated_rows(None, None, 60).empty)
