"""The exchange-bar fallback for a session the vendor has not served.

Regression for the NSE run of 5 Oct 2026: twenty hours after the close Yahoo
still had no bar for that session on two thirds of the universe (1 Oct, then
the live 6 Oct row, a hole between), and both attempts failed the alignment
guard. NSE's own bhavcopy for the day had the missing bars.
"""

import re
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from screener.data_collection import StockDataCollector
from screener.markets import resolve
from screener.session_bars import SessionBarSource, patch_expected_session_bar
from tests.test_markets import config_with_env_cleared

IST = ZoneInfo("Asia/Kolkata")
TZ = "Asia/Kolkata"
EXPECTED = date(2026, 10, 5)
HOLIDAYS = ("2026-10-02",)


def _history(*, hole=True, live_row=True, periods=80):
    """Yahoo-shaped daily frame ending 1 Oct, with 5 Oct unfilled or absent."""
    dates = pd.bdate_range(end="2026-10-01", periods=periods)
    closes = [100.0 + position for position in range(periods)]
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Adj Close": closes,
            "Volume": [100_000.0 + position for position in range(periods)],
        },
        index=dates,
    )
    if hole:
        # The batch's union index: another ticker had the session, this one not.
        frame.loc[pd.Timestamp("2026-10-05")] = np.nan
    if live_row:
        frame.loc[pd.Timestamp("2026-10-06")] = [190.0, 191.0, 189.0, 190.5, 190.5, 5_000.0]
    return frame


def _bar(**overrides):
    bar = {
        "Symbol": "EXAMPLE",
        "Open": 180.0,
        "High": 184.0,
        "Low": 179.0,
        "Close": 182.0,
        "Prev_Close": 179.0,  # the 1 Oct close in _history()
        "Volume": 250_000,
    }
    bar.update(overrides)
    return bar


def _patch(frame, bar):
    return patch_expected_session_bar(frame, EXPECTED, TZ, lambda: bar)


class PatchExpectedSessionBarTests(unittest.TestCase):
    def test_unfilled_row_takes_the_exchange_bar(self):
        patched, did = _patch(_history(), _bar())

        self.assertTrue(did)
        row = patched.loc[pd.Timestamp("2026-10-05")]
        self.assertEqual(
            [row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]],
            [180.0, 184.0, 179.0, 182.0, 250_000.0],
        )
        self.assertEqual(row["Adj Close"], 182.0)
        # Nothing else moved, including the live row after it.
        self.assertEqual(patched.loc[pd.Timestamp("2026-10-06"), "Close"], 190.5)
        self.assertEqual(len(patched), len(_history()))

    def test_absent_row_is_inserted_in_date_order(self):
        patched, did = _patch(_history(hole=False), _bar())

        self.assertTrue(did)
        self.assertTrue(patched.index.is_monotonic_increasing)
        self.assertEqual(
            [stamp.date().isoformat() for stamp in patched.index[-3:]],
            ["2026-10-01", "2026-10-05", "2026-10-06"],
        )

    def test_timezone_aware_index_gets_a_matching_label(self):
        frame = _history(hole=False, live_row=False).tz_localize(TZ)

        patched, did = _patch(frame, _bar())

        self.assertTrue(did)
        self.assertEqual(str(patched.index.tz), TZ)
        self.assertEqual(patched.index[-1].date(), EXPECTED)

    def test_adjusted_close_keeps_the_previous_bars_factor(self):
        frame = _history()
        frame["Adj Close"] = frame["Close"] / 2.0

        patched, _ = _patch(frame, _bar())

        self.assertEqual(patched.loc[pd.Timestamp("2026-10-05"), "Adj Close"], 91.0)

    def test_a_bar_the_vendor_already_has_is_not_touched_or_looked_up(self):
        frame = _history()
        frame.loc[pd.Timestamp("2026-10-05")] = [1.0, 1.0, 1.0, 181.0, 181.0, 9.0]

        def lookup():
            raise AssertionError("the exchange must not be asked")

        patched, did = patch_expected_session_bar(frame, EXPECTED, TZ, lookup)

        self.assertFalse(did)
        self.assertIs(patched, frame)

    def test_previous_close_mismatch_is_not_patched(self):
        # More than one session missing, or the two sources on different scales.
        _, did = _patch(_history(), _bar(Prev_Close=175.0))
        self.assertFalse(did)

    def test_a_move_that_could_be_an_unapplied_split_is_not_patched(self):
        _, did = _patch(_history(), _bar(Close=89.5))
        self.assertFalse(did)

    def test_symbol_absent_from_the_exchange_file_is_left_alone(self):
        frame = _history()
        patched, did = _patch(frame, None)
        self.assertFalse(did)
        self.assertIs(patched, frame)

    def test_untraded_or_malformed_bar_is_not_patched(self):
        for bad in ({"Volume": 0}, {"Close": None}, {"Prev_Close": float("nan")}):
            with self.subTest(bad=bad):
                self.assertFalse(_patch(_history(), _bar(**bad))[1])


