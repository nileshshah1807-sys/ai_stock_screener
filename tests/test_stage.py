"""Behavioural spec for stage analysis, RS rating and the timing score."""

import unittest

import numpy as np
import pandas as pd

from screener.stage import (
    ENTRY_ENTER,
    ENTRY_EXTENDED,
    ENTRY_PULLBACK,
    ENTRY_STAGE_3,
    ENTRY_STAGE_4,
    S2_CANDIDATE,
    STAGE_2,
    STAGE_3,
    STAGE_4,
    attach_timing,
    classify_stages,
    extension_score,
    stage_features,
)


def path(*legs, start=100.0):
    """Geometric price path from (sessions, daily_return) legs."""
    prices = [start]
    for sessions, daily in legs:
        for _ in range(sessions):
            prices.append(prices[-1] * (1.0 + daily))
    return pd.Series(prices[1:])


def dated(series, start="2023-01-02"):
    return pd.Series(
        series.to_numpy(), index=pd.bdate_range(start, periods=len(series))
    )


class StageClassificationTests(unittest.TestCase):
    def test_steady_advance_is_stage_2(self):
        result = stage_features(path((400, 0.002)))
        self.assertEqual(result["Stage"], STAGE_2)

    def test_steady_decline_is_stage_4(self):
        result = stage_features(path((400, -0.002)))
        self.assertEqual(result["Stage"], STAGE_4)

    def test_pullback_under_ma50_in_an_advance_is_a_candidate(self):
        # Long advance, then a short dip: below MA50, still well above MA150.
        result = stage_features(path((380, 0.003), (12, -0.008)))
        self.assertEqual(result["Stage"], S2_CANDIDATE)

    def test_break_below_ma150_while_it_still_rises_is_stage_3(self):
        result = stage_features(path((380, 0.003), (35, -0.012)))
        self.assertEqual(result["Stage"], STAGE_3)

    def test_undefined_without_enough_history(self):
        result = stage_features(path((150, 0.002)))
        self.assertIsNone(result["Stage"])
        self.assertTrue(np.isnan(result["Days_In_Stage"]))

    def test_labels_are_undefined_before_ma200_and_its_slope_exist(self):
        labels = classify_stages(path((300, 0.002)))
        self.assertTrue(labels.iloc[:220].isna().all())
        self.assertTrue(labels.iloc[221:].notna().all())


class StageRunTests(unittest.TestCase):
    def test_days_in_stage_are_calendar_days_since_the_run_began(self):
        closes = dated(path((380, 0.003), (12, -0.008)))
        result = stage_features(closes)
        entry = pd.Timestamp(result["Stage_Entry_Date"])
        self.assertEqual(result["Days_In_Stage"], (closes.index[-1] - entry).days)
        self.assertEqual(result["Stage_Entry_Price"], round(float(closes.loc[entry]), 2))

    def test_pullback_restarts_days_in_stage_but_not_advance_age(self):
        result = stage_features(dated(path((380, 0.003), (12, -0.008))))
        self.assertLess(result["Days_In_Stage"], 30)
        self.assertGreater(result["Advance_Age_Days"], 150)

    def test_run_that_began_before_the_data_is_marked_censored(self):
        result = stage_features(path((400, 0.002)))
        self.assertTrue(result["Stage_Run_Censored"])

    def test_advance_age_is_absent_outside_an_advance(self):
        result = stage_features(path((400, -0.002)))
        self.assertTrue(np.isnan(result["Advance_Age_Days"]))

    def test_timezone_aware_index_is_accepted(self):
        closes = dated(path((300, 0.002)))
        closes.index = closes.index.tz_localize("Asia/Kolkata")
        result = stage_features(closes)
        self.assertEqual(result["Stage"], STAGE_2)
        self.assertEqual(len(result["Stage_Entry_Date"]), 10)


