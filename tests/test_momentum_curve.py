"""Momentum must never rank a strong advance below a flat or falling stock.

The original curve peaked at +5..15% one-month return and then fell away:
+48% scored 7.21, a flat stock scored 8.00, and a stock down 5% scored 6.00.
SBCL was ranked 770 in the 2026-08-11 run partly because it had gone up too
much. Extension risk is legitimate, but RSI, StochRSI, Bollinger position and
ATR already spend 40 of the 132 technical points on it; the momentum component
discounting it a fifth time made a breakout structurally unrankable.
"""

import unittest

from screener.scoring import TECH_COMPONENT_MAX, StockScorer


def momentum_points(pct_1m):
    row = {"Pct_Change_1M": pct_1m}
    return StockScorer.technical_score_details(row)["components"]["MOM"]


class MomentumCurveTests(unittest.TestCase):
    def test_curve_is_monotonically_non_decreasing(self):
        previous = None
        value = -60.0
        while value <= 150.0:
            points = momentum_points(value)
            if previous is not None:
                self.assertGreaterEqual(
                    points, previous[1] - 1e-9,
                    f"momentum fell from {previous[1]} at {previous[0]}% to "
                    f"{points} at {value}% -- a larger gain scored worse",
                )
            previous = (value, points)
            value += 0.5

    def test_a_strong_advance_never_scores_below_a_flat_or_falling_stock(self):
        flat = momentum_points(0.0)
        falling = momentum_points(-5.0)
        for gain in (25.0, 40.0, 47.92, 80.0, 120.0):
            with self.subTest(gain=gain):
                self.assertGreater(momentum_points(gain), flat)
                self.assertGreater(momentum_points(gain), falling)

    def test_the_regression_case_now_earns_full_marks(self):
        # SBCL's one-month return in the 2026-08-11 validation run.
        self.assertEqual(momentum_points(47.92), TECH_COMPONENT_MAX["MOM"])

    def test_losses_are_still_penalised(self):
        self.assertLess(momentum_points(-30.0), momentum_points(-10.0))
        self.assertLess(momentum_points(-10.0), momentum_points(0.0))

    def test_component_never_exceeds_its_declared_capacity(self):
        for value in (-100.0, -30.0, 0.0, 25.0, 80.0, 500.0):
            with self.subTest(value=value):
                points = momentum_points(value)
                self.assertGreaterEqual(points, 0.0)
                self.assertLessEqual(points, TECH_COMPONENT_MAX["MOM"])

    def test_extreme_gains_saturate_rather_than_grow_without_limit(self):
        """The defensible half of short-term reversal: cap, don't invert."""

        self.assertEqual(momentum_points(25.0), momentum_points(500.0))

    def test_missing_return_leaves_the_component_unobserved(self):
        components = StockScorer.technical_score_details({})["components"]
        self.assertIsNone(components["MOM"])


if __name__ == "__main__":
    unittest.main()
