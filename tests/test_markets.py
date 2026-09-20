import os
import unittest
from types import SimpleNamespace
from unittest import mock

from screener.markets import (
    MARKETS,
    NSE,
    US,
    active_profile,
    bare_symbol,
    normalize_market,
    resolve,
    ticker_for,
)
from screener.runtime import Config


class MarketResolutionTests(unittest.TestCase):
    def test_default_market_is_nse(self):
        self.assertEqual(normalize_market(None), NSE)
        self.assertEqual(normalize_market("  "), NSE)
        self.assertEqual(resolve(None).code, NSE)

    def test_market_code_is_case_and_space_insensitive(self):
        self.assertEqual(resolve(" us ").code, US)
        self.assertEqual(resolve("nse").code, NSE)

    def test_unknown_market_raises_rather_than_defaulting(self):
        """A typo must stop the run, not silently publish under the wrong market."""
        with self.assertRaises(ValueError) as caught:
            resolve("LSE")
        self.assertIn("LSE", str(caught.exception))
        self.assertIn("NSE", str(caught.exception))

    def test_config_market_wins_over_environment(self):
        config = SimpleNamespace(MARKET="US")
        with mock.patch.dict(os.environ, {"MARKET": "NSE"}):
            self.assertEqual(active_profile(config).code, US)

    def test_stub_config_without_market_falls_back_to_nse(self):
        """The suite is full of SimpleNamespace configs predating this module."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(active_profile(SimpleNamespace()).code, NSE)
            self.assertEqual(active_profile(None).code, NSE)


class TickerTranslationTests(unittest.TestCase):
    def test_nse_symbols_take_the_yfinance_suffix(self):
        profile = resolve(NSE)
        self.assertEqual(ticker_for("reliance", profile), "RELIANCE.NS")
        self.assertEqual(bare_symbol("RELIANCE.NS", profile), "RELIANCE")

    def test_us_symbols_are_already_vendor_tickers(self):
        profile = resolve(US)
        self.assertEqual(ticker_for("aapl", profile), "AAPL")
        self.assertEqual(bare_symbol("AAPL", profile), "AAPL")

    def test_bare_symbol_tolerates_an_already_bare_input(self):
        profile = resolve(NSE)
        self.assertEqual(bare_symbol("RELIANCE", profile), "RELIANCE")

    def test_suffix_is_only_stripped_from_the_end(self):
        """A symbol that merely contains the suffix text keeps it."""
        profile = resolve(NSE)
        self.assertEqual(bare_symbol("NSAMPLE", profile), "NSAMPLE")


class ProfileContentTests(unittest.TestCase):
    def test_every_profile_is_self_consistent(self):
        for code, profile in MARKETS.items():
            with self.subTest(market=code):
                self.assertEqual(profile.code, code)
                self.assertTrue(profile.benchmark_symbol)
                self.assertTrue(profile.timezone)
                self.assertTrue(profile.fallback_symbols)
                self.assertTrue(profile.safety_net_symbols)

    def test_us_has_no_impact_cost_provider(self):
        """NSE's monthly impact-cost file has no US equivalent."""
        self.assertIsNone(resolve(US).liquidity_provider)
        self.assertEqual(resolve(NSE).liquidity_provider, "nse_impact_cost")

    def test_nse_defaults_are_unchanged_by_the_market_refactor(self):
        """The regression that matters: an unset MARKET screens NSE as before."""
        profile = resolve(NSE)
        self.assertEqual(profile.timezone, "Asia/Kolkata")
        self.assertEqual(profile.bar_complete_after, "16:15")
        self.assertEqual(profile.benchmark_symbol, "^CRSLDX")
        self.assertEqual(profile.benchmark_fallback, "^NSEI")
        self.assertEqual(profile.ticker_suffix, ".NS")


class ConfigDefaultTests(unittest.TestCase):
    """Config is imported with MARKET unset, so it must still read as NSE."""

    def test_config_defaults_match_the_nse_profile(self):
        profile = resolve(NSE)
        self.assertEqual(Config.MARKET, NSE)
        self.assertEqual(Config.ANALYSIS_TIMEZONE, profile.timezone)
        self.assertEqual(
            Config.MARKET_BAR_COMPLETE_AFTER_IST, profile.bar_complete_after
        )
        self.assertEqual(Config.BENCHMARK_INDEX_SYMBOL, profile.benchmark_symbol)
        self.assertEqual(Config.BENCHMARK_INDEX_FALLBACK, profile.benchmark_fallback)
        self.assertEqual(Config.MARKET_CURRENCY, "INR")
        self.assertEqual(list(Config.CUSTOM_WATCHLIST), list(profile.fallback_symbols))


if __name__ == "__main__":
    unittest.main()
