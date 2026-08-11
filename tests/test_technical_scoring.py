import unittest
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from app import StockScorer, TechnicalEnhancer, sort_by_recommendation
from screener.market_data import BacktestEngine, PriceCache
from screener.scoring import score_fundamentals, sector_relative_fund_scores


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
            "Technical_Price": 110.0,
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
            "CMF_21": 0.15,
            "Price_Return_20D_Pct": 8.0,
            "Demand_Proxy_Status": "Accumulation proxy",
            "BB_Position": 0.6,
        }
        if "Current_Price" in overrides and "Technical_Price" not in overrides:
            overrides["Technical_Price"] = overrides["Current_Price"]
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

    def test_indicator_failures_are_missing_but_legitimate_zero_is_preserved(self):
        short = pd.Series([100.0, 101.0, 102.0])

        adx, plus_di, minus_di = TechnicalEnhancer.calculate_adx(
            short, short, short, 14
        )

        self.assertTrue(np.isnan(adx))
        self.assertTrue(np.isnan(plus_di))
        self.assertTrue(np.isnan(minus_di))
        self.assertTrue(np.isnan(TechnicalEnhancer.calculate_stoch_rsi(short, 14)))
        self.assertTrue(np.isnan(TechnicalEnhancer.calculate_atr(short, short, short, 14)))

        flat = pd.Series([100.0] * 60)
        adx, plus_di, minus_di = TechnicalEnhancer.calculate_adx(
            flat, flat, flat, 14
        )
        self.assertEqual((adx, plus_di, minus_di), (0.0, 0.0, 0.0))
        self.assertEqual(
            TechnicalEnhancer.calculate_atr(flat, flat, flat, 14), 0.0
        )

    def test_short_return_distinguishes_missing_history_from_zero_return(self):
        unchanged = pd.Series([100.0] * 22)

        self.assertEqual(
            TechnicalEnhancer.calculate_pct_return(unchanged, 21), 0.0
        )
        self.assertTrue(np.isnan(
            TechnicalEnhancer.calculate_pct_return(unchanged.iloc[:-1], 21)
        ))

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

    def test_nonpositive_multiples_cannot_win_sector_value_points(self):
        peers = pd.DataFrame(
            {
                "Sector": ["Technology"] * 5,
                "PE_Ratio": [-10.0, 5.0, 10.0, 20.0, 30.0],
                "PB_Ratio": [-1.0, 1.0, 2.0, 3.0, 4.0],
                "EV_EBITDA": [0.0, 5.0, 10.0, 15.0, 20.0],
            }
        )

        relative = sector_relative_fund_scores(peers, min_peers=2)
        components = score_fundamentals(
            peers.iloc[0], relative.iloc[0], return_components=True
        )

        self.assertTrue(pd.isna(relative.loc[0, "PE_Ratio"]))
        self.assertTrue(pd.isna(relative.loc[0, "PB_Ratio"]))
        self.assertTrue(pd.isna(relative.loc[0, "EV_EBITDA"]))
        self.assertEqual(components["PE"], 0.0)
        self.assertEqual(components["PB"], 0.0)
        self.assertEqual(components["EV"], 0.0)

    def test_unusable_extremes_cannot_move_fresh_sector_peer_scores(self):
        fresh = pd.concat(
            [
                self._high_scoring_stock(
                    Symbol=f"FRESH{position}",
                    PE_Ratio=pe,
                    Fundamental_Record_Available=True,
                    Fund_Data_Stale=False,
                )
                for position, pe in enumerate((10.0, 15.0, 20.0, 25.0, 30.0), 1)
            ],
            ignore_index=True,
        )
        excluded = pd.concat(
            [
                self._high_scoring_stock(
                    Symbol="STALE_EXTREME",
                    PE_Ratio=1_000.0,
                    Fund_Data_Stale=True,
                ),
                self._high_scoring_stock(
                    Symbol="UNAVAILABLE_EXTREME",
                    PE_Ratio=0.5,
                    Fundamental_Record_Available=False,
                ),
                self._high_scoring_stock(
                    Symbol="ANOMALOUS_EXTREME",
                    PE_Ratio=0.5,
                    ROE=1.2,
                    Profit_Margin=1.5,
                ),
            ],
            ignore_index=True,
        )

        baseline = StockScorer().score_all_stocks(fresh)
        challenged = StockScorer().score_all_stocks(
            pd.concat([fresh, excluded], ignore_index=True)
        )
        baseline_pe = baseline.set_index("Symbol")["Fund_Component_PE"]
        challenged_pe = challenged.set_index("Symbol")["Fund_Component_PE"]

        pd.testing.assert_series_equal(
            baseline_pe.sort_index(),
            challenged_pe.loc[baseline_pe.index].sort_index(),
        )
        challenged_by_symbol = challenged.set_index("Symbol")
        self.assertTrue(
            challenged_by_symbol.loc[baseline_pe.index, "Sector_Peer_Reference_Eligible"].all()
        )
        self.assertTrue(
            (~challenged_by_symbol.loc[excluded["Symbol"], "Sector_Peer_Reference_Eligible"]).all()
        )
        self.assertTrue(
            (challenged_by_symbol.loc[baseline_pe.index, "Sector_Peer_Reference_Count"] == 5).all()
        )

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

    def test_backtest_does_not_mix_model_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = BacktestEngine(directory, model_version="3.0.0")
            pd.DataFrame({
                "Rating": ["BUY", "BUY"],
                "Forward_Return_Pct": [100.0, 10.0],
                "Model_Version": ["2.2.0", "3.0.0"],
            }).to_csv(engine.history_file, index=False)

            result = engine.analyze_performance()

        self.assertEqual(result["BUY"]["observations"], 1)
        self.assertEqual(result["BUY"]["average_return_pct"], 10.0)

    def test_recommendation_order_places_strong_buy_before_buy(self):
        stock_rows = pd.DataFrame([
            {"Symbol": "BUY_HIGHER_SCORE", "Rating": "BUY", "Final_Score": 85.0},
            {"Symbol": "STRONG_BUY", "Rating": "STRONG BUY", "Final_Score": 75.0},
        ])

        ordered = sort_by_recommendation(stock_rows, "Final_Score")

        self.assertEqual(ordered.iloc[0]["Symbol"], "STRONG_BUY")

    def test_high_volume_distribution_is_not_rewarded_as_demand(self):
        accumulation = self._high_scoring_stock(
            Vol_Ratio=2.5,
            CMF_21=0.20,
            Price_Return_20D_Pct=12.0,
            Demand_Proxy_Status="Accumulation proxy",
        ).iloc[0]
        distribution = accumulation.copy()
        distribution["CMF_21"] = -0.20
        distribution["Price_Return_20D_Pct"] = -12.0
        distribution["Demand_Proxy_Status"] = "Distribution proxy"

        accumulation_detail = StockScorer.technical_score_details(accumulation)
        distribution_detail = StockScorer.technical_score_details(distribution)

        self.assertGreater(
            accumulation_detail["components"]["VOL"],
            distribution_detail["components"]["VOL"],
        )
        self.assertGreater(
            accumulation_detail["adjusted_score"],
            distribution_detail["adjusted_score"],
        )

    def test_demand_score_is_continuous_across_zero_category_boundary(self):
        negative = self._high_scoring_stock(
            CMF_21=-0.000001,
            Price_Return_20D_Pct=-0.000001,
            Vol_Ratio=2.0,
            Demand_Proxy_Status="Distribution proxy",
        ).iloc[0]
        positive = negative.copy()
        positive["CMF_21"] = 0.000001
        positive["Price_Return_20D_Pct"] = 0.000001
        positive["Demand_Proxy_Status"] = "Accumulation proxy"

        negative_points = StockScorer.technical_score_details(negative)["components"]["VOL"]
        positive_points = StockScorer.technical_score_details(positive)["components"]["VOL"]

        self.assertGreater(positive_points, negative_points)
        self.assertLess(positive_points - negative_points, 0.001)

    def test_demand_label_is_descriptive_not_a_scoring_input(self):
        first = self._high_scoring_stock(Demand_Proxy_Status="Accumulation proxy").iloc[0]
        second = first.copy()
        second["Demand_Proxy_Status"] = "Distribution proxy"

        first_detail = StockScorer.technical_score_details(first)
        second_detail = StockScorer.technical_score_details(second)

        self.assertEqual(
            first_detail["components"]["VOL"], second_detail["components"]["VOL"]
        )
        self.assertTrue(first_detail["demand_proxy_input_complete"])

    def test_missing_technicals_are_neutral_with_zero_coverage(self):
        details = StockScorer.technical_score_details(pd.Series(dtype=object))

        self.assertEqual(details["coverage"], 0.0)
        self.assertEqual(details["observed_score"], 50.0)
        self.assertEqual(details["adjusted_score"], 50.0)
        self.assertEqual(set(details["missing_components"]), set(details["components"]))

    def test_partial_technical_evidence_is_shrunk_toward_neutral(self):
        details = StockScorer.technical_score_details(pd.Series({"RSI_14": 50.0}))

        self.assertGreater(details["observed_score"], 50.0)
        self.assertGreater(details["adjusted_score"], 50.0)
        self.assertLess(details["adjusted_score"], details["observed_score"])
        self.assertAlmostEqual(
            details["coverage"],
            12.0 / StockScorer.MAX_TECH_SCORE,
        )

    def test_failed_indicator_reduces_coverage_instead_of_adding_neutral_points(self):
        complete = self._high_scoring_stock().iloc[0]
        missing = complete.copy()
        missing["ADX_14"] = np.nan
        missing["MA50_Slope_Pct"] = np.nan

        details = StockScorer.technical_score_details(missing)

        self.assertIsNone(details["components"]["ADX"])
        self.assertIsNone(details["components"]["MA50"])
        self.assertIn("ADX", details["missing_components"])
        self.assertIn("MA50", details["missing_components"])
        self.assertAlmostEqual(
            details["coverage"],
            1.0 - (12.0 + 15.0) / StockScorer.MAX_TECH_SCORE,
        )

    def test_zero_technical_values_are_observed_not_missing(self):
        row = self._high_scoring_stock(
            RSI_14=0.0,
            MA50_Slope_Pct=0.0,
            MACD=0.0,
            MACD_Signal=0.0,
            ADX_14=0.0,
            ADX_Plus_DI=0.0,
            ADX_Minus_DI=0.0,
            StochRSI_14=0.0,
            ATR_14=0.0,
            Pct_Change_1M=0.0,
            Vol_Ratio=0.0,
            CMF_21=0.0,
            Price_Return_20D_Pct=0.0,
        ).iloc[0]

        details = StockScorer.technical_score_details(row)

        self.assertEqual(details["coverage"], 1.0)
        self.assertEqual(details["components"]["ATR"], 8.0)
        self.assertIsNotNone(details["components"]["ADX"])
        self.assertIsNotNone(details["components"]["VOL"])

    def test_raw_price_scale_does_not_change_adjusted_technical_score(self):
        first = self._high_scoring_stock(
            Current_Price=220.0,
            Technical_Price=110.0,
        ).iloc[0]
        second = first.copy()
        second["Current_Price"] = 999.0

        first_detail = StockScorer.technical_score_details(first)
        second_detail = StockScorer.technical_score_details(second)

        self.assertEqual(first_detail["components"], second_detail["components"])
        self.assertEqual(first_detail["adjusted_score"], second_detail["adjusted_score"])

    def test_momentum_is_continuous_around_zero(self):
        negative = self._high_scoring_stock(Pct_Change_1M=-0.01).iloc[0]
        positive = self._high_scoring_stock(Pct_Change_1M=0.01).iloc[0]

        neg_points = StockScorer.technical_score_details(negative)["components"]["MOM"]
        pos_points = StockScorer.technical_score_details(positive)["components"]["MOM"]

        self.assertGreater(pos_points, neg_points)
        self.assertLess(pos_points - neg_points, 0.1)

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
        self.assertEqual(scored.loc[0, "Core_Rating"], "HOLD")
        self.assertFalse(scored.loc[0, "Core_Buy_Eligible"])
        self.assertIn("MA50 falling", scored.loc[0, "Core_Rating_Cap_Reason"])

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
        self.assertEqual(scored.loc[0, "Core_Rating"], "HOLD")
        self.assertIn("MA50 falling", scored.loc[0, "Core_Buy_Gate_Reason"])
        self.assertIn("3M return not positive", scored.loc[0, "Core_Buy_Gate_Reason"])

    def test_stale_fundamental_fallback_cannot_receive_buy(self):
        stock = self._high_scoring_stock(Fund_Data_Stale=True)

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Core_Rating"], "HOLD")
        self.assertIn("stale fundamental fallback", scored.loc[0, "Core_Rating_Cap_Reason"])

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
            "Technical_Price": 110.0,
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
        self.assertFalse(scored.loc[0, "Core_Rating_Capped"])
        self.assertFalse(scored.loc[0, "Specialized_Fundamental_Model_Required"])
        self.assertFalse(scored.loc[0, "Specialized_Quality_Eligible"])
        self.assertEqual(scored.loc[0, "Core_Rating"], "BUY")
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

        self.assertEqual(scored.loc[0, "Core_Rating"], "STRONG BUY")
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

        self.assertEqual(scored.loc[0, "Core_Rating"], "BUY")
        self.assertFalse(scored.loc[0, "Specialized_Quality_Eligible"])
        self.assertIn("Gross NPA", scored.loc[0, "Core_Strong_Buy_Gate_Reason"])

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

        self.assertNotEqual(scored.loc[0, "Core_Rating"], "STRONG BUY")
        self.assertTrue(scored.loc[0, "Fundamental_Anomaly"])
        self.assertIn("extreme earnings growth", scored.loc[0, "Core_Strong_Buy_Gate_Reason"])

    def test_multiple_extreme_fundamental_values_cap_rating_at_hold(self):
        stock = self._high_scoring_stock(
            Symbol="OUTLIER",
            PE_Ratio=0.5,
            ROE=1.2,
            Profit_Margin=1.5,
        )

        scored = StockScorer().score_all_stocks(stock)

        self.assertEqual(scored.loc[0, "Core_Rating"], "HOLD")
        self.assertTrue(scored.loc[0, "Core_Rating_Capped"])
        self.assertIn("multiple fundamental data anomalies", scored.loc[0, "Core_Rating_Cap_Reason"])

    def test_scorer_emits_only_core_decisions_in_score_first_order(self):
        first = self._high_scoring_stock(Symbol="ZZZ")
        second = self._high_scoring_stock(Symbol="AAA")
        source = pd.concat([first, second], ignore_index=True)
        # Simulate rescoring a prior export; stale canonical decisions must not
        # survive the component-scoring boundary.
        source["Rating"] = ["SELL", "SELL"]
        source["Rank"] = [99, 98]
        source["Buy_Eligible"] = [False, False]
        source["Final_Score"] = [1.0, 2.0]

        scored = StockScorer().score_all_stocks(source)

        self.assertEqual(scored["Symbol"].tolist(), ["AAA", "ZZZ"])
        self.assertEqual(scored["Core_Score_Rank"].tolist(), [1, 2])
        self.assertEqual(scored["Core_Score"].tolist(), scored["Combined_Score"].tolist())
        self.assertTrue((scored["Core_Rating"] == "STRONG BUY").all())
        for canonical in (
            "Rating",
            "Rank",
            "Buy_Eligible",
            "Strong_Buy_Eligible",
            "Rating_Capped",
            "Final_Score",
        ):
            self.assertNotIn(canonical, scored.columns)

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
            "Technical_Price": 110.0,
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
