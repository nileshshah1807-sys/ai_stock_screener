import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from screener.data_collection import StockDataCollector
from screener.reporting import InteractiveDashboard


class ModuleWiringTests(unittest.TestCase):
    def test_nse_master_response_populates_full_universe(self):
        config = SimpleNamespace(SCAN_ALL_NSE=True, CUSTOM_WATCHLIST=[])
        response = SimpleNamespace(
            status_code=200,
            text="SYMBOL,NAME OF COMPANY\n20MICRONS,20 Microns Limited\nRELIANCE,Reliance Industries\n",
        )

        with patch("screener.data_collection.requests.get", return_value=response):
            symbols = StockDataCollector(config).get_comprehensive_stock_list()

        self.assertIn("20MICRONS", symbols)
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


if __name__ == "__main__":
    unittest.main()