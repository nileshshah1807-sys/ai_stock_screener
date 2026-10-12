"""Restating price history across a demerger.

Regression for October 2026: a parent going ex-demerger fell by the value of
the business carved out of it, and the site showed a 90% loss and a Stage 3
label for a company whose holders had lost nothing. Yahoo applies no adjustment
to an NSE demerger and the chart's ledger carries no ratio for one, so both the
screener and the chart read the price cut as a crash -- for every demerged
parent, for as long as the ex-date stayed in the history window.
"""

import re
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.corporate_actions import (
    ACTION_DEMERGER,
    AdjustmentTable,
    demerger_price_factor,
)
from screener.data_collection import StockDataCollector
from screener.demergers import (
    STATUS_NOT_LOADED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    DemergerLedger,
    restate_for_demergers,
)
from screener.markets import resolve
from tests.test_markets import config_with_env_cleared
from workers.price_series_publisher import apply_demerger_factors

IST = ZoneInfo("Asia/Kolkata")
TZ = "Asia/Kolkata"
EX_DATE = date(2026, 9, 21)
HOLIDAYS = ("2026-10-02",)


def _history(*, periods=80, pre=400.0, post=100.0, ex_open=None):
    """Yahoo-shaped frame: flat at ``pre``, then flat at ``post`` from EX_DATE."""
    dates = pd.bdate_range(end="2026-10-05", periods=periods)
    closes = [post if stamp.date() >= EX_DATE else pre for stamp in dates]
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": [value * 1.01 for value in closes],
            "Low": [value * 0.99 for value in closes],
            "Close": closes,
            # A dividend already in the vendor's adjustment must survive.
            "Adj Close": [value * 0.98 for value in closes],
            "Volume": [100_000.0] * periods,
        },
        index=dates,
    )
    if ex_open is not None:
        frame.loc[pd.Timestamp(EX_DATE), "Open"] = ex_open
    return frame


class PriceFactorTests(unittest.TestCase):
    def test_the_factor_is_the_previous_close_over_the_ex_date_open(self):
        self.assertAlmostEqual(demerger_price_factor(471.5, 289.95), 1.6261, places=4)

    def test_an_open_at_or_above_the_previous_close_is_not_a_ratio(self):
        self.assertIsNone(demerger_price_factor(100.0, 100.0))
        self.assertIsNone(demerger_price_factor(100.0, 104.0))

    def test_missing_or_zero_prices_give_no_factor(self):
        for prev_close, ex_open in ((None, 50.0), (100.0, None), (0, 50.0), (100.0, 0), ("x", 50.0)):
            self.assertIsNone(demerger_price_factor(prev_close, ex_open))


