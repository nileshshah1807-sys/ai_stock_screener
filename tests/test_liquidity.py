import unittest
from types import SimpleNamespace

import pandas as pd

from screener.data_collection import StockDataCollector, calculate_liquidity_metrics
from screener.liquidity import LiquidityQualityEnricher
from screener.scoring import score_fundamentals
from scoring.transcript_enricher import rank_actionable_recommendations


class LiquidityMetricTests(unittest.TestCase):
    def test_turnover_uses_each_days_close_and_robust_windows(self):
        prices = pd.DataFrame({
            "Close": [100.0] * 59 + [1_000.0],
            "Volume": [100_000.0] * 60,
        })

        result = calculate_liquidity_metrics(prices)

        self.assertEqual(result["Avg_Turnover_INR"], 11_500_000.0)
        self.assertEqual(result["Median_Turnover_20D_INR"], 10_000_000.0)
        self.assertEqual(result["Turnover_P10_20D_INR"], 10_000_000.0)
        self.assertGreater(result["Turnover_Top5_Share_60D"], 0.20)

    def test_strong_buy_is_capped_for_thin_or_spike_dominated_turnover(self):
        source = pd.DataFrame({
            "Symbol": ["LIQUID", "THIN", "SPIKY", "THIN_BUY"],
            "Rating": ["STRONG BUY", "STRONG BUY", "STRONG BUY", "BUY"],
            "Final_Score": [75.0, 80.0, 78.0, 68.0],
            "Median_Turnover_20D_INR": [80_000_000, 20_000_000, 80_000_000, 10_000_000],
            "Median_Turnover_60D_INR": [75_000_000, 18_000_000, 40_000_000, 9_000_000],
            "Turnover_P10_20D_INR": [50_000_000, 5_000_000, 20_000_000, 2_000_000],
            "Turnover_Top5_Share_60D": [0.30, 0.35, 0.70, 0.40],
        })

        result = LiquidityQualityEnricher(SimpleNamespace()).enrich(source)

        self.assertEqual(result["Rating"].tolist(), ["STRONG BUY", "BUY", "BUY", "BUY"])
        self.assertEqual(
            result["Liquidity_Status"].tolist(),
            ["Liquid", "Thin", "Spike-concentrated", "Thin"],
        )
        self.assertEqual(result["Final_Score"].tolist(), source["Final_Score"].tolist())
        self.assertEqual(result.loc[0, "Liquidity_Suggested_Max_Position_INR"], 800_000)
        self.assertIn("below", result.loc[1, "Liquidity_Cap_Reason"])
        self.assertIn("top 5 days", result.loc[2, "Liquidity_Cap_Reason"])
        self.assertFalse(result.loc[3, "Liquidity_Rating_Capped"])

    def test_missing_liquidity_cannot_retain_high_conviction_label(self):
        source = pd.DataFrame({
            "Symbol": ["UNKNOWN"],
            "Rating": ["STRONG BUY"],
            "Final_Score": [75.0],
        })

        result = LiquidityQualityEnricher(SimpleNamespace()).enrich(source)

        self.assertEqual(result.loc[0, "Rating"], "BUY")
        self.assertEqual(result.loc[0, "Liquidity_Status"], "Unknown")

    def test_actionable_liquid_buy_ranks_before_higher_scoring_thin_buy(self):
        source = pd.DataFrame({
            "Symbol": ["THIN", "LIQUID"],
            "Rating": ["BUY", "BUY"],
            "Final_Score": [85.0, 70.0],
            "Liquidity_Conviction_Eligible": [False, True],
            "Transcript_Priority_Applied": [False, False],
        })

        ranked = rank_actionable_recommendations(source)

        self.assertEqual(ranked["Symbol"].tolist(), ["LIQUID", "THIN"])


class DividendUnitTests(unittest.TestCase):
    def test_yahoo_percentage_yield_is_converted_to_ratio_for_scoring(self):
        prepared = StockDataCollector._prepare_fundamental_frame([
            {"Symbol": "TCS", "Dividend_Yield": 2.74},
        ])

        self.assertAlmostEqual(prepared.loc[0, "Dividend_Yield_Ratio"], 0.0274)
        self.assertEqual(prepared.loc[0, "Dividend_Yield"], 2.74)
        components = score_fundamentals(prepared.loc[0], return_components=True)
        self.assertEqual(components["DY"], 4.0)

    def test_legacy_ratio_input_remains_supported_without_unit_column(self):
        components = score_fundamentals(
            pd.Series({"Dividend_Yield": 0.03}),
            return_components=True,
        )

        self.assertEqual(components["DY"], 5.0)


if __name__ == "__main__":
    unittest.main()