class RelativeStrengthInputTests(unittest.TestCase):
    def test_weighted_return_uses_the_ibd_quarter_weights(self):
        closes = path((300, 0.001))
        result = stage_features(closes)
        last = closes.iloc[-1]
        expected = 100.0 * sum(
            weight * (last / closes.iloc[-1 - sessions] - 1.0)
            for sessions, weight in ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2))
        )
        self.assertAlmostEqual(result["RS_Raw_Pct"], expected, places=8)

    def test_one_month_ago_value_excludes_the_last_21_sessions(self):
        closes = path((300, 0.001))
        lagged = stage_features(closes.iloc[:-21])
        self.assertAlmostEqual(
            stage_features(closes)["RS_Raw_1M_Ago_Pct"], lagged["RS_Raw_Pct"], places=8
        )

    def test_no_weighted_return_without_a_full_year(self):
        self.assertTrue(np.isnan(stage_features(path((200, 0.001)))["RS_Raw_Pct"]))


class ExtensionScoreTests(unittest.TestCase):
    def test_piecewise_shape(self):
        scores = extension_score(pd.Series([-5.0, 0.0, 25.0, 50.0, 75.0, 120.0, np.nan]))
        self.assertEqual(list(scores.iloc[:6]), [50.0, 100.0, 100.0, 50.0, 0.0, 0.0])
        self.assertTrue(np.isnan(scores.iloc[6]))


class AttachTimingTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame(
            {
                "Symbol": ["A", "B", "C", "D"],
                "Research_Score": [100.0, 85.0, 70.0, 90.0],
                "Stage": [S2_CANDIDATE, STAGE_2, STAGE_4, None],
                "Price_To_MA150_Pct": [20.0, 10.0, -15.0, np.nan],
                "RS_Raw_Pct": [90.0, 40.0, -20.0, np.nan],
                "RS_Raw_1M_Ago_Pct": [95.0, 20.0, -10.0, np.nan],
            }
        )

    def test_rs_rating_is_a_1_to_99_percentile(self):
        result = attach_timing(self.frame())
        ratings = result["RS_Rating"].dropna()
        self.assertEqual(ratings.max(), 99.0)
        self.assertGreaterEqual(ratings.min(), 1.0)
        self.assertTrue(np.isnan(result.loc[3, "RS_Rating"]))

    def test_zero_weight_leaves_the_research_order_untouched(self):
        result = attach_timing(self.frame(), timing_weight=0.0)
        pd.testing.assert_series_equal(
            result["Action_Score"], result["Research_Score"], check_names=False
        )

    def test_weight_blends_research_and_timing(self):
        result = attach_timing(self.frame(), timing_weight=0.3)
        row = result.loc[1]
        self.assertAlmostEqual(
            row["Action_Score"], round(0.7 * 85.0 + 0.3 * row["Timing_Score"], 2)
        )

    def test_fresh_stage_2_can_outrank_a_higher_research_score(self):
        result = attach_timing(self.frame(), timing_weight=0.4)
        self.assertGreater(result.loc[1, "Action_Score"], result.loc[0, "Action_Score"] - 15)
        self.assertLess(result.loc[2, "Action_Score"], result.loc[1, "Action_Score"])

    def test_missing_stage_blends_at_neutral_50(self):
        result = attach_timing(self.frame(), timing_weight=0.3)
        self.assertTrue(np.isnan(result.loc[3, "Timing_Score"]))
        self.assertAlmostEqual(result.loc[3, "Action_Score"], 0.7 * 90.0 + 0.3 * 50.0)

    def test_weight_outside_unit_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            attach_timing(self.frame(), timing_weight=1.5)

    def test_entry_states(self):
        frame = self.frame()
        frame.loc[len(frame)] = ["E", 80.0, STAGE_2, 60.0, 50.0, 50.0]
        frame.loc[len(frame)] = ["F", 80.0, STAGE_3, -3.0, 0.0, 0.0]
        result = attach_timing(frame).set_index("Symbol")
        self.assertEqual(result.loc["A", "Entry_State"], ENTRY_PULLBACK)
        self.assertEqual(result.loc["B", "Entry_State"], ENTRY_ENTER)
        self.assertEqual(result.loc["C", "Entry_State"], ENTRY_STAGE_4)
        self.assertEqual(result.loc["E", "Entry_State"], ENTRY_EXTENDED)
        self.assertEqual(result.loc["F", "Entry_State"], ENTRY_STAGE_3)
        self.assertTrue(pd.isna(result.loc["D", "Entry_State"]))

    def test_does_not_mutate_the_input(self):
        frame = self.frame()
        before = frame.copy()
        attach_timing(frame, timing_weight=0.3)
        pd.testing.assert_frame_equal(frame, before)


