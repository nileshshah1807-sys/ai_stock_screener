"""Behavioural spec for the Model 5.0 trend, momentum and risk price features."""

import unittest

import numpy as np
import pandas as pd

from screener.market_data import TechnicalEnhancer, calculate_trend_risk_features


def steady_series(sessions=300, start=100.0, daily=0.001):
    return pd.Series(
        [start * (1.0 + daily) ** step for step in range(sessions)],
        index=pd.date_range("2024-01-01", periods=sessions, freq="B"),
    )


class SkipMonthReturnTests(unittest.TestCase):
    def test_formation_window_ends_one_month_ago(self):
        # A series that rises steadily then spikes only in the final month.
        values = pd.Series([100.0] * 260 + [500.0] * 21)
        # 12-1 must ignore the terminal spike entirely: both endpoints of the
        # formation window sit in the flat stretch.
        self.assertAlmostEqual(
            TechnicalEnhancer.skip_month_return(values, 252), 0.0, places=6
        )
        # The plain 12-month return does see it.
        self.assertGreater(
            TechnicalEnhancer.calculate_pct_return(values, 252), 100.0
        )

    def test_insufficient_history_is_missing_not_zero(self):
        self.assertTrue(
            np.isnan(TechnicalEnhancer.skip_month_return(pd.Series([1.0] * 100), 252))
        )

    def test_known_two_point_ratio(self):
        values = pd.Series([50.0] * 200 + [75.0] * 22)
        # Index -22 is 75, index -(126+1) is 50 -> +50%.
        self.assertAlmostEqual(
            TechnicalEnhancer.skip_month_return(values, 126), 50.0, places=6
        )


class LongTrendTests(unittest.TestCase):
    def test_ma200_matches_explicit_mean(self):
        closes = steady_series()
        features = calculate_trend_risk_features(closes)
        expected = float(closes.tail(200).mean())
        self.assertAlmostEqual(features["MA200"], round(expected, 2), places=2)

    def test_sessions_above_share_ignores_pre_average_sessions(self):
        # Sessions before the 200-day average exists are unknown, not "below".
        # Counting them as below understated the share for every recent listing.
        features = calculate_trend_risk_features(steady_series(sessions=260))
        self.assertAlmostEqual(features["Sessions_Above_MA200_Share"], 1.0, places=6)

    def test_ma200_missing_below_two_hundred_sessions(self):
        features = calculate_trend_risk_features(steady_series(sessions=150))
        self.assertTrue(np.isnan(features["MA200"]))
        self.assertTrue(np.isnan(features["MA200_Slope_Pct"]))
        # A partially observed long average must never be silently substituted:
        # an under-seasoned listing would otherwise look like an established
        # uptrend to the BUY gate.
        self.assertTrue(np.isnan(features["Price_To_MA200_Pct"]))

    def test_uptrend_is_above_a_rising_average(self):
        features = calculate_trend_risk_features(steady_series())
        self.assertGreater(features["Price_To_MA200_Pct"], 0.0)
        self.assertGreater(features["MA200_Slope_Pct"], 0.0)
        self.assertGreater(features["MA50_To_MA200_Pct"], 0.0)
        self.assertEqual(features["Below_MA200_Streak"], 0)
        self.assertAlmostEqual(features["Sessions_Above_MA200_Share"], 1.0, places=6)

    def test_below_ma200_streak_counts_only_the_trailing_run(self):
        rising = [100.0 * (1.005**step) for step in range(260)]
        # Collapse hard enough that the last 15 sessions close below MA200.
        falling = [rising[-1] * (0.97**step) for step in range(1, 41)]
        features = calculate_trend_risk_features(pd.Series(rising + falling))
        self.assertGreaterEqual(features["Below_MA200_Streak"], 10)
        self.assertLess(features["Price_To_MA200_Pct"], 0.0)

    def test_trend_quality_is_near_one_for_a_smooth_advance(self):
        features = calculate_trend_risk_features(steady_series())
        self.assertGreater(features["Trend_Quality_R2"], 0.99)

    def test_trend_quality_falls_for_a_round_trip(self):
        # The scored window is the last 126 sessions, so build a genuine
        # round-trip inside it rather than a clean second leg.
        rng = np.random.default_rng(11)
        chop = 100 * np.cumprod(1 + rng.normal(0, 0.02, 300))
        features = calculate_trend_risk_features(pd.Series(chop))
        self.assertLess(abs(features["Trend_Quality_R2"]), 0.9)

    def test_trend_quality_is_signed_against_a_smooth_decline(self):
        # An unsigned R-squared scores a relentless decline a perfect 1.0. Since
        # this feeds a momentum block where higher is better, a clean downtrend
        # must be the worst reading, not the best.
        decline = pd.Series([100.0 * (0.995**step) for step in range(300)])
        features = calculate_trend_risk_features(decline)
        self.assertLess(features["Trend_Quality_R2"], -0.99)
        rise = calculate_trend_risk_features(steady_series())
        self.assertGreater(rise["Trend_Quality_R2"], 0.99)


class RiskFeatureTests(unittest.TestCase):
    def test_drawdown_is_negative_and_bounded(self):
        up = [100.0] * 200
        crash = [50.0] * 60
        features = calculate_trend_risk_features(pd.Series(up + crash))
        self.assertLessEqual(features["Max_Drawdown_1Y_Pct"], -49.0)
        self.assertGreaterEqual(features["Max_Drawdown_1Y_Pct"], -100.0)

    def test_flat_series_has_zero_volatility_and_no_drawdown(self):
        features = calculate_trend_risk_features(pd.Series([100.0] * 300))
        self.assertAlmostEqual(features["Volatility_Ann_Pct"], 0.0, places=6)
        self.assertAlmostEqual(features["Max_Drawdown_1Y_Pct"], 0.0, places=6)

    def test_volatile_series_scores_higher_volatility(self):
        rng = np.random.default_rng(7)
        calm = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.002, 300)))
        wild = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.030, 300)))
        self.assertLess(
            calculate_trend_risk_features(calm)["Volatility_Ann_Pct"],
            calculate_trend_risk_features(wild)["Volatility_Ann_Pct"],
        )

    def test_return_concentration_detects_a_few_dominant_sessions(self):
        rng = np.random.default_rng(3)
        base = np.full(300, 0.0001)
        spiky = base.copy()
        spiky[[10, 40, 90, 150, 210]] = 0.35
        even = rng.normal(0.0005, 0.0005, 300)
        concentrated = calculate_trend_risk_features(
            pd.Series(100 * np.cumprod(1 + spiky))
        )["Return_Concentration_1Y"]
        diffuse = calculate_trend_risk_features(
            pd.Series(100 * np.cumprod(1 + even))
        )["Return_Concentration_1Y"]
        self.assertGreater(concentrated, diffuse)

    def test_gap_risk_requires_opens(self):
        closes = steady_series()
        self.assertTrue(np.isnan(calculate_trend_risk_features(closes)["Gap_Risk_Pct"]))
        opens = closes.shift(1).fillna(closes.iloc[0]) * 1.02
        features = calculate_trend_risk_features(closes, opens=opens)
        self.assertFalse(np.isnan(features["Gap_Risk_Pct"]))

    def test_empty_input_returns_explicit_missing(self):
        features = calculate_trend_risk_features(pd.Series([], dtype=float))
        self.assertEqual(features["Price_History_Sessions"], 0)
        self.assertTrue(np.isnan(features["MA200"]))


if __name__ == "__main__":
    unittest.main()
