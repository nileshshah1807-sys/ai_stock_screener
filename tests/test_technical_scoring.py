import unittest

import pandas as pd

from app import TechnicalEnhancer, sort_by_recommendation


class TechnicalScoringTests(unittest.TestCase):
    def test_rsi_handles_zero_losses_as_overbought(self):
        close = pd.Series(range(1, 31), dtype=float)

        rsi = TechnicalEnhancer._rsi(close, 14)

        self.assertEqual(rsi.iloc[-1], 100.0)

    def test_stoch_rsi_returns_smoothed_percent_k(self):
        close = pd.Series([100, 102, 101, 104, 103, 106, 105, 108, 107, 110] * 5, dtype=float)

        stoch_rsi = TechnicalEnhancer.calculate_stoch_rsi(close, 14, 3)

        self.assertGreaterEqual(stoch_rsi, 0.0)
        self.assertLessEqual(stoch_rsi, 100.0)

    def test_recommendation_order_places_strong_buy_before_buy(self):
        stock_rows = pd.DataFrame([
            {"Symbol": "BUY_HIGHER_SCORE", "Rating": "BUY", "Final_Score": 85.0},
            {"Symbol": "STRONG_BUY", "Rating": "STRONG BUY", "Final_Score": 75.0},
        ])

        ordered = sort_by_recommendation(stock_rows, "Final_Score")

        self.assertEqual(ordered.iloc[0]["Symbol"], "STRONG_BUY")


if __name__ == "__main__":
    unittest.main()