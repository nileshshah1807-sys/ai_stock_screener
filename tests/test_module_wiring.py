import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from app import run_daily_analysis
from screener.data_collection import StockDataCollector
from screener.reporting import InteractiveDashboard


class ModuleWiringTests(unittest.TestCase):
    def test_nse_master_response_populates_full_universe(self):
        config = SimpleNamespace(SCAN_ALL_NSE=True, CUSTOM_WATCHLIST=[])
        response = SimpleNamespace(
            status_code=200,
            text=(
                "SYMBOL,NAME OF COMPANY\n"
                "20MICRONS,20 Microns Limited\n"
                "BAJAJ-AUTO,Bajaj Auto Limited\n"
                "RELIANCE,Reliance Industries\n"
            ),
        )

        with patch("screener.data_collection.requests.get", return_value=response):
            symbols = StockDataCollector(config).get_comprehensive_stock_list()

        self.assertIn("20MICRONS", symbols)
        self.assertIn("BAJAJ-AUTO", symbols)
        self.assertIn("ETERNAL", symbols)
        self.assertIn("TMCV", symbols)
        self.assertNotIn("ZOMATO", symbols)
        self.assertNotIn("TATAMOTORS", symbols)

    def test_dashboard_generates_with_pandas_histogram(self):
        scored = pd.DataFrame([{
            "Rank": 1,
            "Symbol": "RELIANCE",
            "Current_Price": 100.0,
            "Rating": "BUY",
            "Fundamental_Score": 70.0,
            "Technical_Score": 65.0,
            "Combined_Score": 68.0,
            "Final_Score": 69.0,
        }])
        with tempfile.TemporaryDirectory() as output_dir:
            path = InteractiveDashboard.generate(scored, "06-08-2026", output_dir)

            self.assertEqual(path, str(Path(output_dir) / "dashboard_06082026.html"))
            self.assertTrue(Path(path).exists())

    def test_single_ticker_multilevel_download_is_collected(self):
        symbol = "BAJAJ-AUTO.NS"
        prices = [100.0 + index for index in range(80)]
        columns = pd.MultiIndex.from_product([
            [symbol], ["Open", "High", "Low", "Close", "Volume"],
        ])
        rows = [
            [price, price + 1, price - 1, price, 100_000]
            for price in prices
        ]
        download = pd.DataFrame(rows, columns=columns)

        with tempfile.TemporaryDirectory() as output_dir:
            config = SimpleNamespace(
                OUTPUT_DIR=Path(output_dir),
                PRICE_CACHE_MAX_AGE_HOURS=18,
            )
            with patch("screener.data_collection.yf.download", return_value=download):
                result = StockDataCollector(config).download_stock_data(["BAJAJ-AUTO"])

        self.assertEqual(result["Symbol"].tolist(), ["BAJAJ-AUTO"])

    def test_empty_market_data_fails_the_run_instead_of_exiting_green(self):
        collector = SimpleNamespace(
            get_comprehensive_stock_list=lambda: ["RELIANCE"],
            download_stock_data=lambda symbols: pd.DataFrame(),
        )
        with (
            patch("app.Config", return_value=SimpleNamespace()),
            patch("app.configure_runtime_cache"),
            patch("app.StockDataCollector", return_value=collector),
        ):
            with self.assertRaisesRegex(RuntimeError, "No technical data"):
                run_daily_analysis()


if __name__ == "__main__":
    unittest.main()
