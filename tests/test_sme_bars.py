"""SME names Yahoo lacks are priced from the exchange's daily files."""

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from screener.data_collection import StockDataCollector
from screener.price_basis import restate_price_basis
from screener.session_bars import carry_quiet_session
from screener.sme_bars import SmeBarHistory
from tests.test_session_bars import HOLIDAYS, _history

TZ = "Asia/Kolkata"
EXPECTED = date(2026, 10, 5)
NOW = datetime(2026, 10, 6, 11, 33, tzinfo=ZoneInfo(TZ))


def _day_frame(session):
    close = 100.0 + session.toordinal() % 50
    row = {
        "Trade_Date": session.isoformat(), "Symbol": "SMEONE", "Open": close, "High": close + 1,
        "Low": close - 1, "Close": close, "Volume": 10_000,
    }
    return pd.DataFrame([row, {**row, "Symbol": "SMETWO"}])


class SmeBarHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "sme_bars.csv.gz"
        self.fetched = []

    def _history(self, **kwargs):
        def fetch(day):
            self.fetched.append(day)
            return _day_frame(day)

        return SmeBarHistory(
            self.path, EXPECTED, TZ, market_holidays=HOLIDAYS, history_days=30, fetch_day=fetch, **kwargs
        )

    def test_bars_are_yahoo_shaped_and_skip_holidays_and_weekends(self):
        bars = self._history().bars("smeone")
        self.assertEqual(list(bars.columns), ["Open", "High", "Low", "Close", "Adj Close", "Volume"])
        self.assertEqual(str(bars.index.tz), TZ)
        self.assertEqual(bars.index[-1].date(), EXPECTED)
        self.assertTrue((bars["Adj Close"] == bars["Close"]).all())
        self.assertNotIn(date(2026, 10, 2), self.fetched)  # listed holiday
        self.assertTrue(all(day.weekday() < 5 for day in self.fetched))

    def test_a_later_run_fetches_only_the_new_session(self):
        self._history().bars("SMEONE")
        self.fetched.clear()
        later = SmeBarHistory(
            self.path, date(2026, 10, 6), TZ, market_holidays=HOLIDAYS, history_days=30,
            fetch_day=lambda day: (self.fetched.append(day), _day_frame(day))[1],
        )
        later.bars("SMEONE")
        self.assertEqual(self.fetched, [date(2026, 10, 6)])

    def test_unknown_symbol_and_failed_fetch_give_none(self):
        self.assertIsNone(self._history().bars("NOSUCH"))

        def broken(day):
            raise ConnectionError("down")

        failing = SmeBarHistory(self.path.with_name("x.csv.gz"), EXPECTED, TZ, fetch_day=broken)
        self.assertIsNone(failing.bars("SMEONE"))

    def test_an_unapplied_bonus_is_restated_by_the_price_basis_rule(self):
        frame = self._history().bars("SMEONE")
        before = frame["Adj Close"].iloc[-4]
        frame.iloc[-3:, :5] = frame.iloc[-3:, :5] / 2  # 1:1 bonus, open halves
        restated, changes = restate_price_basis(frame, (), TZ, max_open_gap=1.3)
        self.assertTrue(changes)
        self.assertAlmostEqual(restated["Adj Close"].iloc[-4], before / 2, delta=1.0)  # not a 50% crash


class FakeHistory:
    def __init__(self, frame):
        self.frame = frame
        self.asked = []

    def bars(self, symbol):
        self.asked.append(symbol)
        return self.frame


