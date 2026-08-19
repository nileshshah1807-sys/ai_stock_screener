"""Behavioural spec for bhavcopy normalisation and the day-file store."""

import gzip
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from backtest.bhavcopy import (
    BhavcopyStore,
    candidate_sessions,
    detect_format,
    is_udiff_date,
    normalise_bhavcopy,
)


def udiff_frame():
    """A UDIFF cash-market file: stocks, a derivative row, and a non-EQ series."""
    return pd.DataFrame(
        {
            "TradDt": ["2026-08-11"] * 4,
            "FinInstrmTp": ["STK", "STK", "STF", "STK"],
            "ISIN": ["INE001A01036", "INE002B01018", "INE003C01010", "INE004D01012"],
            "TckrSymb": ["ALPHA", "BETA", "GAMMAFUT", "DELTA"],
            "SctySrs": ["EQ", "BE", "EQ", "SM"],
            "OpnPric": [100.0, 50.0, 900.0, 10.0],
            "HghPric": [105.0, 52.0, 910.0, 11.0],
            "LwPric": [99.0, 49.0, 890.0, 9.5],
            "ClsPric": [104.0, 51.0, 905.0, 10.5],
            "LastPric": [104.0, 51.0, 905.0, 10.5],
            "PrvsClsgPric": [98.0, 50.5, 900.0, 10.2],
            "TtlTradgVol": [1000, 2000, 3000, 4000],
            "TtlTrfVal": [104000.0, 102000.0, 2715000.0, 42000.0],
            "TtlNbOfTxsExctd": [10, 20, 30, 40],
        }
    )


def legacy_frame():
    """A legacy file, including the leading-space column NSE actually ships."""
    return pd.DataFrame(
        {
            "SYMBOL": ["ALPHA", "OLDCO"],
            " SERIES": ["EQ", "EQ"],
            "OPEN": [90.0, 5.0],
            "HIGH": [95.0, 5.5],
            "LOW": [89.0, 4.5],
            "CLOSE": [94.0, 5.2],
            "LAST": [94.0, 5.2],
            "PREVCLOSE": [88.0, 5.0],
            "TOTTRDQTY": [500, 600],
            "TOTTRDVAL": [47000.0, 3120.0],
            "TIMESTAMP": ["10-JAN-2024", "10-JAN-2024"],
            "TOTALTRADES": [5, 6],
            "ISIN": ["INE001A01036", "INE999Z01011"],
        }
    )


class DetectFormatTests(unittest.TestCase):
    def test_recognises_both_layouts(self):
        self.assertEqual(detect_format(udiff_frame()), "udiff")
        self.assertEqual(detect_format(legacy_frame()), "legacy")

    def test_unknown_layout_raises_rather_than_returning_empty(self):
        with self.assertRaises(ValueError):
            detect_format(pd.DataFrame({"Nonsense": [1]}))

    def test_udiff_switch_boundary(self):
        self.assertFalse(is_udiff_date(date(2024, 7, 5)))
        self.assertTrue(is_udiff_date(date(2024, 7, 8)))


