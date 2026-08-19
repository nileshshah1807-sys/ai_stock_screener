"""Behavioural spec for point-in-time features, strategies and the runner.

The load-bearing test in this file is
``test_history_slice_cannot_see_past_the_signal_date``. Every other look-ahead
guarantee in the engine rests on that one boundary being correct.
"""

import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

from backtest.calendar import TradingCalendar
from backtest.execution import PricePanel
from backtest.features import HistoryPanel, build_cross_section, price_features
from backtest.metrics import rank_ic
from backtest.runner import (
    MONTHLY,
    QUARTERLY,
    UniverseRule,
    WalkForwardRunner,
    evaluate,
    portfolio_turnover_series,
    rebalance_dates,
)
from backtest.strategies import (
    EqualWeightUniverse,
    MomentumOnly,
    MomentumRiskBlend,
    RandomRanking,
    RiskOnly,
    attach_market_relative,
    weighted_block,
)


def business_days(start, count):
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


SESSIONS = business_days(date(2024, 1, 1), 400)


def synthetic_panel(specs):
    """Build a long price panel from {key: (start_price, daily_drift)} specs."""
    rows = []
    for key, (start_price, drift) in specs.items():
        price = start_price
        for day in SESSIONS:
            price *= 1.0 + drift
            rows.append(
                {
                    "Security_ID": key,
                    "Symbol": key,
                    "Trade_Date": day.isoformat(),
                    "Open": price,
                    "High": price * 1.01,
                    "Low": price * 0.99,
                    "Close": price,
                    "Volume": 100_000,
                    "Turnover_INR": 50_000_000.0,
                }
            )
    return pd.DataFrame(rows)


class HistorySliceTests(unittest.TestCase):
    def setUp(self):
        self.panel = HistoryPanel(synthetic_panel({"SEC1": (100.0, 0.001)}))

    def test_history_slice_cannot_see_past_the_signal_date(self):
        """The single boundary every other guarantee depends on."""
        signal = SESSIONS[100]
        history = self.panel.slice_upto("SEC1", signal)
        self.assertEqual(history["dates"][-1], signal)
        self.assertTrue(all(day <= signal for day in history["dates"]))

    def test_slice_length_matches_the_sessions_elapsed(self):
        history = self.panel.slice_upto("SEC1", SESSIONS[100])
        self.assertEqual(len(history["close"]), 101)

    def test_slice_on_a_non_session_takes_the_prior_session(self):
        saturday = SESSIONS[100] + timedelta(days=1)
        while saturday.weekday() < 5:
            saturday += timedelta(days=1)
        history = self.panel.slice_upto("SEC1", saturday)
        self.assertLessEqual(history["dates"][-1], saturday)

    def test_slice_before_any_history_is_none(self):
        self.assertIsNone(self.panel.slice_upto("SEC1", date(2020, 1, 1)))

    def test_unknown_key_is_none(self):
        self.assertIsNone(self.panel.slice_upto("NOPE", SESSIONS[100]))

    def test_features_from_two_dates_differ(self):
        """Proof the slice is actually driving the arithmetic."""
        early = price_features(
            self.panel.slice_upto("SEC1", SESSIONS[250]), SESSIONS[250]
        )
        late = price_features(
            self.panel.slice_upto("SEC1", SESSIONS[399]), SESSIONS[399]
        )
        self.assertNotAlmostEqual(early["Close"], late["Close"])


class FeatureTests(unittest.TestCase):
    def test_rising_series_has_positive_momentum(self):
        panel = HistoryPanel(synthetic_panel({"UP": (100.0, 0.002)}))
        record = price_features(panel.slice_upto("UP", SESSIONS[399]), SESSIONS[399])
        self.assertGreater(record["Momentum_12_1_Pct"], 0)

    def test_falling_series_has_negative_momentum(self):
        panel = HistoryPanel(synthetic_panel({"DOWN": (100.0, -0.002)}))
        record = price_features(
            panel.slice_upto("DOWN", SESSIONS[399]), SESSIONS[399]
        )
        self.assertLess(record["Momentum_12_1_Pct"], 0)

    def test_insufficient_history_yields_no_features(self):
        panel = HistoryPanel(synthetic_panel({"SEC1": (100.0, 0.001)}))
        self.assertIsNone(
            price_features(panel.slice_upto("SEC1", SESSIONS[50]), SESSIONS[50])
        )

    def test_smooth_uptrend_has_high_signed_trend_quality(self):
        panel = HistoryPanel(synthetic_panel({"UP": (100.0, 0.002)}))
        record = price_features(panel.slice_upto("UP", SESSIONS[399]), SESSIONS[399])
        self.assertGreater(record["Trend_Quality_R2"], 0.9)

    def test_smooth_downtrend_has_negative_trend_quality(self):
        """An unsigned R-squared would score a relentless decline as perfect."""
        panel = HistoryPanel(synthetic_panel({"DOWN": (100.0, -0.002)}))
        record = price_features(
            panel.slice_upto("DOWN", SESSIONS[399]), SESSIONS[399]
        )
        self.assertLess(record["Trend_Quality_R2"], 0)

    def test_turnover_is_captured_for_the_cost_model(self):
        panel = HistoryPanel(synthetic_panel({"SEC1": (100.0, 0.001)}))
        record = price_features(
            panel.slice_upto("SEC1", SESSIONS[399]), SESSIONS[399]
        )
        self.assertAlmostEqual(record["Median_Turnover_INR"], 50_000_000.0)


