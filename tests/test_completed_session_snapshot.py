import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from screener.data_collection import (
    StockDataCollector,
    align_valuation_to_completed_price_bar,
)
from screener.market_data import PriceCache, TechnicalEnhancer


IST = ZoneInfo("Asia/Kolkata")


class CompletedSessionSnapshotTests(unittest.TestCase):
    @staticmethod
    def _price_frame(end="2026-08-10", periods=80, final_price=999.0):
        dates = pd.bdate_range(end=end, periods=periods)
        closes = [100.0 + position for position in range(periods)]
        closes[-1] = final_price
        return pd.DataFrame(
            {
                "Open": closes,
                "High": [value + 1.0 for value in closes],
                "Low": [value - 1.0 for value in closes],
                "Close": closes,
                "Adj Close": closes,
                "Volume": [100_000 + position for position in range(periods)],
            },
            index=dates,
        )

    @staticmethod
    def _config(output_dir):
        return SimpleNamespace(
            OUTPUT_DIR=Path(output_dir),
            PRICE_CACHE_MAX_AGE_HOURS=18,
            FUND_CACHE_MAX_AGE_DAYS=7,
        )

    def _collect(self, now, frame, *, completion_cutoff=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        collector = StockDataCollector(
            self._config(directory.name),
            clock=lambda: now,
            completion_cutoff=completion_cutoff,
        )
        with patch("screener.data_collection.yf.download", return_value=frame):
            return collector.download_stock_data(["EXAMPLE"])

    def test_pre_cutoff_excludes_same_day_bar_from_price_and_all_indicators(self):
        frame = self._price_frame()

        result = self._collect(datetime(2026, 8, 10, 15, 0, tzinfo=IST), frame)

        row = result.iloc[0]
        self.assertEqual(row["Current_Price"], 178.0)
        self.assertEqual(row["Technical_Price"], 178.0)
        self.assertEqual(row["High_6M"], 178.0)
        self.assertEqual(row["MA20"], 168.5)
        self.assertEqual(row["Price_Bar_As_Of"], "2026-08-07")
        self.assertTrue(row["Price_Bar_Complete"])
        self.assertEqual(row["Analysis_As_Of"], "2026-08-10T15:00:00+05:30")
        self.assertEqual(row["Price_Fetched_At"], "2026-08-10T15:00:00+05:30")

    def test_same_day_bar_is_accepted_at_official_1615_cutoff(self):
        frame = self._price_frame()

        result = self._collect(datetime(2026, 8, 10, 16, 15, tzinfo=IST), frame)

        row = result.iloc[0]
        self.assertEqual(row["Current_Price"], 999.0)
        self.assertEqual(row["Technical_Price"], 999.0)
        self.assertEqual(row["Price_Bar_As_Of"], "2026-08-10")
        self.assertTrue(row["Price_Bar_Complete"])

    def test_collector_exports_raw_and_adjusted_price_scales_separately(self):
        frame = self._price_frame()
        frame["Adj Close"] = frame["Close"] / 2.0

        result = self._collect(
            datetime(2026, 8, 10, 16, 15, tzinfo=IST), frame
        )

        row = result.iloc[0]
        self.assertEqual(row["Current_Price"], 999.0)
        self.assertEqual(row["Technical_Price"], 499.5)
        self.assertAlmostEqual(row["MA20"], frame["Adj Close"].tail(20).mean(), 2)

    def test_insufficient_return_and_slope_history_is_explicitly_missing(self):
        frame = self._price_frame(periods=60, final_price=159.0)

        result = self._collect(
            datetime(2026, 8, 10, 16, 15, tzinfo=IST), frame
        )

        row = result.iloc[0]
        self.assertFalse(pd.isna(row["Pct_Change_1M"]))
        self.assertTrue(pd.isna(row["Pct_Change_3M"]))
        self.assertTrue(pd.isna(row["MA50_Slope_Pct"]))

    def test_prior_bar_is_rejected_after_cutoff_on_normal_session(self):
        frame = self._price_frame(end="2026-08-07", final_price=179.0)

        result = self._collect(
            datetime(2026, 8, 10, 16, 30, tzinfo=IST), frame
        )

        self.assertTrue(result.empty)

    def test_completion_cutoff_is_configurable(self):
        frame = self._price_frame()

        result = self._collect(
            datetime(2026, 8, 10, 16, 20, tzinfo=IST),
            frame,
            completion_cutoff="16:30",
        )

        self.assertEqual(result.iloc[0]["Current_Price"], 178.0)
        self.assertEqual(result.iloc[0]["Price_Bar_As_Of"], "2026-08-07")

    def test_weekend_uses_latest_available_completed_bar(self):
        frame = self._price_frame(end="2026-08-07", final_price=179.0)

        result = self._collect(datetime(2026, 8, 9, 12, 0, tzinfo=IST), frame)

        self.assertEqual(result.iloc[0]["Current_Price"], 179.0)
        self.assertEqual(result.iloc[0]["Price_Bar_As_Of"], "2026-08-07")

    def test_symbol_lagging_expected_session_is_rejected_before_cutoff(self):
        frame = self._price_frame(end="2026-08-06", final_price=179.0)

        result = self._collect(
            datetime(2026, 8, 10, 15, 0, tzinfo=IST), frame
        )

        self.assertTrue(result.empty)

    @staticmethod
    def _cache_record(**overrides):
        row = {column: 1 for column in PriceCache.REQUIRED_COLUMNS}
        row.update(
            {
                "Symbol": "EXAMPLE",
                "Technical_Indicator_Version": TechnicalEnhancer.INDICATOR_VERSION,
                "Price_Bar_As_Of": "2026-08-07",
                "Price_Bar_Complete": True,
                "Analysis_As_Of": "2026-08-10T15:00:00+05:30",
                "Price_Fetched_At": "2026-08-10T15:00:00+05:30",
            }
        )
        row.update(overrides)
        return row

    def test_cache_crossing_completion_cutoff_forces_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "price_cache.csv"
            PriceCache.save(path, [self._cache_record()])

            before = PriceCache.load(
                path,
                max_age_hours=1_000_000,
                as_of=datetime(2026, 8, 10, 15, 30, tzinfo=IST),
            )
            after = PriceCache.load(
                path,
                max_age_hours=1_000_000,
                as_of=datetime(2026, 8, 10, 16, 30, tzinfo=IST),
            )

        self.assertFalse(before.empty)
        self.assertTrue(after.empty)

    def test_after_cutoff_fetch_can_reuse_prior_bar_on_holiday(self):
        # 2026-08-11 is declared a holiday, so the latest expected completed
        # session is Monday 2026-08-10 and the cached bar must match it.
        record = self._cache_record(
            Price_Bar_As_Of="2026-08-10",
            Analysis_As_Of="2026-08-11T16:20:00+05:30",
            Price_Fetched_At="2026-08-11T16:20:00+05:30",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "price_cache.csv"
            PriceCache.save(path, [record])

            cached = PriceCache.load(
                path,
                max_age_hours=1_000_000,
                as_of=datetime(2026, 8, 11, 16, 30, tzinfo=IST),
                market_holidays=("2026-08-11",),
            )

        self.assertFalse(cached.empty)

    def test_after_cutoff_prior_bar_is_rejected_on_normal_session(self):
        # Same prior-session bar as the holiday case, but 2026-08-11 is a
        # normal session, so its own completed bar is the one required.
        record = self._cache_record(
            Price_Bar_As_Of="2026-08-10",
            Analysis_As_Of="2026-08-11T16:20:00+05:30",
            Price_Fetched_At="2026-08-11T16:20:00+05:30",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "price_cache.csv"
            PriceCache.save(path, [record])

            cached = PriceCache.load(
                path,
                max_age_hours=1_000_000,
                as_of=datetime(2026, 8, 11, 16, 30, tzinfo=IST),
            )

        self.assertTrue(cached.empty)

    def test_after_cutoff_fetch_cannot_relabel_pre_cutoff_snapshot_as_complete(self):
        record = self._cache_record(
            Analysis_As_Of="2026-08-10T15:00:00+05:30",
            Price_Fetched_At="2026-08-10T16:20:00+05:30",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "price_cache.csv"
            PriceCache.save(path, [record])

            cached = PriceCache.load(
                path,
                max_age_hours=1_000_000,
                as_of=datetime(2026, 8, 10, 16, 30, tzinfo=IST),
            )

        self.assertTrue(cached.empty)

    def test_rewriting_cache_file_does_not_extend_old_source_fetch(self):
        record = self._cache_record(
            Analysis_As_Of="2026-08-09T18:30:00+05:30",
            Price_Fetched_At="2026-08-09T18:30:00+05:30",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "price_cache.csv"
            # Saving now gives the file a fresh mtime; source-fetch age must
            # still invalidate it independently of that filesystem timestamp.
            PriceCache.save(path, [record])

            cached = PriceCache.load(
                path,
                max_age_hours=18,
                as_of=datetime(2026, 8, 10, 15, 0, tzinfo=IST),
            )

        self.assertTrue(cached.empty)

    def test_fundamental_fetch_preserves_raw_recomputation_inputs_and_timestamp(self):
        fixed_now = datetime(2026, 8, 10, 16, 30, tzinfo=IST)
        info = {
            "longName": "Example Limited",
            "trailingEps": 12.5,
            "bookValue": 80.0,
            "sharesOutstanding": 10_000_000,
            "ebitda": 500_000_000,
            "totalDebt": 100_000_000,
            "totalCash": 50_000_000,
            "dividendRate": 4.0,
            "sector": "Industrials",
            "industry": "Specialty Industrial Machinery",
        }
        with tempfile.TemporaryDirectory() as directory:
            collector = StockDataCollector(
                self._config(directory), clock=lambda: fixed_now
            )
            ticker = SimpleNamespace(info=info)
            with patch("screener.data_collection.yf.Ticker", return_value=ticker):
                result = collector.get_fundamental_data(
                    pd.DataFrame([{"Symbol": "EXAMPLE"}])
                )

        row = result.iloc[0]
        self.assertEqual(row["EPS"], 12.5)
        self.assertEqual(row["Book_Value"], 80.0)
        self.assertEqual(row["Shares_Outstanding"], 10_000_000)
        self.assertEqual(row["EBITDA"], 500_000_000)
        self.assertEqual(row["Total_Debt"], 100_000_000)
        self.assertEqual(row["Total_Cash"], 50_000_000)
        self.assertEqual(row["Dividend_Rate"], 4.0)
        self.assertEqual(row["Fundamental_As_Of"], "2026-08-10T16:30:00+05:30")
        self.assertEqual(row["Fundamental_Fetched_At"], "2026-08-10T16:30:00+05:30")
        self.assertEqual(row["Fundamental_As_Of_Quality"], "fetch_timestamp")

    def test_valuation_helper_recomputes_from_completed_close_and_preserves_source(self):
        merged = pd.DataFrame(
            [
                {
                    "Current_Price": 100.0,
                    "Price_Bar_As_Of": "2026-08-10",
                    "EPS": 10.0,
                    "Book_Value": 50.0,
                    "Shares_Outstanding": 100.0,
                    "EBITDA": 1_000.0,
                    "Total_Debt": 100.0,
                    "Total_Cash": 50.0,
                    "PE_Ratio": 99.0,
                    "PB_Ratio": 88.0,
                    "Market_Cap": 77.0,
                    "EV_EBITDA": 66.0,
                    "Dividend_Yield": 4.0,
                    "Dividend_Yield_Ratio": 0.04,
                    "Dividend_Rate": 4.0,
                }
            ]
        )

        result = align_valuation_to_completed_price_bar(merged)
        row = result.iloc[0]

        self.assertEqual(row["PE_Ratio"], 10.0)
        self.assertEqual(row["PB_Ratio"], 2.0)
        self.assertEqual(row["Market_Cap"], 10_000.0)
        self.assertEqual(row["EV_EBITDA"], 10.05)
        self.assertEqual(row["Dividend_Yield_Ratio"], 0.04)
        self.assertEqual(row["Dividend_Yield"], 4.0)
        self.assertEqual(row["PE_Ratio_As_Fetched"], 99.0)
        self.assertEqual(row["EV_EBITDA_As_Fetched"], 66.0)
        self.assertEqual(row["Valuation_Price_Alignment_Status"], "complete")
        self.assertEqual(row["Valuation_Price_As_Of"], "2026-08-10")


if __name__ == "__main__":
    unittest.main()