class NormaliseTests(unittest.TestCase):
    def test_udiff_keeps_only_investable_equity_series(self):
        out = normalise_bhavcopy(udiff_frame(), date(2026, 8, 11))
        self.assertEqual(list(out["Symbol"]), ["ALPHA", "BETA"])

    def test_derivative_rows_are_excluded(self):
        out = normalise_bhavcopy(udiff_frame(), date(2026, 8, 11))
        self.assertNotIn("GAMMAFUT", set(out["Symbol"]))

    def test_sme_series_is_excluded(self):
        out = normalise_bhavcopy(udiff_frame(), date(2026, 8, 11))
        self.assertNotIn("DELTA", set(out["Symbol"]))

    def test_legacy_leading_space_column_is_handled(self):
        out = normalise_bhavcopy(legacy_frame(), date(2024, 1, 10))
        self.assertEqual(list(out["Series"]), ["EQ", "EQ"])

    def test_trade_date_comes_from_caller_not_file(self):
        out = normalise_bhavcopy(legacy_frame(), date(2024, 1, 10))
        self.assertEqual(set(out["Trade_Date"]), {"2024-01-10"})

    def test_both_layouts_produce_identical_schema(self):
        new = normalise_bhavcopy(udiff_frame(), date(2026, 8, 11))
        old = normalise_bhavcopy(legacy_frame(), date(2024, 1, 10))
        self.assertEqual(list(new.columns), list(old.columns))

    def test_prices_are_numeric(self):
        out = normalise_bhavcopy(udiff_frame(), date(2026, 8, 11))
        self.assertTrue(pd.api.types.is_numeric_dtype(out["Close"]))
        self.assertTrue(pd.api.types.is_numeric_dtype(out["Turnover_INR"]))

    def test_rows_without_usable_close_are_dropped(self):
        frame = udiff_frame()
        frame.loc[0, "ClsPric"] = 0.0
        out = normalise_bhavcopy(frame, date(2026, 8, 11))
        self.assertNotIn("ALPHA", set(out["Symbol"]))

    def test_rows_without_isin_are_dropped(self):
        frame = udiff_frame()
        frame.loc[0, "ISIN"] = "nan"
        out = normalise_bhavcopy(frame, date(2026, 8, 11))
        self.assertNotIn("ALPHA", set(out["Symbol"]))

    def test_duplicate_isin_collapses_to_one_row(self):
        frame = udiff_frame()
        frame.loc[1, "ISIN"] = frame.loc[0, "ISIN"]
        out = normalise_bhavcopy(frame, date(2026, 8, 11))
        self.assertEqual(out["ISIN"].nunique(), len(out))

    def test_missing_required_column_raises(self):
        frame = udiff_frame().drop(columns=["ClsPric"])
        with self.assertRaises(ValueError):
            normalise_bhavcopy(frame, date(2026, 8, 11))

    def test_empty_input_returns_empty_schema(self):
        out = normalise_bhavcopy(pd.DataFrame(), date(2026, 8, 11))
        self.assertTrue(out.empty)
        self.assertIn("ISIN", out.columns)


class StubNSE:
    """Stands in for nse.NSE, writing a fixture file instead of downloading."""

    def __init__(self, folder, frames):
        self.folder = Path(folder)
        self.frames = frames
        self.requested = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def equityBhavcopy(self, date):
        day = date.date() if hasattr(date, "date") else date
        self.requested.append(day)
        if day not in self.frames:
            raise RuntimeError("NSE file is unavailable or not yet updated.")
        path = self.folder / f"{day.isoformat()}.csv"
        self.frames[day].to_csv(path, index=False)
        return path


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.frames = {
            date(2026, 8, 11): udiff_frame(),
            date(2024, 1, 10): legacy_frame(),
        }
        self.calls = []

        def factory(folder):
            client = StubNSE(folder, self.frames)
            self.calls.append(client)
            return client

        self.store = BhavcopyStore(self.root, nse_factory=factory)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fetch_writes_a_gzipped_day_file(self):
        self.store.fetch_day(date(2026, 8, 11))
        path = self.store.day_path(date(2026, 8, 11))
        self.assertTrue(path.exists())
        with gzip.open(path, "rt") as handle:
            self.assertIn("ISIN", handle.readline())

    def test_day_files_are_sharded_by_year(self):
        path = self.store.day_path(date(2024, 1, 10))
        self.assertEqual(path.parent.name, "2024")

    def test_get_day_uses_cache_without_a_second_fetch(self):
        self.store.get_day(date(2026, 8, 11))
        self.store.get_day(date(2026, 8, 11))
        self.assertEqual(len(self.calls), 1)

    def test_unavailable_session_raises_for_the_caller_to_classify(self):
        with self.assertRaises(RuntimeError):
            self.store.fetch_day(date(2026, 8, 16))

    def test_cached_dates_lists_every_ingested_session(self):
        self.store.fetch_day(date(2026, 8, 11))
        self.store.fetch_day(date(2024, 1, 10))
        self.assertEqual(
            self.store.cached_dates(), [date(2024, 1, 10), date(2026, 8, 11)]
        )

    def test_round_trip_preserves_isin_as_text(self):
        self.store.fetch_day(date(2026, 8, 11))
        loaded = self.store.load_day(date(2026, 8, 11))
        self.assertEqual(loaded["ISIN"].iloc[0], "INE001A01036")


class CandidateSessionTests(unittest.TestCase):
    def test_weekends_are_never_candidates(self):
        days = candidate_sessions(date(2026, 8, 14), date(2026, 8, 17))
        self.assertEqual(days, [date(2026, 8, 14), date(2026, 8, 17)])

    def test_configured_holiday_is_skipped(self):
        days = candidate_sessions(
            date(2026, 8, 13), date(2026, 8, 14), market_holidays=["2026-08-14"]
        )
        self.assertEqual(days, [date(2026, 8, 13)])


if __name__ == "__main__":
    unittest.main()
