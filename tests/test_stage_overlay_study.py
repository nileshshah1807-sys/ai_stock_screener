"""Behavioural spec for the P5 overlay simulation."""

import unittest

import numpy as np
import pandas as pd

from tools.stage_overlay_study import simulate, stage_codes


def market(sessions=520):
    """Two securities: A advances throughout; B advances, then breaks down."""
    index = pd.bdate_range("2023-01-02", periods=sessions)
    rising = 100.0 * 1.002 ** np.arange(sessions)
    breaking = rising.copy()
    breaking[450:] = breaking[449] * 0.985 ** np.arange(1, sessions - 449)
    return pd.DataFrame({"A": rising, "B": breaking}, index=index)


def panel_for(dates):
    rows = []
    for day in dates:
        rows.append({"Signal_Date": day, "Security_ID": "A", "Research_Score": 90.0})
        rows.append({"Signal_Date": day, "Security_ID": "B", "Research_Score": 80.0})
    return pd.DataFrame(rows)


class WindowBoundaryTests(unittest.TestCase):
    def test_final_period_ends_at_the_closing_rebalance_not_the_data(self):
        closes = market()
        stages = stage_codes(closes)
        dates = [closes.index[300], closes.index[321]]
        closing = closes.index[342]
        curve, _, _ = simulate(panel_for(dates + [closing]), closes, stages, None,
                               dates, closing=closing)
        self.assertEqual(curve.index[-1], closes.index[343])
        self.assertLess(curve.index[-1], closes.index[-1])

    def test_without_closing_the_final_period_runs_to_the_data_end(self):
        closes = market()
        stages = stage_codes(closes)
        dates = [closes.index[300]]
        curve, _, _ = simulate(panel_for(dates), closes, stages, None, dates)
        self.assertEqual(curve.index[-1], closes.index[-1])


class ExitRuleTests(unittest.TestCase):
    def test_a_break_into_stage_3_or_4_is_sold_and_limits_the_loss(self):
        closes = market()
        stages = stage_codes(closes)
        dates = [closes.index[440]]
        held, held_exits, _ = simulate(panel_for(dates), closes, stages, None, dates)
        sold, sold_exits, _ = simulate(panel_for(dates), closes, stages, None, dates,
                                       exit_codes={3, 4})
        self.assertEqual(held_exits, 0)
        self.assertEqual(sold_exits, 1)
        self.assertGreater(sold.iloc[-1], held.iloc[-1])

    def test_a_name_bought_in_the_exit_stage_is_not_sold_for_it(self):
        closes = market()
        stages = stage_codes(closes)
        dates = [closes.index[500]]  # B is already broken down at entry
        self.assertIn(stages.loc[dates[0], "B"], (3.0, 4.0))
        _, exits, _ = simulate(panel_for(dates), closes, stages, None, dates,
                               exit_codes={3, 4})
        self.assertEqual(exits, 0)


if __name__ == "__main__":
    unittest.main()
