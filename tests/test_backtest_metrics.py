"""Behavioural spec for the walk-forward evaluation metrics."""

import unittest

import numpy as np
import pandas as pd

from backtest.metrics import (
    bucket_returns,
    bucket_spread,
    equity_curve,
    excess_metrics,
    ic_summary,
    max_drawdown,
    monotonicity,
    portfolio_metrics,
    rank_ic,
    turnover,
)


class RankIcTests(unittest.TestCase):
    def test_perfect_ordering_is_one(self):
        scores = list(range(30))
        returns = list(range(30))
        self.assertAlmostEqual(rank_ic(scores, returns), 1.0)

    def test_perfect_inversion_is_minus_one(self):
        scores = list(range(30))
        returns = list(range(30))[::-1]
        self.assertAlmostEqual(rank_ic(scores, returns), -1.0)

    def test_ic_is_rank_based_not_level_based(self):
        """A monotone but wildly non-linear return still ranks perfectly."""
        scores = list(range(30))
        returns = [x**3 for x in range(30)]
        self.assertAlmostEqual(rank_ic(scores, returns), 1.0)

    def test_thin_cross_section_returns_none_rather_than_noise(self):
        self.assertIsNone(rank_ic([1, 2, 3], [3, 2, 1]))

    def test_min_observations_is_configurable(self):
        self.assertIsNotNone(rank_ic([1, 2, 3], [3, 2, 1], min_observations=3))

    def test_constant_scores_yield_none(self):
        self.assertIsNone(rank_ic([5] * 30, list(range(30))))

    def test_missing_values_are_dropped_pairwise(self):
        scores = list(range(30)) + [np.nan]
        returns = list(range(30)) + [5.0]
        self.assertAlmostEqual(rank_ic(scores, returns), 1.0)

    def test_rows_missing_a_return_do_not_count_toward_the_minimum(self):
        scores = list(range(30))
        returns = [np.nan] * 30
        self.assertIsNone(rank_ic(scores, returns))


class IcSummaryTests(unittest.TestCase):
    def test_reports_mean_median_and_positive_share(self):
        summary = ic_summary([0.10, 0.05, -0.02, 0.08])
        self.assertEqual(summary["periods"], 4)
        self.assertAlmostEqual(summary["mean"], 0.0525)
        self.assertAlmostEqual(summary["median"], 0.065)
        self.assertAlmostEqual(summary["positive_share"], 0.75)

    def test_worst_and_best_periods_are_reported(self):
        summary = ic_summary([0.10, -0.20, 0.05])
        self.assertAlmostEqual(summary["worst"], -0.20)
        self.assertAlmostEqual(summary["best"], 0.10)

    def test_a_mean_carried_by_one_outlier_is_visible_in_the_spread(self):
        """The distinction p0.md insists on: consistency, not just an average."""
        consistent = ic_summary([0.05] * 10)
        lumpy = ic_summary([0.5] + [0.0] * 9)
        self.assertAlmostEqual(consistent["mean"], lumpy["mean"])
        self.assertLess(consistent["std"], lumpy["std"])
        self.assertGreater(consistent["positive_share"], lumpy["positive_share"])

    def test_none_values_are_excluded(self):
        self.assertEqual(ic_summary([None, 0.1, None])["periods"], 1)

    def test_empty_input_is_safe(self):
        self.assertEqual(ic_summary([])["periods"], 0)
        self.assertIsNone(ic_summary([])["mean"])

    def test_single_period_has_no_dispersion(self):
        summary = ic_summary([0.1])
        self.assertEqual(summary["periods"], 1)
        self.assertIsNone(summary["std"])
        self.assertIsNone(summary["t_stat"])


class BucketTests(unittest.TestCase):
    def setUp(self):
        # Higher score genuinely predicts higher return.
        self.scores = list(range(100))
        self.returns = [x * 0.5 for x in range(100)]

    def test_bucket_one_holds_the_highest_scores(self):
        frame = bucket_returns(self.scores, self.returns, buckets=5)
        top = frame.sort_values("bucket").iloc[0]
        bottom = frame.sort_values("bucket").iloc[-1]
        self.assertGreater(top["mean_return_pct"], bottom["mean_return_pct"])

    def test_buckets_are_evenly_populated(self):
        frame = bucket_returns(self.scores, self.returns, buckets=5)
        self.assertEqual(set(frame["count"]), {20})

    def test_spread_is_top_minus_bottom(self):
        frame = bucket_returns(self.scores, self.returns, buckets=5)
        self.assertGreater(bucket_spread(frame), 0)

    def test_monotonicity_is_one_for_a_perfect_ladder(self):
        frame = bucket_returns(self.scores, self.returns, buckets=5)
        self.assertAlmostEqual(monotonicity(frame), 1.0)

    def test_monotonicity_is_negative_when_inverted(self):
        frame = bucket_returns(self.scores, self.returns[::-1], buckets=5)
        self.assertAlmostEqual(monotonicity(frame), -1.0)

    def test_monotonicity_near_zero_when_score_is_uninformative(self):
        rng = np.random.default_rng(11)
        frame = bucket_returns(
            list(range(400)), rng.normal(size=400).tolist(), buckets=10
        )
        self.assertLess(abs(monotonicity(frame)), 0.85)

    def test_skewed_scores_still_divide_the_population_evenly(self):
        scores = [x**4 for x in range(100)]
        frame = bucket_returns(scores, self.returns, buckets=4)
        self.assertEqual(set(frame["count"]), {25})

    def test_too_few_rows_returns_none(self):
        self.assertIsNone(bucket_returns([1, 2], [1, 2], buckets=10))

    def test_spread_of_none_is_none(self):
        self.assertIsNone(bucket_spread(None))


