import unittest

import pandas as pd

from app import StockScorer, TechnicalEnhancer, sort_by_recommendation


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

    def test_financial_services_uses_sector_specific_equity_model(self):
        stock = pd.DataFrame([{
            "Symbol": "BANK",
            "Sector": "Financial Services",
            "PE_Ratio": 14.0,
            "PB_Ratio": 1.5,
            "ROE": 0.30,
            "ROA": 0.10,
            "Debt_to_Equity": 20.0,
            "Current_Ratio": 2.0,
            "Profit_Margin": 0.25,
            "Revenue_Growth": 0.25,
            "Earnings_Growth": 0.30,
            "Dividend_Yield": 0.04,
            "EV_EBITDA": 8.0,
            "Current_Price": 110.0,
            "MA20": 100.0,
            "MA50": 100.0,
            "MA50_Slope_Pct": 4.0,
            "RSI_14": 50.0,
            "MACD": 1.0,
            "MACD_Signal": 0.0,
            "ADX_14": 41.0,
            "ADX_Plus_DI": 30.0,
            "ADX_Minus_DI": 10.0,
            "StochRSI_14": 15.0,
            "ATR_14": 0.5,
            "Pct_Change_1M": 10.0,
            "Pct_Change_3M": 12.0,
            "Vol_Ratio": 2.1,
            "BB_Position": 0.2,
        }])

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Fundamental_Model"], "Financial Services Equity Model")
        self.assertFalse(scored.loc[0, "Rating_Capped"])
        self.assertFalse(scored.loc[0, "Specialized_Fundamental_Model_Required"])

    def test_real_estate_uses_sector_specific_asset_model(self):
        stock = pd.DataFrame([{
            "Symbol": "PROPERTY",
            "Sector": "Real Estate",
            "PE_Ratio": 20.0,
            "PB_Ratio": 2.0,
            "Debt_to_Equity": 60.0,
            "Current_Ratio": 1.5,
            "Profit_Margin": 0.18,
            "Revenue_Growth": 0.12,
            "Earnings_Growth": 0.15,
            "Current_Price": 110.0,
            "MA20": 100.0,
            "MA50": 100.0,
            "MA50_Slope_Pct": 4.0,
            "RSI_14": 50.0,
            "MACD": 1.0,
            "MACD_Signal": 0.0,
            "ADX_14": 41.0,
            "ADX_Plus_DI": 30.0,
            "ADX_Minus_DI": 10.0,
            "StochRSI_14": 15.0,
            "ATR_14": 0.5,
            "Pct_Change_1M": 10.0,
            "Pct_Change_3M": 12.0,
            "Vol_Ratio": 2.1,
            "BB_Position": 0.2,
        }])

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Fundamental_Model"], "Real Estate Asset Model")
        self.assertFalse(scored.loc[0, "Specialized_Fundamental_Model_Required"])


if __name__ == "__main__":
    unittest.main()