import unittest
from types import SimpleNamespace

import pandas as pd

from screener.data_collection import StockDataCollector, calculate_liquidity_metrics
from screener.liquidity import (
    LiquidityQualityEnricher,
    NSELiquidityProvider,
    filter_execution_universe,
)
from screener.scoring import score_fundamentals
from scoring.transcript_enricher import rank_actionable_recommendations


class LiquidityMetricTests(unittest.TestCase):
    def test_turnover_uses_each_days_close_and_robust_windows(self):
        prices = pd.DataFrame({
            "High": [101.0] * 59 + [1_001.0],
            "Low": [99.0] * 59 + [999.0],
            "Close": [100.0] * 59 + [1_000.0],
            "Volume": [100_000.0] * 60,
        })

        result = calculate_liquidity_metrics(prices)

        self.assertEqual(result["Avg_Turnover_INR"], 11_500_000.0)
        self.assertEqual(result["Median_Turnover_20D_INR"], 10_000_000.0)
        self.assertEqual(result["Turnover_P10_20D_INR"], 10_000_000.0)
        self.assertGreater(result["Turnover_Top5_Share_60D"], 0.20)
        self.assertEqual(result["Trading_Frequency_60D"], 1.0)

    def test_zero_volume_sessions_reduce_frequency_and_are_not_discarded(self):
        prices = pd.DataFrame({
            "High": [101.0] * 60,
            "Low": [99.0] * 60,
            "Close": [100.0] * 60,
            "Volume": [100_000.0] * 48 + [0.0] * 12,
        })

        result = calculate_liquidity_metrics(prices)

        self.assertEqual(result["Trading_Frequency_60D"], 0.8)
        self.assertEqual(result["Turnover_Observations"], 60)
        self.assertEqual(result["Turnover_P10_20D_INR"], 0.0)

    def test_cmf_demand_proxy_is_descriptive(self):
        prices = pd.DataFrame({
            "High": [102.0 + i for i in range(60)],
            "Low": [98.0 + i for i in range(60)],
            "Close": [101.5 + i for i in range(60)],
            "Volume": [100_000.0] * 60,
        })

        result = calculate_liquidity_metrics(prices)

        self.assertGreater(result["CMF_21"], 0)
        self.assertGreater(result["Price_Return_20D_Pct"], 0)
        self.assertEqual(result["Demand_Proxy_Status"], "Accumulation proxy")

    def test_turnover_uses_raw_close_but_return_uses_split_adjusted_close(self):
        prices = pd.DataFrame({
            "High": [202.0] * 39 + [102.0] * 21,
            "Low": [198.0] * 39 + [98.0] * 21,
            "Close": [200.0] * 39 + [100.0] * 21,
            "Adj Close": [100.0] * 60,
            "Volume": [100_000.0] * 60,
        })

        result = calculate_liquidity_metrics(prices)

        self.assertEqual(result["Median_Turnover_20D_INR"], 10_000_000.0)
        self.assertEqual(result["Price_Return_20D_Pct"], 0.0)

    def test_liquidity_never_rewrites_investment_rating(self):
        source = pd.DataFrame({
            "Symbol": ["GROUP1", "GROUP2", "PROXY"],
            "Rating": ["STRONG BUY", "STRONG BUY", "BUY"],
            "Final_Score": [75.0, 80.0, 68.0],
            "Median_Turnover_20D_INR": [20_000_000, 80_000_000, 20_000_000],
            "Median_Turnover_60D_INR": [18_000_000, 75_000_000, 18_000_000],
            "Turnover_P10_20D_INR": [5_000_000, 50_000_000, 5_000_000],
            "Turnover_Top5_Share_60D": [0.70, 0.30, 0.30],
            "Trading_Frequency_60D": [1.0, 1.0, 1.0],
            "NSE_Liquidity_Category": [1, 2, None],
            "NSE_Impact_Cost_Pct": [0.30, 1.40, None],
        })

        result = LiquidityQualityEnricher(SimpleNamespace()).enrich(source)

        self.assertEqual(result["Rating"].tolist(), source["Rating"].tolist())
        self.assertEqual(result["Investment_Rating"].tolist(), source["Rating"].tolist())
        self.assertEqual(result["Final_Score"].tolist(), source["Final_Score"].tolist())
        self.assertEqual(result["Liquidity_Grade"].tolist(), [
            "Group I - liquid", "Group II - less liquid", "Proxy only",
        ])
        self.assertEqual(result["Portfolio_Actionable"].tolist(), [True, False, True])
        self.assertIn("NSE Rs1 lakh", result.loc[0, "Portfolio_Actionability"])
        self.assertIn("Restricted", result.loc[1, "Portfolio_Actionability"])
        self.assertIn("NSE monthly", result.loc[0, "Liquidity_Methodology"])
        self.assertFalse(result["Liquidity_Rating_Capped"].any())

    def test_larger_target_uses_position_sized_turnover_proxy(self):
        source = pd.DataFrame({
            "Symbol": ["SMALL"],
            "Rating": ["STRONG BUY"],
            "Final_Score": [75.0],
            "Median_Turnover_20D_INR": [20_000_000],
            "Median_Turnover_60D_INR": [18_000_000],
            "Turnover_P10_20D_INR": [5_000_000],
            "Turnover_Top5_Share_60D": [0.30],
            "Trading_Frequency_60D": [1.0],
            "NSE_Liquidity_Category": [1],
        })

        result = LiquidityQualityEnricher(SimpleNamespace(
            PORTFOLIO_TARGET_POSITION_INR=500_000,
            LIQUIDITY_POSITION_PARTICIPATION_RATE=0.01,
        )).enrich(source)

        self.assertEqual(result.loc[0, "Rating"], "STRONG BUY")
        self.assertFalse(result.loc[0, "Portfolio_Actionable"])
        self.assertEqual(result.loc[0, "Portfolio_Estimated_Build_Days"], 3)
        self.assertIn("3 trading days", result.loc[0, "Portfolio_Actionability"])

    def test_group_one_without_impact_cost_needs_turnover_evidence(self):
        source = pd.DataFrame({
            "Symbol": ["NEWLY_LISTED"],
            "Rating": ["BUY"],
            "Final_Score": [70.0],
            "Median_Turnover_20D_INR": [2_000_000],
            "Median_Turnover_60D_INR": [2_000_000],
            "Turnover_P10_20D_INR": [500_000],
            "Turnover_Top5_Share_60D": [0.30],
            "Trading_Frequency_60D": [1.0],
            "NSE_Liquidity_Category": [1],
            "NSE_Impact_Cost_Pct": [None],
        })

        result = LiquidityQualityEnricher(SimpleNamespace()).enrich(source)

        self.assertFalse(result.loc[0, "Portfolio_Actionable"])
        self.assertIn("5 trading days", result.loc[0, "Portfolio_Actionability"])

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
        self.assertEqual(ranked["Actionable_Rank"].tolist(), [1, 2])
        self.assertEqual(ranked.set_index("Symbol").loc["THIN", "Investment_Rank"], 1)
        self.assertEqual(ranked.set_index("Symbol").loc["LIQUID", "Investment_Rank"], 2)

    def test_universe_uses_nse_group_before_absolute_turnover(self):
        source = pd.DataFrame({
            "Symbol": ["SMALL_GROUP1", "LARGE_GROUP2", "NO_CATEGORY_OK", "NO_CATEGORY_THIN"],
            "Current_Price": [100.0] * 4,
            "Avg_Turnover_INR": [1_000_000, 100_000_000, 8_000_000, 1_000_000],
            "Median_Turnover_20D_INR": [1_000_000, 100_000_000, 8_000_000, 1_000_000],
            "NSE_Liquidity_Category": [1, 2, None, None],
        })

        result = filter_execution_universe(source, SimpleNamespace())

        self.assertEqual(result["Symbol"].tolist(), ["SMALL_GROUP1", "NO_CATEGORY_OK"])


class NSELiquidityProviderTests(unittest.TestCase):
    def test_official_file_parser_keeps_eq_and_exposes_impact_cost(self):
        rows = ["10,AUG,2026,000501"]
        rows.extend(
            f"20,SYM{index},EQ,INE{index:09d},1,0.25"
            for index in range(501)
        )
        rows.append("20,SYM0,BE,INE000000000,3,")

        parsed = NSELiquidityProvider._parse_file(
            "\n".join(rows),
            "https://nsearchives.nseindia.com/content/nsccl/C_CATG_AUG2026.T01",
            "2026-08-03",
        )

        self.assertEqual(len(parsed), 501)
        self.assertEqual(parsed.loc[0, "Symbol"], "SYM0")
        self.assertEqual(parsed.loc[0, "NSE_Liquidity_Category"], 1)
        self.assertEqual(parsed.loc[0, "NSE_Impact_Cost_Pct"], 0.25)
        self.assertEqual(parsed.loc[0, "NSE_Liquidity_Group"], "Group I - liquid")


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