class TurnoverTests(unittest.TestCase):
    def test_identical_portfolios_have_zero_turnover(self):
        weights = {"A": 0.5, "B": 0.5}
        self.assertAlmostEqual(turnover(weights, weights), 0.0)

    def test_full_replacement_is_one(self):
        self.assertAlmostEqual(
            turnover({"A": 0.5, "B": 0.5}, {"C": 0.5, "D": 0.5}), 1.0
        )

    def test_three_of_five_replaced(self):
        """The p0.md worked example: A,B,C,D,E -> A,B,F,G,H."""
        before = {k: 0.2 for k in "ABCDE"}
        after = {k: 0.2 for k in "ABFGH"}
        self.assertAlmostEqual(turnover(before, after), 0.6)

    def test_empty_to_empty_is_zero(self):
        self.assertAlmostEqual(turnover({}, {}), 0.0)

    def test_initial_build_is_full_turnover(self):
        self.assertAlmostEqual(turnover({}, {"A": 1.0}), 0.5)


class DrawdownTests(unittest.TestCase):
    def test_monotonic_growth_has_no_drawdown(self):
        self.assertAlmostEqual(max_drawdown([1.0, 1.1, 1.2]), 0.0)

    def test_halving_from_peak_is_minus_fifty_percent(self):
        self.assertAlmostEqual(max_drawdown([1.0, 2.0, 1.0]), -0.5)

    def test_drawdown_is_measured_from_the_running_peak(self):
        self.assertAlmostEqual(max_drawdown([1.0, 2.0, 1.5, 3.0, 2.4]), -0.25)

    def test_empty_curve_is_none(self):
        self.assertIsNone(max_drawdown([]))


class PortfolioMetricsTests(unittest.TestCase):
    def test_compounding_produces_the_expected_curve(self):
        curve = equity_curve([10.0, 10.0])
        self.assertAlmostEqual(float(curve.iloc[-1]), 1.21)

    def test_twelve_one_percent_months_annualise_near_twelve_point_seven(self):
        metrics = portfolio_metrics([1.0] * 12, periods_per_year=12)
        self.assertAlmostEqual(metrics["cagr_pct"], 12.6825, places=3)

    def test_hit_rate_counts_positive_periods(self):
        metrics = portfolio_metrics([1.0, -1.0, 2.0, -2.0], periods_per_year=12)
        self.assertAlmostEqual(metrics["hit_rate_pct"], 50.0)

    def test_drawdown_is_reported_as_a_percentage(self):
        metrics = portfolio_metrics([50.0, -50.0], periods_per_year=12)
        self.assertAlmostEqual(metrics["max_drawdown_pct"], -50.0)

    def test_constant_returns_have_no_volatility_and_no_sharpe(self):
        metrics = portfolio_metrics([1.0] * 6, periods_per_year=12)
        self.assertAlmostEqual(metrics["volatility_ann_pct"], 0.0)
        self.assertIsNone(metrics["sharpe"])

    def test_empty_input_is_safe(self):
        self.assertEqual(portfolio_metrics([])["periods"], 0)


class ExcessMetricsTests(unittest.TestCase):
    def test_beating_the_benchmark_every_period(self):
        metrics = excess_metrics([2.0, 3.0, 4.0], [1.0, 1.0, 1.0])
        self.assertAlmostEqual(metrics["mean_excess_pct"], 2.0)
        self.assertAlmostEqual(metrics["periods_beaten_share"], 1.0)

    def test_matching_the_benchmark_gives_no_excess(self):
        metrics = excess_metrics([1.0, 2.0], [1.0, 2.0])
        self.assertAlmostEqual(metrics["mean_excess_pct"], 0.0)
        self.assertAlmostEqual(metrics["periods_beaten_share"], 0.0)

    def test_a_higher_mean_with_erratic_excess_scores_a_lower_ir(self):
        """Same mean excess, different consistency: the steady one wins on IR."""
        steady = excess_metrics(
            [3.1, 2.9, 3.0, 3.2, 2.8, 3.0, 3.1, 2.9], [1.0] * 8
        )
        erratic = excess_metrics([11.0, -5.0] * 4, [1.0] * 8)
        self.assertAlmostEqual(
            steady["mean_excess_pct"], erratic["mean_excess_pct"], places=6
        )
        self.assertGreater(steady["information_ratio"], erratic["information_ratio"])

    def test_a_constant_excess_has_no_defined_information_ratio(self):
        """Zero tracking error makes the ratio undefined, not enormous."""
        metrics = excess_metrics([2.0] * 8, [1.0] * 8)
        self.assertAlmostEqual(metrics["mean_excess_pct"], 1.0)
        self.assertIsNone(metrics["information_ratio"])

    def test_mismatched_lengths_align_on_the_shorter(self):
        metrics = excess_metrics([1.0, 2.0, 3.0], [1.0, 1.0])
        self.assertEqual(metrics["periods"], 2)

    def test_empty_input_is_safe(self):
        self.assertEqual(excess_metrics([], [])["periods"], 0)


if __name__ == "__main__":
    unittest.main()