class TimingStrategyTests(unittest.TestCase):
    def shared(self):
        model_5 = AttachTimingTests().frame()
        model_5["Score"] = model_5["Research_Score"]
        return {"model_5": model_5}

    def test_score_is_the_action_score(self):
        from backtest.strategies import Model5Timing

        shared = self.shared()
        scored = Model5Timing("t", 0.3).score(shared["model_5"], shared)
        pd.testing.assert_series_equal(
            scored["Score"], scored["Action_Score"], check_names=False
        )

    def test_stage_4_demotion_ranks_it_below_everything(self):
        from backtest.strategies import Model5Timing

        shared = self.shared()
        shared["model_5"].loc[2, "Research_Score"] = 100.0
        scored = Model5Timing("t", 0.0, demote_stage_4=True).score(
            shared["model_5"], shared
        )
        self.assertEqual(scored["Score"].idxmin(), 2)

    def test_declared_grid_is_five_variants_in_order(self):
        from backtest.strategies import timing_strategies

        names = [strategy.name for strategy in timing_strategies()]
        self.assertEqual(
            names,
            [
                "model_5_t1_w10",
                "model_5_t2_w20",
                "model_5_t3_w30",
                "model_5_t4_w40",
                "model_5_t5_stage4_demotion_only",
            ],
        )


class ActionRankPolicyTests(unittest.TestCase):
    """Action_Rank is published beside Investment_Rank, never in its place."""

    def rows(self):
        from tests.test_factor_policy import clean_row

        return [
            clean_row(
                "TOPPING", score=95.0, Stage=STAGE_4, Price_To_MA150_Pct=-8.0,
                RS_Raw_Pct=10.0, RS_Raw_1M_Ago_Pct=40.0,
            ),
            clean_row(
                "FRESH", score=85.0, Stage=STAGE_2, Price_To_MA150_Pct=12.0,
                RS_Raw_Pct=60.0, RS_Raw_1M_Ago_Pct=30.0,
            ),
            clean_row(
                "MIDDLE", score=80.0, Stage=S2_CANDIDATE, Price_To_MA150_Pct=5.0,
                RS_Raw_Pct=20.0, RS_Raw_1M_Ago_Pct=20.0,
            ),
        ]

    def finalize(self, **settings):
        from screener.recommendation import finalize_recommendations
        from tests.test_factor_policy import ResearchRankConfig

        config = type("TimingConfig", (ResearchRankConfig,), settings)
        return finalize_recommendations(pd.DataFrame(self.rows()), config).set_index(
            "Symbol"
        )

    def test_timing_weight_reorders_action_rank_only(self):
        result = self.finalize(STAGE_TIMING_ENABLED=True, TIMING_WEIGHT=0.4)
        self.assertEqual(result.loc["TOPPING", "Investment_Rank"], 1)
        self.assertEqual(result.loc["FRESH", "Action_Rank"], 1)
        self.assertEqual(result.loc["TOPPING", "Action_Rank"], 3)
        self.assertEqual(result.loc["TOPPING", "Entry_State"], ENTRY_STAGE_4)

    def test_zero_weight_action_rank_follows_research(self):
        result = self.finalize(STAGE_TIMING_ENABLED=True, TIMING_WEIGHT=0.0)
        self.assertEqual(
            list(result.sort_values("Action_Rank").index),
            list(result.sort_values("Investment_Rank").index),
        )

    def test_disabled_publishes_no_timing_columns(self):
        result = self.finalize(STAGE_TIMING_ENABLED=False, TIMING_WEIGHT=0.4)
        self.assertNotIn("Action_Rank", result.columns)
        self.assertNotIn("Timing_Score", result.columns)

    def test_ratings_are_unchanged_by_the_timing_weight(self):
        off = self.finalize(STAGE_TIMING_ENABLED=False)
        on = self.finalize(STAGE_TIMING_ENABLED=True, TIMING_WEIGHT=0.4)
        pd.testing.assert_series_equal(off["Rating"], on["Rating"].loc[off.index])


if __name__ == "__main__":
    unittest.main()
