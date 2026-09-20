"""The collector's market wiring: universe selection and ticker translation."""

import unittest
from types import SimpleNamespace
from unittest import mock

from screener import universe
from screener.data_collection import StockDataCollector
from screener.markets import resolve


def _config(market=None, **overrides):
    config = SimpleNamespace(
        SCAN_ALL_NSE=True,
        CUSTOM_WATCHLIST=["AAA", "BBB"],
        US_UNIVERSE_SOURCE="",
    )
    if market is not None:
        config.MARKET = market
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _result(symbols, status="ok"):
    return universe.UniverseResult(
        symbols=tuple(symbols),
        source_url="https://example.test/universe.csv",
        status=status,
        source_sha256="0" * 64,
        source_symbol_count=len(set(symbols)),
    )


class UniverseSelectionTests(unittest.TestCase):
    def test_fetched_symbols_are_unioned_with_the_safety_net(self):
        config = _config()
        collector = StockDataCollector(config)
        with mock.patch.object(universe, "fetch", return_value=_result(["ZZTOP"])):
            symbols = collector.get_comprehensive_stock_list()

        self.assertIn("ZZTOP", symbols)
        # RELIANCE is in the NSE safety net but not in the mocked fetch.
        self.assertIn("RELIANCE", symbols)

    def test_diagnostics_record_the_market_and_its_provenance(self):
        config = _config()
        collector = StockDataCollector(config)
        with mock.patch.object(universe, "fetch", return_value=_result(["ZZTOP"])):
            collector.get_comprehensive_stock_list()

        diagnostics = collector.collection_diagnostics
        self.assertEqual(diagnostics["market"], "NSE")
        self.assertEqual(diagnostics["universe_source"], "nse_equity_l")
        self.assertEqual(diagnostics["universe_fetch_status"], "ok")
        self.assertEqual(diagnostics["universe_source_sha256"], "0" * 64)
        self.assertIn("universe_fetched_at", diagnostics)

    def test_a_failed_fetch_records_no_fetch_timestamp(self):
        config = _config()
        collector = StockDataCollector(config)
        failed = _result([], status="error:TimeoutError")
        with mock.patch.object(universe, "fetch", return_value=failed):
            symbols = collector.get_comprehensive_stock_list()

        self.assertNotIn("universe_fetched_at", collector.collection_diagnostics)
        # The safety net is what keeps a vendor outage from emptying the run.
        self.assertIn("RELIANCE", symbols)

    def test_custom_watchlist_override_replaces_the_universe(self):
        config = _config(SCAN_ALL_NSE=False)
        collector = StockDataCollector(config)
        with mock.patch.object(universe, "fetch", return_value=_result(["ZZTOP"])):
            symbols = collector.get_comprehensive_stock_list()

        self.assertEqual(symbols, ["AAA", "BBB"])
        self.assertTrue(
            collector.collection_diagnostics["universe_fetch_status"].endswith(
                ":custom_watchlist_override"
            )
        )

    def test_overlong_symbols_are_dropped(self):
        config = _config()
        collector = StockDataCollector(config)
        with mock.patch.object(universe, "fetch", return_value=_result(["A" * 21])):
            symbols = collector.get_comprehensive_stock_list()

        self.assertNotIn("A" * 21, symbols)


class MarketProfileWiringTests(unittest.TestCase):
    def test_an_nse_collector_keeps_the_pre_refactor_defaults(self):
        collector = StockDataCollector(_config())

        self.assertEqual(collector.market_profile.code, "NSE")
        self.assertEqual(str(collector.market_timezone), "Asia/Kolkata")
        self.assertEqual(collector.price_bar_completion_cutoff.hour, 16)
        self.assertEqual(collector.price_bar_completion_cutoff.minute, 15)

    def test_a_us_collector_takes_its_session_from_the_us_profile(self):
        collector = StockDataCollector(_config(market="US"))

        self.assertEqual(collector.market_profile.code, "US")
        self.assertEqual(str(collector.market_timezone), "America/New_York")
        self.assertEqual(collector.price_bar_completion_cutoff.hour, 16)
        self.assertEqual(collector.price_bar_completion_cutoff.minute, 0)

    def test_explicit_arguments_still_win_over_the_profile(self):
        collector = StockDataCollector(
            _config(market="US"),
            market_timezone="Asia/Kolkata",
            completion_cutoff="09:30",
        )

        self.assertEqual(str(collector.market_timezone), "Asia/Kolkata")
        self.assertEqual(collector.price_bar_completion_cutoff.minute, 30)

    def test_us_universe_source_reaches_the_diagnostics(self):
        config = _config(market="US", US_UNIVERSE_SOURCE="all_listed")
        collector = StockDataCollector(config)

        self.assertEqual(collector.collection_diagnostics["universe_source"], "all_listed")
        self.assertEqual(
            collector.collection_diagnostics["universe_source_url"],
            universe.SOURCE_URLS["all_listed"],
        )


class StatementTickerTests(unittest.TestCase):
    def test_statement_fetch_uses_the_market_suffix(self):
        from screener.statements import FinancialStatementCollector

        seen = []

        def factory(ticker):
            seen.append(ticker)
            raise RuntimeError("stop after the ticker is built")

        for market, expected in (("NSE", "RELIANCE.NS"), ("US", "AAPL")):
            with self.subTest(market=market):
                seen.clear()
                collector = FinancialStatementCollector(
                    SimpleNamespace(MARKET=market), ticker_factory=factory
                )
                symbol = "RELIANCE" if market == "NSE" else "AAPL"
                self.assertIsNone(collector.fetch_symbol(symbol))
                self.assertEqual(seen, [expected])


class TickerBatchTests(unittest.TestCase):
    """download_stock_data builds vendor tickers from the profile."""

    def test_nse_batches_carry_the_suffix_and_results_are_bare(self):
        from screener.markets import bare_symbol, ticker_for

        profile = resolve("NSE")
        batch = [ticker_for(s, profile) for s in ["RELIANCE", "TCS"]]
        self.assertEqual(batch, ["RELIANCE.NS", "TCS.NS"])
        self.assertEqual([bare_symbol(s, profile) for s in batch], ["RELIANCE", "TCS"])

    def test_us_batches_are_unchanged_round_trip(self):
        from screener.markets import bare_symbol, ticker_for

        profile = resolve("US")
        batch = [ticker_for(s, profile) for s in ["AAPL", "BRK-B"]]
        self.assertEqual(batch, ["AAPL", "BRK-B"])
        self.assertEqual([bare_symbol(s, profile) for s in batch], ["AAPL", "BRK-B"])


if __name__ == "__main__":
    unittest.main()