class CrossSectionTests(unittest.TestCase):
    def setUp(self):
        self.frame = synthetic_panel(
            {"UP": (100.0, 0.002), "FLAT": (100.0, 0.0), "DOWN": (100.0, -0.002)}
        )
        self.panel = HistoryPanel(self.frame)

    def test_all_eligible_names_appear(self):
        frame = build_cross_section(self.panel, SESSIONS[399])
        self.assertEqual(set(frame["Security_ID"]), {"UP", "FLAT", "DOWN"})

    def test_name_not_trading_on_the_signal_date_is_excluded(self):
        """A delisted name must not be resurrected into the cross-section."""
        truncated = self.frame[
            ~(
                (self.frame["Security_ID"] == "DOWN")
                & (self.frame["Trade_Date"] >= SESSIONS[300].isoformat())
            )
        ]
        panel = HistoryPanel(truncated)
        frame = build_cross_section(panel, SESSIONS[399])
        self.assertNotIn("DOWN", set(frame["Security_ID"]))

    def test_empty_result_still_has_the_schema(self):
        frame = build_cross_section(self.panel, SESSIONS[10])
        self.assertTrue(frame.empty)
        self.assertIn("Security_ID", frame.columns)


class UniverseRuleTests(unittest.TestCase):
    def frame(self):
        """Real ISIN cores: INE is a company security, INF a fund scheme."""
        return pd.DataFrame(
            {
                "Security_ID": [
                    "INE002A01",  # RELIANCE
                    "INE467B01",  # TCS, illiquid here
                    "INE001A01",  # patchy
                    "INE003C01",  # short history
                    "INF204KB1",  # NIFTYBEES, an ETF
                ],
                "Symbol": ["RELIANCE", "TCS", "PATCHY", "SHORT", "NIFTYBEES"],
                "Median_Turnover_INR": [5e7, 1e5, 5e7, 5e7, 5e7],
                "Trading_Frequency": [1.0, 1.0, 0.4, 1.0, 1.0],
                "Price_History_Sessions": [300, 300, 300, 50, 300],
            }
        )

    def test_illiquid_name_is_excluded(self):
        eligible, _ = UniverseRule().apply(self.frame())
        self.assertNotIn("INE467B01", set(eligible["Security_ID"]))

    def test_intermittently_traded_name_is_excluded(self):
        eligible, _ = UniverseRule().apply(self.frame())
        self.assertNotIn("INE001A01", set(eligible["Security_ID"]))

    def test_short_history_is_excluded(self):
        eligible, _ = UniverseRule().apply(self.frame())
        self.assertNotIn("INE003C01", set(eligible["Security_ID"]))

    def test_etf_is_excluded_by_isin_class_not_by_name(self):
        """INF is a mutual-fund scheme; no name pattern is involved."""
        eligible, diagnostics = UniverseRule().apply(self.frame())
        self.assertNotIn("INF204KB1", set(eligible["Security_ID"]))
        self.assertEqual(diagnostics["excluded_non_equity"], 1)

    def test_company_equity_survives_the_isin_class_filter(self):
        eligible, _ = UniverseRule().apply(self.frame())
        self.assertEqual(list(eligible["Security_ID"]), ["INE002A01"])

    def test_isin_class_filter_can_be_disabled(self):
        rule = UniverseRule(require_identifier_prefix=None)
        eligible, _ = rule.apply(self.frame())
        self.assertIn("INF204KB1", set(eligible["Security_ID"]))

    def test_named_exclusion_still_works_alongside(self):
        rule = UniverseRule(exclude_symbols=("RELIANCE",))
        eligible, diagnostics = rule.apply(self.frame())
        self.assertEqual(diagnostics["excluded_by_name"], 1)
        self.assertTrue(eligible.empty)

    def test_diagnostics_report_each_reason(self):
        _, diagnostics = UniverseRule().apply(self.frame())
        self.assertEqual(diagnostics["input"], 5)
        self.assertGreaterEqual(diagnostics["failed_turnover"], 1)


