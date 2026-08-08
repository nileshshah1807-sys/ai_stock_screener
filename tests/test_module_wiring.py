import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from app import run_daily_analysis
from screener.data_collection import StockDataCollector
from screener.reporting import EmailReporter, InteractiveDashboard, REPORTLAB_AVAILABLE


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

    @unittest.skipUnless(REPORTLAB_AVAILABLE, "reportlab is not installed")
    def test_pdf_report_contains_only_compact_ranked_stock_fields(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("PyMuPDF is not installed")

        scored = pd.DataFrame([{
            "Rank": 1,
            "Symbol": "SYRMA",
            "Company": "Syrma SGS Technology Limited",
            "Current_Price": 823.45,
            "PE_Ratio": 28.7,
            "Fundamental_Score": 84.0,
            "Technical_Score": 76.0,
            "Transcript_Score": 73.7,
            "Rating": "STRONG BUY",
            "Fundamental_Model": "Generic Fundamental Model",
            "Fund_Component_Summary": "Detailed fundamental evidence",
            "Specialized_Quality_Gate_Reason": "passed",
            "DCF_Assessment": "Attractive reverse DCF",
        }])
        with tempfile.TemporaryDirectory() as output_dir:
            config = SimpleNamespace(
                OUTPUT_DIR=Path(output_dir),
                TOP_STOCKS_COUNT=20,
            )
            path = EmailReporter(config).create_pdf_report(scored, "07-08-2026")

            self.assertIsNotNone(path)
            with pymupdf.open(path) as document:
                self.assertEqual(document.page_count, 1)
                pdf_text = "\n".join(page.get_text() for page in document)

        for expected in ("Rank", "Company", "CMP", "PE", "Fund", "Tech", "Transcript", "Score", "Rating"):
            self.assertIn(expected, pdf_text)
        for expected in ("Syrma SGS Technology Limited", "823", "28.7", "84", "76", "73.7", "STRONG BUY"):
            self.assertIn(expected, pdf_text)
        for excluded in (
            "Generic Fundamental Model",
            "Detailed fundamental evidence",
            "Quality Gate",
            "Reverse DCF",
            "Attractive reverse DCF",
        ):
            self.assertNotIn(excluded, pdf_text)

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