class CollectorSmeTests(unittest.TestCase):
    def _collect(self, yahoo, history, *, sme):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = SimpleNamespace(
            OUTPUT_DIR=Path(directory.name), PRICE_CACHE_MAX_AGE_HOURS=18, FUND_CACHE_MAX_AGE_DAYS=7,
            FACTOR_MODEL_ENABLED=False, NSE_MARKET_HOLIDAYS=HOLIDAYS,
        )
        collector = StockDataCollector(config, clock=lambda: NOW, sme_bar_history=history)
        collector.sme_symbols = frozenset(sme)
        with patch("screener.data_collection.yf.download", return_value=yahoo):
            return collector, collector.download_stock_data(["EXAMPLE"])

    def _bars(self):
        frame = _history(hole=False, live_row=False)
        frame.loc[pd.Timestamp("2026-10-05")] = [182.0, 183.0, 181.0, 182.0, 182.0, 250_000.0]
        frame.index = frame.index.tz_localize(TZ)
        return frame

    def test_yahoo_gap_is_filled_for_an_sme_name(self):
        history = FakeHistory(self._bars())
        collector, result = self._collect(pd.DataFrame(), history, sme={"EXAMPLE"})
        self.assertEqual(result.iloc[0]["Symbol"], "EXAMPLE")
        self.assertEqual(result.iloc[0]["Current_Price"], 182.0)
        self.assertEqual(
            collector.collection_diagnostics["technical_sme_bhavcopy_priced_symbols"], ["EXAMPLE"]
        )

    def test_a_ticker_yahoo_failed_as_an_all_nan_block_is_filled(self):
        # yfinance returns a failed ticker as a column block of NaN, so ``.empty`` is False.
        nan = _history(hole=False, live_row=False) * float("nan")
        yahoo = pd.concat({"EXAMPLE.NS": nan}, axis=1)
        history = FakeHistory(self._bars())
        collector, result = self._collect(yahoo, history, sme={"EXAMPLE"})
        self.assertEqual(history.asked, ["EXAMPLE"])
        self.assertEqual(
            collector.collection_diagnostics["technical_sme_bhavcopy_priced_symbols"], ["EXAMPLE"]
        )

    def test_an_sme_name_with_years_old_yahoo_bars_takes_the_exchange_bars(self):
        stale = _history(hole=False, live_row=False)
        stale.index = stale.index - pd.DateOffset(years=2)
        history = FakeHistory(self._bars())
        collector, result = self._collect(pd.concat({"EXAMPLE.NS": stale}, axis=1), history, sme={"EXAMPLE"})
        self.assertEqual(result.iloc[0]["Current_Price"], 182.0)
        self.assertEqual(
            collector.collection_diagnostics["technical_sme_bhavcopy_priced_symbols"], ["EXAMPLE"]
        )

    def test_stale_yahoo_bars_with_no_exchange_bars_are_dropped_not_scored(self):
        stale = _history(hole=False, live_row=False)
        stale.index = stale.index - pd.DateOffset(years=2)
        _, result = self._collect(pd.concat({"EXAMPLE.NS": stale}, axis=1), FakeHistory(None), sme={"EXAMPLE"})
        self.assertTrue(result.empty)

    def test_an_sme_name_whose_yahoo_bars_stop_short_of_the_session_takes_the_exchange_bars(self):
        # Yahoo does not carry a quiet SME name forward; the exchange file has the session.
        history = FakeHistory(self._bars())
        collector, result = self._collect(
            pd.concat({"EXAMPLE.NS": _history(hole=False, live_row=False)}, axis=1), history, sme={"EXAMPLE"}
        )
        self.assertEqual(result.iloc[0]["Price_Bar_As_Of"], EXPECTED.isoformat())
        self.assertEqual(
            collector.collection_diagnostics["technical_sme_bhavcopy_priced_symbols"], ["EXAMPLE"]
        )

    def test_a_lagging_sme_name_the_exchange_does_not_have_keeps_yahoos_bars(self):
        _, result = self._collect(
            pd.concat({"EXAMPLE.NS": _history(hole=False, live_row=False, periods=120)}, axis=1),
            FakeHistory(None),
            sme={"EXAMPLE"},
        )
        self.assertTrue(result.empty)  # as before: behind the session, it leaves to the cache fallback

    def test_stale_bars_of_a_mainboard_name_are_left_alone(self):
        stale = _history(hole=False, live_row=False)
        stale.index = stale.index - pd.DateOffset(years=2)
        history = FakeHistory(self._bars())
        self._collect(pd.concat({"EXAMPLE.NS": stale}, axis=1), history, sme=set())
        self.assertEqual(history.asked, [])

    def test_a_mainboard_name_is_never_given_exchange_bars(self):
        history = FakeHistory(self._bars())
        _, result = self._collect(pd.DataFrame(), history, sme=set())
        self.assertTrue(result.empty)
        self.assertEqual(history.asked, [])

    def test_yahoo_stays_the_source_where_it_serves(self):
        history = FakeHistory(self._bars())
        collector, _ = self._collect(self._bars(), history, sme={"EXAMPLE"})
        self.assertEqual(history.asked, [])
        self.assertEqual(collector.collection_diagnostics["technical_sme_bhavcopy_priced_symbols"], [])