class SessionBarSourceTests(unittest.TestCase):
    def test_fetches_once_and_only_when_asked(self):
        calls = []

        def loader(session, cache_root):
            calls.append((session, cache_root))
            return pd.DataFrame([_bar(), _bar(Symbol="other")])

        source = SessionBarSource("nse_bhavcopy", EXPECTED, "root", loader=loader)
        self.assertEqual(calls, [])
        self.assertEqual(source.bar("example")["Close"], 182.0)
        self.assertEqual(source.bar("OTHER")["Symbol"], "other")
        self.assertIsNone(source.bar("MISSING"))
        self.assertEqual(calls, [(EXPECTED, "root")])

    def test_unpublished_file_degrades_to_no_fallback(self):
        calls = []

        def loader(session, cache_root):
            calls.append(session)
            raise ConnectionError("bhavcopy not published yet")

        source = SessionBarSource("nse_bhavcopy", EXPECTED, "root", loader=loader)
        with self.assertLogs("screener.session_bars", level="WARNING"):
            self.assertIsNone(source.bar("EXAMPLE"))
        self.assertIsNone(source.bar("EXAMPLE"))
        self.assertEqual(len(calls), 1)


class CollectorFallbackTests(unittest.TestCase):
    NOW = datetime(2026, 10, 6, 11, 33, tzinfo=IST)  # attempt 2 of the failed run

    def _collect(self, *, enabled, bars=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.loader_calls = []

        def loader(session, cache_root):
            self.loader_calls.append(session)
            return pd.DataFrame(bars if bars is not None else [_bar()])

        config = SimpleNamespace(
            OUTPUT_DIR=Path(directory.name),
            PRICE_CACHE_MAX_AGE_HOURS=18,
            FUND_CACHE_MAX_AGE_DAYS=7,
            FACTOR_MODEL_ENABLED=False,
            NSE_MARKET_HOLIDAYS=HOLIDAYS,
            PRICE_BAR_FALLBACK_ENABLED=enabled,
        )
        self.collector = StockDataCollector(
            config, clock=lambda: self.NOW, session_bar_loader=loader
        )
        with patch("screener.data_collection.yf.download", return_value=_history()):
            return self.collector.download_stock_data(["EXAMPLE"])

    def test_vendor_gap_is_filled_and_the_row_is_aligned(self):
        with self.assertLogs("screener.data_collection", level="WARNING") as logs:
            result = self._collect(enabled=True)

        row = result.iloc[0]
        self.assertEqual(row["Price_Bar_As_Of"], "2026-10-05")
        self.assertEqual(row["Expected_Price_Bar_As_Of"], "2026-10-05")
        self.assertTrue(row["Price_Bar_Aligned"])
        self.assertEqual(row["Current_Price"], 182.0)
        self.assertEqual(row["Latest_Volume"], 250_000)
        self.assertEqual(
            self.collector.collection_diagnostics[
                "technical_session_bar_patched_symbols"
            ],
            ["EXAMPLE"],
        )
        self.assertTrue(any("nse_bhavcopy" in line for line in logs.output))

    def test_disabled_keeps_the_symbol_one_session_behind(self):
        result = self._collect(enabled=False)

        row = result.iloc[0]
        self.assertEqual(row["Price_Bar_As_Of"], "2026-10-01")
        self.assertFalse(row["Price_Bar_Aligned"])
        self.assertEqual(self.loader_calls, [])
        self.assertEqual(
            self.collector.collection_diagnostics[
                "technical_session_bar_patched_symbols"
            ],
            [],
        )

    def test_symbol_the_exchange_did_not_trade_stays_behind(self):
        result = self._collect(enabled=True, bars=[_bar(Symbol="SOMEONEELSE")])

        self.assertEqual(result.iloc[0]["Price_Bar_As_Of"], "2026-10-01")
        self.assertEqual(self.loader_calls, [EXPECTED])


class FallbackWiringTests(unittest.TestCase):
    def test_off_unless_a_workflow_opts_in(self):
        # The NSE workflow sets the flag at job level and it leaks into its
        # regression-test step, so the default is read with the variable cleared.
        Config = config_with_env_cleared("PRICE_BAR_FALLBACK_ENABLED")
        self.assertIs(Config.PRICE_BAR_FALLBACK_ENABLED, False)

    def test_only_nse_has_an_exchange_source(self):
        self.assertEqual(resolve("NSE").session_bar_fallback, "nse_bhavcopy")
        self.assertIsNone(resolve("US").session_bar_fallback)

    def test_the_nse_workflow_opts_in(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        pattern = re.compile(r'PRICE_BAR_FALLBACK_ENABLED:\s*"True"')
        self.assertRegex((workflows / "daily-stock-screener.yml").read_text(), pattern)


if __name__ == "__main__":
    unittest.main()