class RebalanceDateTests(unittest.TestCase):
    def setUp(self):
        self.calendar = TradingCalendar(SESSIONS)

    def test_monthly_gives_one_date_per_month(self):
        dates = rebalance_dates(
            self.calendar, SESSIONS[0], SESSIONS[-1], frequency=MONTHLY
        )
        months = {(day.year, day.month) for day in dates}
        self.assertEqual(len(dates), len(months))

    def test_monthly_uses_the_last_session_of_the_month(self):
        dates = rebalance_dates(
            self.calendar, date(2024, 1, 1), date(2024, 1, 31), frequency=MONTHLY
        )
        january = [day for day in SESSIONS if day.month == 1 and day.year == 2024]
        self.assertEqual(dates, [january[-1]])

    def test_quarterly_gives_roughly_a_third_as_many(self):
        monthly = rebalance_dates(
            self.calendar, SESSIONS[0], SESSIONS[-1], frequency=MONTHLY
        )
        quarterly = rebalance_dates(
            self.calendar, SESSIONS[0], SESSIONS[-1], frequency=QUARTERLY
        )
        self.assertLess(len(quarterly), len(monthly))

    def test_unsupported_frequency_is_rejected(self):
        with self.assertRaises(ValueError):
            rebalance_dates(self.calendar, SESSIONS[0], SESSIONS[-1], frequency="daily")

    def test_window_outside_the_calendar_is_empty(self):
        self.assertEqual(
            rebalance_dates(self.calendar, date(2019, 1, 1), date(2019, 2, 1)), []
        )


class StrategyTests(unittest.TestCase):
    def cross_section(self):
        frame = synthetic_panel(
            {
                "UP": (100.0, 0.003),
                "MILD": (100.0, 0.001),
                "FLAT": (100.0, 0.0),
                "SOFT": (100.0, -0.001),
                "DOWN": (100.0, -0.003),
            }
        )
        return build_cross_section(HistoryPanel(frame), SESSIONS[399])

    def test_momentum_ranks_the_riser_above_the_faller(self):
        scored = MomentumOnly().score(self.cross_section())
        ranked = scored.set_index("Security_ID")["Score"]
        self.assertGreater(ranked["UP"], ranked["DOWN"])

    def test_momentum_ordering_is_monotone_in_drift(self):
        scored = MomentumOnly().score(self.cross_section())
        ranked = scored.set_index("Security_ID")["Score"]
        order = [ranked[key] for key in ("UP", "MILD", "FLAT", "SOFT", "DOWN")]
        self.assertEqual(order, sorted(order, reverse=True))

    def test_equal_weight_benchmark_scores_everything_alike(self):
        scored = EqualWeightUniverse().score(self.cross_section())
        self.assertEqual(scored["Score"].nunique(), 1)

    def test_risk_block_produces_a_score(self):
        scored = RiskOnly().score(self.cross_section())
        self.assertTrue(scored["Score"].notna().any())

    def test_blend_exposes_its_component_blocks(self):
        scored = MomentumRiskBlend().score(self.cross_section())
        self.assertIn("Momentum_Score", scored.columns)
        self.assertIn("Risk_Score", scored.columns)

    def test_random_ranking_is_reproducible(self):
        frame = self.cross_section()
        first = RandomRanking(seed=3).score(frame)["Score"].tolist()
        second = RandomRanking(seed=3).score(frame)["Score"].tolist()
        self.assertEqual(first, second)

    def test_market_relative_centres_on_the_universe(self):
        frame = attach_market_relative(self.cross_section())
        self.assertAlmostEqual(float(frame["RS_Market_6M_Pct"].median()), 0.0, places=6)

    def test_missing_input_shrinks_toward_neutral_not_to_zero(self):
        frame = self.cross_section().copy()
        for column in ("RiskAdj_Momentum_12_1", "RiskAdj_Momentum_6_1",
                       "Trend_Quality_R2"):
            frame[column] = np.nan
        frame = attach_market_relative(frame)
        score, coverage = weighted_block(
            frame,
            (
                ("RiskAdj_Momentum_12_1", 0.5, True),
                ("RS_Market_6M_Pct", 0.5, True),
            ),
            min_coverage=0.4,
        )
        # Half the weight is missing, so scores compress toward 50 rather than 0.
        self.assertTrue((score.dropna() > 20).all())
        self.assertTrue((coverage <= 0.6).all())