class CarryForwardTests(unittest.TestCase):
    def test_an_untraded_session_keeps_its_bar_with_zero_volume(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        def fetch(day):
            frame = _day_frame(day)
            if day == date(2026, 10, 1):  # SMETWO does not trade
                frame = frame[frame["Symbol"] == "SMEONE"]
            return frame

        history = SmeBarHistory(
            Path(directory.name) / "b.csv.gz", EXPECTED, TZ, market_holidays=HOLIDAYS,
            history_days=10, fetch_day=fetch,
        )
        bars = history.bars("SMETWO")
        gap = bars.loc[bars.index.date == date(2026, 10, 1)].iloc[0]
        self.assertEqual(gap["Volume"], 0.0)
        self.assertEqual(gap["Close"], bars["Close"].iloc[list(bars.index.date).index(date(2026, 10, 1)) - 1])
        self.assertEqual(bars.index[-1].date(), EXPECTED)


class FetchFailureTests(unittest.TestCase):
    def test_an_unreachable_exchange_stops_after_a_few_tries(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        calls = []

        def down(day):
            calls.append(day)
            raise TimeoutError("NSE")

        history = SmeBarHistory(Path(directory.name) / "b.csv.gz", EXPECTED, TZ, fetch_day=down)
        with self.assertLogs("screener.sme_bars", level="WARNING"):
            self.assertIsNone(history.bars("SMEONE"))
        self.assertEqual(len(calls), 10)


    def test_holidays_between_stored_sessions_are_not_an_exchange_refusing_us(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "b.csv.gz"
        sessions = [date(2026, 9, 7) + timedelta(days=n) for n in range(0, 28) if (date(2026, 9, 7) + timedelta(days=n)).weekday() < 5]
        holidays = set(sessions[1::2])  # every other session is a holiday the calendar lacks
        pd.concat([_day_frame(d) for d in sessions if d not in holidays]).rename(
            columns={"Trade_Date": "Date"}
        ).to_csv(path, index=False, compression="gzip")
        calls = []

        def fetch(day):
            calls.append(day)
            raise TimeoutError("holiday")

        history = SmeBarHistory(path, date(2026, 10, 2), TZ, history_days=25, max_consecutive_misses=3, fetch_day=fetch)
        history.bars("SMEONE")
        self.assertEqual(set(calls), holidays)


class QuietBseSessionTests(unittest.TestCase):
    """A BSE name its exchange file shows did not trade is a quiet session, not a lag."""

    def _collect(self, *, traded, session="2026-10-05"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = SimpleNamespace(
            OUTPUT_DIR=Path(directory.name), PRICE_CACHE_MAX_AGE_HOURS=18, FUND_CACHE_MAX_AGE_DAYS=7,
            FACTOR_MODEL_ENABLED=False, NSE_MARKET_HOLIDAYS=HOLIDAYS,
        )
        collector = StockDataCollector(config, clock=lambda: NOW)
        collector.bse_session, collector.bse_traded = session, frozenset(traded)
        yahoo = pd.concat({"EXAMPLE.BO": _history(hole=False, live_row=False, periods=120)}, axis=1)
        with patch("screener.data_collection.yf.download", return_value=yahoo):
            return collector, collector.download_stock_data(["EXAMPLE.BO"])

    def test_a_name_not_in_the_exchange_file_is_carried_to_the_session_at_zero_volume(self):
        collector, result = self._collect(traded=set())
        self.assertEqual(result.iloc[0]["Price_Bar_As_Of"], EXPECTED.isoformat())
        self.assertEqual(
            collector.collection_diagnostics["technical_quiet_session_carried_symbols"], ["EXAMPLE.BO"]
        )

    def test_a_name_the_exchange_traded_but_yahoo_lacks_is_left_behind(self):
        collector, result = self._collect(traded={"EXAMPLE.BO"})
        self.assertTrue(result.empty)
        self.assertEqual(collector.collection_diagnostics["technical_quiet_session_carried_symbols"], [])

    def test_without_the_sessions_exchange_file_nothing_is_carried(self):
        _, result = self._collect(traded=set(), session="2026-10-01")
        self.assertTrue(result.empty)

    def test_a_last_bar_older_than_a_week_is_stale_not_quiet(self):
        old = _history(hole=False, live_row=False)
        old.index = old.index - pd.DateOffset(days=14)
        frame, carried = carry_quiet_session(old, EXPECTED, TZ, 7)
        self.assertFalse(carried)
        self.assertIs(frame, old)


class DisplayOnlyTests(unittest.TestCase):
    """An SME name with a price but under the session minimum is shown, not scored."""

    def test_a_short_history_sme_is_kept_aside_not_in_the_scored_frame(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = SimpleNamespace(
            OUTPUT_DIR=Path(directory.name), PRICE_CACHE_MAX_AGE_HOURS=18, FUND_CACHE_MAX_AGE_DAYS=7,
            FACTOR_MODEL_ENABLED=False, NSE_MARKET_HOLIDAYS=HOLIDAYS,
        )
        collector = StockDataCollector(config, clock=lambda: NOW)
        collector.sme_symbols = frozenset({"EXAMPLE"})
        collector.sme_names = {"EXAMPLE": "Example Ltd"}
        yahoo = pd.concat({"EXAMPLE.NS": _history(hole=False, live_row=False, periods=30)}, axis=1)
        yahoo.loc[pd.Timestamp("2026-10-05"), :] = yahoo.iloc[-1].to_numpy()
        with patch("screener.data_collection.yf.download", return_value=yahoo):
            result = collector.download_stock_data(["EXAMPLE"])
        self.assertTrue(result.empty)
        record = collector.display_only[0]
        self.assertEqual((record["Symbol"], record["Company"]), ("EXAMPLE", "Example Ltd"))
        self.assertEqual(record["Price_History_Sessions"], 31)
        self.assertEqual(collector.collection_diagnostics["technical_display_only_symbols"], ["EXAMPLE"])
