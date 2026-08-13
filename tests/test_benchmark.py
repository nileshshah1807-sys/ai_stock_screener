"""Behavioural spec for benchmark loading, relative strength and regime."""

import unittest

import numpy as np
import pandas as pd

from screener.benchmark import (
    NEUTRAL,
    RISK_OFF,
    RISK_ON,
    UNKNOWN,
    BenchmarkProvider,
    classify_regime,
)


def rising(sessions=300, daily=0.002):
    return pd.Series([100.0 * (1 + daily) ** step for step in range(sessions)])


def falling(sessions=300, daily=-0.002):
    return pd.Series([100.0 * (1 + daily) ** step for step in range(sessions)])


class Config:
    PRICE_HISTORY_PERIOD = "2y"
    BENCHMARK_INDEX_SYMBOL = "^CRSLDX"
    BENCHMARK_INDEX_FALLBACK = "^NSEI"
    MARKET_REGIME_ENABLED = True
    MARKET_REGIME_MA_SESSIONS = 200
    MARKET_REGIME_SLOPE_SESSIONS = 20
    MARKET_REGIME_NEUTRAL_BAND_PCT = 2.0


class RegimeTests(unittest.TestCase):
    def test_advancing_market_is_risk_on(self):
        result = classify_regime(rising())
        self.assertEqual(result["Market_Regime"], RISK_ON)
        self.assertGreater(result["Market_Index_Distance_Pct"], 2.0)
        self.assertGreater(result["Market_Index_MA_Slope_Pct"], 0.0)

    def test_declining_market_is_risk_off(self):
        result = classify_regime(falling())
        self.assertEqual(result["Market_Regime"], RISK_OFF)
        self.assertLess(result["Market_Index_Distance_Pct"], -2.0)
        self.assertLess(result["Market_Index_MA_Slope_Pct"], 0.0)

    def test_flat_market_inside_the_band_is_neutral(self):
        self.assertEqual(classify_regime(pd.Series([100.0] * 300))["Market_Regime"], NEUTRAL)

    def test_level_and_trend_disagreement_is_neutral(self):
        # Price has rebounded well above the average, but the average itself is
        # still falling because high old sessions keep rolling out of it. Level
        # and trend disagree, so this must not be promoted to risk-on.
        series = pd.Series([130.0] * 120 + [90.0] * 170 + [120.0] * 10)
        result = classify_regime(series)
        self.assertGreater(result["Market_Index_Distance_Pct"], 2.0)
        self.assertLess(result["Market_Index_MA_Slope_Pct"], 0.0)
        self.assertEqual(result["Market_Regime"], NEUTRAL)

    def test_neutral_band_prevents_a_one_session_flip(self):
        # Just above the average but inside the band -> not yet risk-on.
        base = [100.0] * 299
        result = classify_regime(pd.Series(base + [100.5]), neutral_band_pct=2.0)
        self.assertEqual(result["Market_Regime"], NEUTRAL)

    def test_insufficient_history_is_unknown_not_neutral(self):
        result = classify_regime(rising(sessions=100))
        self.assertEqual(result["Market_Regime"], UNKNOWN)
        self.assertTrue(np.isnan(result["Market_Index_Distance_Pct"]))


class ProviderTests(unittest.TestCase):
    @staticmethod
    def build(responses):
        calls = []

        def downloader(symbol, period):
            calls.append(symbol)
            payload = responses.get(symbol)
            if isinstance(payload, Exception):
                raise payload
            return payload

        return BenchmarkProvider(Config, downloader=downloader), calls

    def test_primary_index_is_used_when_available(self):
        frame = pd.DataFrame({"Adj Close": rising(), "Close": rising()})
        provider, calls = self.build({"^CRSLDX": frame})
        symbol, series = provider.load()
        self.assertEqual(symbol, "^CRSLDX")
        self.assertEqual(len(series), 300)
        self.assertEqual(calls, ["^CRSLDX"])

    def test_falls_back_to_the_secondary_index(self):
        frame = pd.DataFrame({"Adj Close": rising()})
        provider, calls = self.build(
            {"^CRSLDX": RuntimeError("no data"), "^NSEI": frame}
        )
        symbol, _ = provider.load()
        self.assertEqual(symbol, "^NSEI")
        self.assertEqual(calls, ["^CRSLDX", "^NSEI"])

    def test_missing_benchmark_degrades_without_raising(self):
        provider, _ = self.build({})
        context = provider.market_context()
        self.assertEqual(context["Benchmark_Symbol"], "unavailable")
        self.assertEqual(context["Market_Regime"], UNKNOWN)
        self.assertTrue(np.isnan(context["Benchmark_Return_6M_Pct"]))

    def test_market_context_exposes_formation_returns(self):
        frame = pd.DataFrame({"Adj Close": rising()})
        provider, _ = self.build({"^CRSLDX": frame})
        context = provider.market_context()
        self.assertEqual(context["Market_Regime"], RISK_ON)
        self.assertGreater(context["Benchmark_Return_6M_Pct"], 0.0)
        self.assertGreater(context["Benchmark_Return_12M_Pct"], 0.0)
        # The 12-1 formation window ends a month earlier, so on a steadily
        # compounding series it is strictly smaller than the full 12M return.
        self.assertLess(
            context["Benchmark_Return_12_1_Pct"],
            context["Benchmark_Return_12M_Pct"],
        )

    def test_multiindex_download_shape_is_handled(self):
        columns = pd.MultiIndex.from_product([["Adj Close", "Close"], ["^CRSLDX"]])
        frame = pd.DataFrame(
            np.column_stack([rising().to_numpy(), rising().to_numpy()]),
            columns=columns,
        )
        provider, _ = self.build({"^CRSLDX": frame})
        symbol, series = provider.load()
        self.assertEqual(symbol, "^CRSLDX")
        self.assertEqual(len(series), 300)


if __name__ == "__main__":
    unittest.main()