class RestateTests(unittest.TestCase):
    def test_history_before_the_ex_date_is_restated_onto_the_new_basis(self):
        frame = _history()
        restated, applied = restate_for_demergers(frame, (EX_DATE,), TZ)

        self.assertEqual(applied, [(EX_DATE, 4.0)])
        before = restated.index < pd.Timestamp(EX_DATE)
        self.assertTrue((restated.loc[before, "Adj Close"].round(6) == 98.0).all())
        self.assertTrue((restated.loc[~before, "Adj Close"].round(6) == 98.0).all())

    def test_raw_prices_are_left_alone(self):
        # Turnover is priced on the raw close; restating it would cut it fourfold.
        frame = _history()
        restated, _ = restate_for_demergers(frame, (EX_DATE,), TZ)
        for column in ("Open", "High", "Low", "Close", "Volume"):
            pd.testing.assert_series_equal(restated[column], frame[column])

    def test_the_input_frame_is_not_modified(self):
        frame = _history()
        snapshot = frame.copy()
        restate_for_demergers(frame, (EX_DATE,), TZ)
        pd.testing.assert_frame_equal(frame, snapshot)

    def test_a_symbol_with_no_demerger_comes_back_untouched(self):
        frame = _history()
        restated, applied = restate_for_demergers(frame, (), TZ)
        self.assertIs(restated, frame)
        self.assertEqual(applied, [])

    def test_the_open_prices_the_demerger_not_the_close(self):
        # The stock opened at 200 and then sold off to 100: half the fall was
        # the demerger and half was the market, and only the first is restated.
        frame = _history(ex_open=200.0)
        restated, applied = restate_for_demergers(frame, (EX_DATE,), TZ)
        self.assertEqual(applied, [(EX_DATE, 2.0)])
        self.assertAlmostEqual(restated["Adj Close"].iloc[0], 400.0 * 0.98 / 2.0)

    def test_an_ex_date_with_no_price_cut_restates_nothing(self):
        frame = _history(pre=100.0, post=100.0)
        restated, applied = restate_for_demergers(frame, (EX_DATE,), TZ)
        self.assertIs(restated, frame)
        self.assertEqual(applied, [])

    def test_an_ex_date_before_the_history_restates_nothing(self):
        frame = _history()
        restated, applied = restate_for_demergers(frame, (date(2020, 1, 6),), TZ)
        self.assertIs(restated, frame)
        self.assertEqual(applied, [])

    def test_an_ex_date_bar_not_yet_served_restates_nothing(self):
        frame = _history()
        frame = frame[frame.index < pd.Timestamp(EX_DATE)]
        restated, applied = restate_for_demergers(frame, (EX_DATE,), TZ)
        self.assertIs(restated, frame)
        self.assertEqual(applied, [])

    def test_a_parent_suspended_past_its_ex_date_is_priced_from_its_first_bar(self):
        frame = _history()
        suspended = [pd.Timestamp("2026-09-21"), pd.Timestamp("2026-09-22")]
        frame = frame.drop(index=suspended)
        _, applied = restate_for_demergers(frame, (EX_DATE,), TZ)
        self.assertEqual(applied, [(date(2026, 9, 23), 4.0)])

    def test_a_first_bar_weeks_after_the_ex_date_is_not_trusted(self):
        frame = _history(periods=120)
        _, applied = restate_for_demergers(frame, (date(2026, 8, 22),), TZ)
        self.assertEqual(applied, [])
        gap = frame[(frame.index < "2026-08-22") | (frame.index >= "2026-09-21")]
        _, applied = restate_for_demergers(gap, (date(2026, 8, 22),), TZ)
        self.assertEqual(applied, [])

    def test_two_demergers_compound(self):
        dates = pd.bdate_range(end="2026-10-05", periods=60)
        first, second = dates[20].date(), dates[40].date()
        closes = [
            50.0 if stamp.date() >= second else 100.0 if stamp.date() >= first else 400.0
            for stamp in dates
        ]
        frame = pd.DataFrame(
            {"Open": closes, "Close": closes, "Adj Close": closes, "Volume": 1.0},
            index=dates,
        )
        restated, applied = restate_for_demergers(frame, (second, first), TZ)
        self.assertEqual(applied, [(first, 4.0), (second, 2.0)])
        self.assertTrue((restated["Adj Close"].round(6) == 50.0).all())

    def test_a_timezone_aware_index_is_read_in_market_time(self):
        frame = _history()
        frame.index = frame.index.tz_localize(TZ).tz_convert("UTC")
        _, applied = restate_for_demergers(frame, (EX_DATE,), TZ)
        self.assertEqual(applied, [(EX_DATE, 4.0)])


class LedgerTests(unittest.TestCase):
    START, END = date(2024, 8, 1), date(2026, 10, 6)

    def test_ex_dates_are_served_per_symbol_from_one_fetch(self):
        calls = []

        def loader(start, end):
            calls.append((start, end))
            return [("example", EX_DATE), ("EXAMPLE", date(2025, 3, 3)), ("OTHER", EX_DATE)]

        ledger = DemergerLedger("nse_actions", self.START, self.END, loader=loader)
        self.assertEqual(ledger.status, STATUS_NOT_LOADED)
        self.assertEqual(ledger.ex_dates("Example"), (date(2025, 3, 3), EX_DATE))
        self.assertEqual(ledger.ex_dates("NOBODY"), ())
        self.assertEqual(calls, [(self.START, self.END)])
        self.assertEqual(ledger.status, STATUS_OK)

    def test_a_failed_fetch_is_reported_once_and_adjusts_nothing(self):
        calls = []

        def loader(start, end):
            calls.append(start)
            raise ConnectionError("exchange unreachable")

        ledger = DemergerLedger("nse_actions", self.START, self.END, loader=loader)
        with self.assertLogs("screener.demergers", level="WARNING"):
            self.assertEqual(ledger.ex_dates("EXAMPLE"), ())
        self.assertEqual(ledger.ex_dates("EXAMPLE"), ())
        self.assertEqual(len(calls), 1)
        self.assertEqual(ledger.status, STATUS_UNAVAILABLE)


