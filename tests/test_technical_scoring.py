import unittest
import tempfile
from pathlib import Path

import pandas as pd

from app import StockScorer, TechnicalEnhancer, sort_by_recommendation
from screener.market_data import PriceCache
from screener.scoring import sector_relative_fund_scores


class TechnicalScoringTests(unittest.TestCase):
    @staticmethod
    def _high_scoring_stock(**overrides):
        stock = {
            "Symbol": "HEALTHY",
            "Sector": "Technology",
            "PE_Ratio": 10.0,
            "PB_Ratio": 1.5,
            "ROE": 0.30,
            "ROA": 0.10,
            "Debt_to_Equity": 10.0,
            "Current_Ratio": 2.0,
            "Profit_Margin": 0.25,
            "Revenue_Growth": 0.25,
            "Earnings_Growth": 0.30,
            "Dividend_Yield": 0.03,
            "EV_EBITDA": 8.0,
            "Current_Price": 110.0,
            "MA20": 100.0,
            "MA50": 100.0,
            "MA50_Slope_Pct": 4.0,
            "RSI_14": 55.0,
            "MACD": 1.0,
            "MACD_Signal": 0.0,
            "ADX_14": 35.0,
            "ADX_Plus_DI": 30.0,
            "ADX_Minus_DI": 10.0,
            "StochRSI_14": 60.0,
            "ATR_14": 2.0,
            "Pct_Change_1M": 8.0,
            "Pct_Change_3M": 12.0,
            "Vol_Ratio": 1.5,
            "BB_Position": 0.6,
        }
        stock.update(overrides)
        return pd.DataFrame([stock])

    def test_rsi_handles_zero_losses_as_overbought(self):
        close = pd.Series(range(1, 31), dtype=float)

        rsi = TechnicalEnhancer._rsi(close, 14)

        self.assertEqual(rsi.iloc[-1], 100.0)

    def test_stoch_rsi_returns_smoothed_percent_k(self):
        close = pd.Series([100, 102, 101, 104, 103, 106, 105, 108, 107, 110] * 5, dtype=float)

        stoch_rsi = TechnicalEnhancer.calculate_stoch_rsi(close, 14, 3)

        self.assertGreaterEqual(stoch_rsi, 0.0)
        self.assertLessEqual(stoch_rsi, 100.0)

    def test_sector_relative_scores_are_symmetric_for_metric_direction(self):
        peers = pd.DataFrame({
            "Sector": ["Technology"] * 5,
            "PE_Ratio": [10, 20, 30, 40, 50],
            "ROE": [0.10, 0.15, 0.20, 0.25, 0.30],
        })

        scores = sector_relative_fund_scores(peers, min_peers=5)

        self.assertEqual(scores.loc[0, "PE_Ratio"], 15.0)
        self.assertEqual(scores.loc[4, "PE_Ratio"], 0.0)
        self.assertEqual(scores.loc[0, "ROE"], 0.0)
        self.assertEqual(scores.loc[4, "ROE"], 15.0)

    def test_missing_reported_roe_uses_auditable_eps_to_book_proxy(self):
        stock = self._high_scoring_stock(
            ROE=None,
            EPS=20.0,
            Book_Value=100.0,
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "ROE_Source"], "eps_to_book_proxy")
        self.assertEqual(scored.loc[0, "ROE"], 0.2)
        self.assertEqual(scored.loc[0, "Fund_Component_ROE"], 15.0)

    def test_price_cache_rejects_old_indicator_math(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "price_cache.csv"
            row = {column: 1 for column in PriceCache.REQUIRED_COLUMNS}
            row["Technical_Indicator_Version"] = TechnicalEnhancer.INDICATOR_VERSION - 1
            pd.DataFrame([row]).to_csv(path, index=False)

            cached = PriceCache.load(path, max_age_hours=1)

        self.assertTrue(cached.empty)

    def test_recommendation_order_places_strong_buy_before_buy(self):
        stock_rows = pd.DataFrame([
            {"Symbol": "BUY_HIGHER_SCORE", "Rating": "BUY", "Final_Score": 85.0},
            {"Symbol": "STRONG_BUY", "Rating": "STRONG BUY", "Final_Score": 75.0},
        ])

        ordered = sort_by_recommendation(stock_rows, "Final_Score")

        self.assertEqual(ordered.iloc[0]["Symbol"], "STRONG_BUY")

    def test_falling_ma50_caps_expleo_pattern_at_hold(self):
        stock = self._high_scoring_stock(
            Symbol="EXPLEOSOL",
            Current_Price=821.0,
            MA20=810.0,
            MA50=800.0,
            MA50_Slope_Pct=-1.4,
            Pct_Change_3M=11.9,
            ADX_14=37.4,
            ADX_Plus_DI=36.8,
            ADX_Minus_DI=6.9,
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertGreater(scored.loc[0, "Combined_Score"], 60.0)
        self.assertEqual(scored.loc[0, "Rating"], "HOLD")
        self.assertFalse(scored.loc[0, "Buy_Eligible"])
        self.assertIn("MA50 falling", scored.loc[0, "Rating_Cap_Reason"])

    def test_negative_medium_term_return_caps_mhlxmiru_pattern_at_hold(self):
        stock = self._high_scoring_stock(
            Symbol="MHLXMIRU",
            Current_Price=161.0,
            MA20=155.0,
            MA50=150.0,
            MA50_Slope_Pct=-9.3,
            Pct_Change_3M=-13.3,
            ADX_14=27.2,
            ADX_Plus_DI=35.6,
            ADX_Minus_DI=20.2,
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertGreater(scored.loc[0, "Combined_Score"], 60.0)
        self.assertEqual(scored.loc[0, "Rating"], "HOLD")
        self.assertIn("MA50 falling", scored.loc[0, "Buy_Gate_Reason"])
        self.assertIn("3M return not positive", scored.loc[0, "Buy_Gate_Reason"])

    def test_stale_fundamental_fallback_cannot_receive_buy(self):
        stock = self._high_scoring_stock(Fund_Data_Stale=True)

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Rating"], "HOLD")
        self.assertIn("stale fundamental fallback", scored.loc[0, "Rating_Cap_Reason"])

    def test_financial_services_uses_sector_specific_equity_model(self):
        stock = pd.DataFrame([{
            "Symbol": "BANK",
            "Sector": "Financial Services",
            "Industry": "Banks - Regional",
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

        self.assertEqual(scored.loc[0, "Fundamental_Model"], "Bank Equity Quality Model")
        self.assertFalse(scored.loc[0, "Rating_Capped"])
        self.assertFalse(scored.loc[0, "Specialized_Fundamental_Model_Required"])
        self.assertFalse(scored.loc[0, "Specialized_Quality_Eligible"])
        self.assertEqual(scored.loc[0, "Rating"], "BUY")
        self.assertIn("Gross_NPA", scored.loc[0, "Specialized_Quality_Gate_Reason"])

    def test_bank_can_only_be_strong_buy_with_acceptable_risk_data(self):
        stock = self._high_scoring_stock(
            Symbol="GOODBANK",
            Sector="Financial Services",
            Industry="Banks - Regional",
            Gross_NPA=0.025,
            Net_NPA=0.008,
            Capital_Adequacy=0.16,
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Rating"], "STRONG BUY")
        self.assertTrue(scored.loc[0, "Specialized_Quality_Eligible"])
        self.assertEqual(scored.loc[0, "Specialized_Quality_Gate_Reason"], "passed")

    def test_bad_bank_asset_quality_blocks_strong_buy(self):
        stock = self._high_scoring_stock(
            Symbol="RISKYBANK",
            Sector="Financial Services",
            Industry="Banks - Regional",
            Gross_NPA=9.2,
            Net_NPA=4.5,
            Capital_Adequacy=11.0,
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Rating"], "BUY")
        self.assertFalse(scored.loc[0, "Specialized_Quality_Eligible"])
        self.assertIn("Gross NPA", scored.loc[0, "Strong_Buy_Gate_Reason"])

    def test_low_bank_pb_without_roe_gets_no_valuation_credit(self):
        stock = self._high_scoring_stock(
            Symbol="CHEAPBANK",
            Sector="Financial Services",
            Industry="Banks - Regional",
            PB_Ratio=0.7,
            ROE=float("nan"),
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Fund_Component_PB_ROE"], 0.0)
        self.assertIn("Val ", scored.loc[0, "Fund_Component_Summary"])

    def test_one_off_financial_growth_blocks_strong_buy(self):
        stock = self._high_scoring_stock(
            Symbol="BROKER",
            Sector="Financial Services",
            Industry="Capital Markets",
            Earnings_Growth=4.61,
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertNotEqual(scored.loc[0, "Rating"], "STRONG BUY")
        self.assertTrue(scored.loc[0, "Fundamental_Anomaly"])
        self.assertIn("extreme earnings growth", scored.loc[0, "Strong_Buy_Gate_Reason"])

    def test_multiple_extreme_fundamental_values_cap_rating_at_hold(self):
        stock = self._high_scoring_stock(
            Symbol="OUTLIER",
            PE_Ratio=0.5,
            ROE=1.2,
            Profit_Margin=1.5,
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Rating"], "HOLD")
        self.assertTrue(scored.loc[0, "Rating_Capped"])
        self.assertIn("multiple fundamental data anomalies", scored.loc[0, "Rating_Cap_Reason"])

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