class RunnerTests(unittest.TestCase):
    def setUp(self):
        # Drift ordering is the ground truth momentum should recover. Keys are
        # INE-prefixed so the production ISIN-class filter treats them as equity.
        specs = {
            f"INE{index:03d}A01": (100.0, 0.0025 - index * 0.0002)
            for index in range(25)
        }
        frame = synthetic_panel(specs)
        self.calendar = TradingCalendar(SESSIONS)
        self.history = HistoryPanel(frame)
        self.prices = PricePanel(frame)
        self.runner = WalkForwardRunner(
            self.calendar,
            self.history,
            self.prices,
            universe_rule=UniverseRule(min_median_turnover_inr=1e6),
            horizons=(1, 3),
        )
        self.dates = rebalance_dates(
            self.calendar, SESSIONS[260], SESSIONS[330], frequency=MONTHLY
        )

    def test_runner_produces_fills_for_every_strategy_and_date(self):
        fills, diagnostics = self.runner.run(
            [MomentumOnly(), EqualWeightUniverse()], self.dates
        )
        self.assertEqual(set(fills["Strategy"]), {"momentum_only", "equal_weight_universe"})
        self.assertEqual(len(diagnostics), len(self.dates))

    def test_forward_return_columns_are_attached(self):
        fills, _ = self.runner.run([MomentumOnly()], self.dates)
        self.assertIn("Forward_Return_1M_Pct", fills.columns)
        self.assertIn("Forward_Return_3M_Pct", fills.columns)

    def test_momentum_recovers_the_drift_ordering(self):
        """A constructed universe where momentum genuinely predicts: IC must be
        strongly positive, or the wiring is wrong rather than the model."""
        fills, _ = self.runner.run([MomentumOnly()], self.dates)
        period = fills[fills["Signal_Date"] == fills["Signal_Date"].iloc[0]]
        ic = rank_ic(period["Score"], period["Forward_Return_1M_Pct"])
        self.assertIsNotNone(ic)
        self.assertGreater(ic, 0.8)

    def test_evaluate_summarises_per_strategy_and_horizon(self):
        fills, _ = self.runner.run(
            [MomentumOnly(), EqualWeightUniverse()], self.dates
        )
        results = evaluate(fills, horizons=(1, 3), portfolio_sizes=(5, 10))
        self.assertIn("momentum_only", results)
        self.assertIn("1M", results["momentum_only"])
        self.assertIn("top_5", results["momentum_only"]["1M"]["portfolios"])

    def test_equal_weight_benchmark_has_no_predictive_ic(self):
        fills, _ = self.runner.run([EqualWeightUniverse()], self.dates)
        results = evaluate(fills, horizons=(1,), portfolio_sizes=(5,))
        # Identical scores across the cross-section cannot rank anything.
        self.assertIsNone(results["equal_weight_universe"]["1M"]["ic"]["mean"])

    def test_turnover_is_reported_per_strategy(self):
        fills, _ = self.runner.run([MomentumOnly()], self.dates)
        result = portfolio_turnover_series(fills, size=5)
        self.assertIn("momentum_only", result)
        self.assertIsNotNone(result["momentum_only"]["mean_one_way_turnover"])

    def test_stable_ranking_produces_low_turnover(self):
        """Monotone drift means the top names barely change month to month."""
        fills, _ = self.runner.run([MomentumOnly()], self.dates)
        result = portfolio_turnover_series(fills, size=5)
        self.assertLess(result["momentum_only"]["mean_one_way_turnover"], 0.4)

    def test_costs_reduce_returns_when_a_cost_model_is_supplied(self):
        from backtest.costs import CostModel

        runner = WalkForwardRunner(
            self.calendar,
            self.history,
            self.prices,
            universe_rule=UniverseRule(min_median_turnover_inr=1e6),
            cost_model=CostModel(),
            horizons=(1,),
        )
        fills, _ = runner.run([MomentumOnly()], self.dates)
        self.assertIn("Net_Return_1M_Pct", fills.columns)
        usable = fills.dropna(subset=["Forward_Return_1M_Pct", "Net_Return_1M_Pct"])
        self.assertTrue(
            (usable["Net_Return_1M_Pct"] < usable["Forward_Return_1M_Pct"]).all()
        )

    def test_evaluate_on_an_empty_frame_is_safe(self):
        self.assertEqual(evaluate(pd.DataFrame()), {})


if __name__ == "__main__":
    unittest.main()