class CollectorTests(unittest.TestCase):
    NOW = datetime(2026, 10, 6, 11, 33, tzinfo=IST)

    def _collect(self, *, enabled, pairs=(("EXAMPLE", EX_DATE),)):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.loader_calls = []

        def loader(start, end):
            self.loader_calls.append((start, end))
            return list(pairs)

        config = SimpleNamespace(
            OUTPUT_DIR=Path(directory.name),
            PRICE_CACHE_MAX_AGE_HOURS=18,
            FUND_CACHE_MAX_AGE_DAYS=7,
            FACTOR_MODEL_ENABLED=False,
            NSE_MARKET_HOLIDAYS=HOLIDAYS,
            DEMERGER_ADJUSTMENT_ENABLED=enabled,
        )
        self.collector = StockDataCollector(
            config, clock=lambda: self.NOW, demerger_loader=loader
        )
        with patch("screener.data_collection.yf.download", return_value=_history()):
            return self.collector.download_stock_data(["EXAMPLE"]).iloc[0]

    def test_a_demerged_parent_is_not_scored_as_a_crash(self):
        row = self._collect(enabled=True)

        self.assertEqual(row["Pct_Change_1M"], 0.0)
        self.assertEqual(row["Pct_Change_3M"], 0.0)
        # The traded price is still the price.
        self.assertEqual(row["Current_Price"], 100.0)
        diagnostics = self.collector.collection_diagnostics
        self.assertEqual(diagnostics["technical_demerger_restated_symbols"], ["EXAMPLE"])
        self.assertEqual(diagnostics["technical_demerger_ledger_status"], STATUS_OK)

    def test_disabled_leaves_the_vendor_history_and_never_asks_the_exchange(self):
        row = self._collect(enabled=False)

        self.assertEqual(row["Pct_Change_1M"], -75.0)
        self.assertEqual(self.loader_calls, [])
        diagnostics = self.collector.collection_diagnostics
        self.assertEqual(diagnostics["technical_demerger_restated_symbols"], [])
        self.assertEqual(diagnostics["technical_demerger_ledger_status"], "disabled")

    def test_a_fall_the_ledger_does_not_name_stays_a_fall(self):
        row = self._collect(enabled=True, pairs=(("SOMEONEELSE", EX_DATE),))

        self.assertEqual(row["Pct_Change_1M"], -75.0)
        self.assertEqual(
            self.collector.collection_diagnostics["technical_demerger_restated_symbols"],
            [],
        )


