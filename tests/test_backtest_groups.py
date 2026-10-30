import unittest

import numpy as np
import pandas as pd

from backtest.groups import GroupMap, coarse_group, group_relative_strength
from backtest.strategies import GroupStrength


def _map():
    return GroupMap(pd.DataFrame({
        "Security_ID": ["A", "A", "B"],
        "Snapshot_Date": ["2019-01-01", "2023-01-01", "2023-01-01"],
        "Group": ["IT", "Metals", "Auto"],
    }))


class GroupMapTest(unittest.TestCase):
    def test_latest_label_on_or_before_the_date(self):
        groups, backfilled = _map().as_of(pd.Series(["A", "B", "C"]), "2020-06-30")
        self.assertEqual(groups.iloc[0], "IT")
        # B is first listed later: its label is back-filled; C was never listed.
        self.assertEqual(groups.iloc[1], "Auto")
        self.assertTrue(pd.isna(groups.iloc[2]))
        self.assertEqual(backfilled.tolist(), [False, True, False])
        self.assertEqual(_map().as_of(pd.Series(["A"]), "2024-01-01")[0].iloc[0], "Metals")

    def test_both_vocabularies_fold_together(self):
        self.assertEqual(coarse_group("OIL & GAS"), coarse_group("Power"))
        self.assertEqual(coarse_group("CONSTRUCTION"), coarse_group("Realty"))

    def test_small_or_unmapped_groups_have_no_reading(self):
        groups = pd.Series(["X"] * 8 + ["Y"] * 2 + [None])
        returns = pd.Series([10.0] * 8 + [50.0, 50.0, 0.0])
        strength = group_relative_strength(returns, groups)
        self.assertTrue((strength.iloc[:8] == 0.0).all())
        self.assertTrue(strength.iloc[8:].isna().all())


class GroupGateTest(unittest.TestCase):
    def test_bottom_third_groups_leave_the_top(self):
        ids = [f"S{i}" for i in range(24)]
        names = ["Weak", "Mid", "Strong"]
        group_map = GroupMap(pd.DataFrame({
            "Security_ID": ids, "Snapshot_Date": "2018-01-01",
            "Group": [names[i % 3] for i in range(24)],
        }))
        frame = pd.DataFrame({
            "Security_ID": ids, "Signal_Date": "2020-01-31",
            "Pct_Change_6M": [(i % 3) * 10.0 for i in range(24)],
        })
        base = frame.assign(Score=np.arange(24, dtype=float)[::-1])
        scored = GroupStrength(group_map, "gate").score(frame, {"model_5": base})
        top = scored.sort_values("Score", ascending=False).head(16)
        self.assertNotIn("Weak", set(top["Group"]))
        self.assertEqual(int(scored["Group_Held_Out"].sum()), 8)


if __name__ == "__main__":
    unittest.main()