class WiringTests(unittest.TestCase):
    def test_off_unless_a_workflow_opts_in(self):
        # The NSE workflow sets the flag at job level and it leaks into its
        # regression-test step, so the default is read with the variable cleared.
        Config = config_with_env_cleared("DEMERGER_ADJUSTMENT_ENABLED")
        self.assertIs(Config.DEMERGER_ADJUSTMENT_ENABLED, False)

    def test_only_nse_has_a_ledger(self):
        self.assertEqual(resolve("NSE").demerger_ledger, "nse_actions")
        self.assertIsNone(resolve("US").demerger_ledger)

    def test_the_nse_workflow_opts_in(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        pattern = re.compile(r'DEMERGER_ADJUSTMENT_ENABLED:\s*"True"')
        self.assertRegex((workflows / "daily-stock-screener.yml").read_text(), pattern)


class _Store:
    def __init__(self, days):
        self.days = days

    def load_day(self, day):
        rows = self.days.get(day)
        return pd.DataFrame(rows) if rows else None


class _Master:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def security_id_for_isin(self, isin):
        return self.mapping.get(isin)


def _actions(*rows):
    return pd.DataFrame(
        [
            {
                "ISIN": isin,
                "Symbol": symbol,
                "Ex_Date": ex_date,
                "Action_Type": action,
                "Price_Factor": None,
                "Dividend_Per_Share": None,
                "Subject": "Demerger",
                "Parse_Status": "unadjustable",
            }
            for isin, symbol, ex_date, action in rows
        ]
    )


def _day(isin, prev_close, open_price, symbol="EXAMPLE"):
    return [{"ISIN": isin, "Symbol": symbol, "Prev_Close": prev_close, "Open": open_price}]


class ChartFactorTests(unittest.TestCase):
    SESSIONS = [date(2026, 9, day) for day in (17, 18, 21, 22, 23)]
    ISIN = "INE000A01010"

    def _apply(self, days, *, actions=None, master=None):
        actions = actions if actions is not None else _actions(
            (self.ISIN, "EXAMPLE", "2026-09-21", ACTION_DEMERGER)
        )
        master = master or _Master()
        table = AdjustmentTable(actions, master=master)
        applied, unpriced = apply_demerger_factors(
            _Store(days), self.SESSIONS, actions, master, table
        )
        return table, applied, unpriced

    def test_prices_before_the_ex_date_are_divided_by_the_factor(self):
        table, applied, unpriced = self._apply(
            {date(2026, 9, 21): _day(self.ISIN, 400.0, 100.0)}
        )

        self.assertEqual(applied, [("EXAMPLE", date(2026, 9, 21), 4.0)])
        self.assertEqual(unpriced, [])
        self.assertEqual(table.price_factor(self.ISIN, date(2026, 9, 18)), 4.0)
        self.assertEqual(table.price_factor(self.ISIN, date(2026, 9, 21)), 1.0)

    def test_the_backtest_still_excludes_the_position(self):
        # The factor is for drawing. A holding period spanning the demerger must
        # stay blocked: the carved-out company's return is not in this series.
        table, _, _ = self._apply({date(2026, 9, 21): _day(self.ISIN, 400.0, 100.0)})
        self.assertTrue(
            table.is_blocked(self.ISIN, date(2026, 9, 17), date(2026, 9, 23))
        )

    def test_a_parent_suspended_on_its_ex_date_is_priced_when_it_trades(self):
        table, applied, _ = self._apply(
            {
                date(2026, 9, 21): _day("INE999Z01019", 10.0, 10.0, symbol="OTHER"),
                date(2026, 9, 23): _day(self.ISIN, 400.0, 200.0),
            }
        )

        self.assertEqual(applied, [("EXAMPLE", date(2026, 9, 23), 2.0)])
        self.assertEqual(table.price_factor(self.ISIN, date(2026, 9, 22)), 2.0)

    def test_an_isin_replaced_since_the_feed_was_written_still_matches(self):
        # The feed quoted the ISIN from before a face-value split.
        traded = "INE000A01028"
        master = _Master({self.ISIN: "INE000A01", traded: "INE000A01"})
        table, applied, unpriced = self._apply(
            {date(2026, 9, 21): _day(traded, 400.0, 100.0)}, master=master
        )

        self.assertEqual(len(applied), 1)
        self.assertEqual(unpriced, [])
        self.assertEqual(table.price_factor("INE000A01", date(2026, 9, 18)), 4.0)

    def test_a_demerger_with_no_bar_is_reported_and_left_unadjusted(self):
        with self.assertLogs("workers.price_series_publisher", level="WARNING"):
            table, applied, unpriced = self._apply({})

        self.assertEqual(applied, [])
        self.assertEqual(unpriced, ["EXAMPLE"])
        self.assertEqual(table.price_factor(self.ISIN, date(2026, 9, 18)), 1.0)

    def test_an_ex_date_without_a_price_cut_adds_no_factor(self):
        table, applied, unpriced = self._apply(
            {date(2026, 9, 21): _day(self.ISIN, 100.0, 101.0)}
        )

        self.assertEqual((applied, unpriced), ([], []))
        self.assertEqual(table.price_factor(self.ISIN, date(2026, 9, 18)), 1.0)

    def test_a_targeted_rebuild_picks_up_the_demerged_symbol(self):
        table, _, _ = self._apply({date(2026, 9, 21): _day(self.ISIN, 400.0, 100.0)})
        self.assertEqual(
            table.securities_with_actions_since(date(2026, 9, 1)), {self.ISIN}
        )

    def test_other_action_types_are_not_priced_this_way(self):
        actions = _actions((self.ISIN, "EXAMPLE", "2026-09-21", "rights"))
        table, applied, _ = self._apply(
            {date(2026, 9, 21): _day(self.ISIN, 400.0, 100.0)}, actions=actions
        )

        self.assertEqual(applied, [])
        self.assertEqual(table.price_factor(self.ISIN, date(2026, 9, 18)), 1.0)


if __name__ == "__main__":
    unittest.main()
