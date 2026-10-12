"""Price history across a change of basis the source did not adjust for.

Regression for October 2026. A parent going ex-demerger fell by the value of
the business carved out of it, and the site showed a 90% loss and a Stage 3
label for a company whose holders had lost nothing. The audit that followed
found the same shape from several causes, in both price sources:

* the chart's ledger carries no ratio for a demerger or a rights issue;
* it quotes ISINs the security never traded under, so a split matched no price
  row and was silently skipped;
* it dates some actions wrongly and omits fund unit splits altogether;
* the screener's vendor adjusts for neither demergers nor rights issues,
  back-adjusts some splits only part of the way, and serves the odd bad print.
"""

import re
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.corporate_actions import (
    ACTION_DEMERGER,
    ACTION_RIGHTS,
    ACTION_SPLIT,
    ACTION_UNKNOWN,
    AdjustmentTable,
    ex_date_price_factor,
    open_gap_factor,
    parse_action,
)
from backtest.security_master import SecurityMaster
from screener.data_collection import StockDataCollector
from screener.markets import resolve
from screener.price_basis import (
    CHANGE_ACTION,
    CHANGE_BAD_PRINT,
    CHANGE_OPEN_GAP,
    STATUS_NOT_LOADED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    ActionLedger,
    restate_price_basis,
)
from tests.test_markets import config_with_env_cleared
from workers.price_series_publisher import (
    adjust_observations,
    collect_raw_observations,
    reconcile_with_prices,
)

IST = ZoneInfo("Asia/Kolkata")
TZ = "Asia/Kolkata"
EX_DATE = date(2026, 9, 21)
HOLIDAYS = ("2026-10-02",)
CAP = 1.30


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


class ExDateFactorTests(unittest.TestCase):
    def test_the_factor_is_the_previous_close_over_the_ex_date_open(self):
        self.assertAlmostEqual(ex_date_price_factor(471.5, 289.95), 1.6261, places=4)

    def test_an_open_at_or_above_the_previous_close_is_not_a_ratio(self):
        self.assertIsNone(ex_date_price_factor(100.0, 100.0))
        self.assertIsNone(ex_date_price_factor(100.0, 104.0))

    def test_missing_or_zero_prices_give_no_factor(self):
        for prev_close, ex_open in ((None, 50.0), (100.0, None), (0, 50.0), (100.0, 0), ("x", 50.0)):
            self.assertIsNone(ex_date_price_factor(prev_close, ex_open))


class OpenGapFactorTests(unittest.TestCase):
    def test_an_open_inside_the_cap_is_trading(self):
        self.assertIsNone(open_gap_factor(100.0, 80.0, 78.0, CAP))
        self.assertIsNone(open_gap_factor(100.0, 120.0, 125.0, CAP))

    def test_an_open_beyond_the_cap_is_a_change_of_basis_either_way(self):
        self.assertEqual(open_gap_factor(1000.0, 100.0, 101.0, CAP), 10.0)
        self.assertEqual(open_gap_factor(10.0, 100.0, 99.0, CAP), 0.1)

    def test_a_bad_opening_print_is_not_a_change_of_basis(self):
        # The open is wild but the session closed where it had been trading.
        self.assertIsNone(open_gap_factor(100.0, 10.0, 99.0, CAP))

    def test_tick_sized_prices_are_not_read(self):
        # One tick on a 10-paise share is a 50% move.
        self.assertIsNone(open_gap_factor(0.10, 0.15, 0.15, CAP))

    def test_missing_prices_give_no_factor(self):
        self.assertIsNone(open_gap_factor(None, 100.0, 100.0, CAP))
        self.assertIsNone(open_gap_factor(1000.0, float("nan"), 100.0, CAP))


class RestateActionTests(unittest.TestCase):
    """Changes the ledger names, on a market with no opening cap."""

    def test_history_before_the_ex_date_is_restated_onto_the_new_basis(self):
        restated, changes = restate_price_basis(_history(), (EX_DATE,), TZ)

        self.assertEqual(changes, [(EX_DATE, CHANGE_ACTION, 4.0)])
        self.assertTrue((restated["Adj Close"].round(6) == 98.0).all())

    def test_raw_prices_are_left_alone(self):
        # Turnover is priced on the raw close; restating it would cut it fourfold.
        frame = _history()
        restated, _ = restate_price_basis(frame, (EX_DATE,), TZ)
        for column in ("Open", "High", "Low", "Close", "Volume"):
            pd.testing.assert_series_equal(restated[column], frame[column])

    def test_the_input_frame_is_not_modified(self):
        frame = _history()
        snapshot = frame.copy()
        restate_price_basis(frame, (EX_DATE,), TZ, max_open_gap=CAP)
        pd.testing.assert_frame_equal(frame, snapshot)

    def test_nothing_to_look_for_returns_the_frame_untouched(self):
        frame = _history()
        restated, changes = restate_price_basis(frame, (), TZ)
        self.assertIs(restated, frame)
        self.assertEqual(changes, [])

    def test_the_open_sizes_the_change_not_the_close(self):
        # The stock opened at 200 and then sold off to 100: half the fall was
        # the action and half was the market, and only the first is restated.
        restated, changes = restate_price_basis(
            _history(ex_open=200.0), (EX_DATE,), TZ
        )
        self.assertEqual(changes, [(EX_DATE, CHANGE_ACTION, 2.0)])
        self.assertAlmostEqual(restated["Adj Close"].iloc[0], 400.0 * 0.98 / 2.0)

    def test_a_small_cut_is_restated_when_the_ledger_names_it(self):
        _, changes = restate_price_basis(
            _history(pre=105.0, post=100.0), (EX_DATE,), TZ, max_open_gap=CAP
        )
        self.assertEqual([change[:2] for change in changes], [(EX_DATE, CHANGE_ACTION)])
        self.assertAlmostEqual(changes[0][2], 1.05)

    def test_an_ex_date_with_no_price_cut_restates_nothing(self):
        frame = _history(pre=100.0, post=100.0)
        restated, changes = restate_price_basis(frame, (EX_DATE,), TZ)
        self.assertIs(restated, frame)
        self.assertEqual(changes, [])

    def test_an_ex_date_outside_the_history_restates_nothing(self):
        frame = _history()
        for ex_date in (date(2020, 1, 6), date(2026, 12, 1)):
            restated, changes = restate_price_basis(frame, (ex_date,), TZ)
            self.assertIs(restated, frame)
            self.assertEqual(changes, [])

    def test_a_security_suspended_past_its_ex_date_is_priced_from_its_first_bar(self):
        frame = _history().drop(
            index=[pd.Timestamp("2026-09-21"), pd.Timestamp("2026-09-22")]
        )
        _, changes = restate_price_basis(frame, (EX_DATE,), TZ)
        self.assertEqual(changes, [(date(2026, 9, 23), CHANGE_ACTION, 4.0)])

    def test_a_first_bar_weeks_after_the_ex_date_is_not_the_action(self):
        frame = _history(periods=120)
        frame = frame[(frame.index < "2026-08-22") | (frame.index >= "2026-09-21")]
        _, changes = restate_price_basis(frame, (date(2026, 8, 22),), TZ)
        self.assertEqual(changes, [])

    def test_two_changes_compound(self):
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
        restated, changes = restate_price_basis(frame, (second, first), TZ)
        self.assertEqual(
            changes, [(first, CHANGE_ACTION, 4.0), (second, CHANGE_ACTION, 2.0)]
        )
        self.assertTrue((restated["Adj Close"].round(6) == 50.0).all())

    def test_a_timezone_aware_index_is_read_in_market_time(self):
        frame = _history()
        frame.index = frame.index.tz_localize(TZ).tz_convert("UTC")
        _, changes = restate_price_basis(frame, (EX_DATE,), TZ)
        self.assertEqual(changes, [(EX_DATE, CHANGE_ACTION, 4.0)])


class RestateOpenGapTests(unittest.TestCase):
    """Changes nothing names, on a market that caps its opening auction."""

    def test_an_open_beyond_the_cap_is_restated_without_a_ledger(self):
        # A split the vendor back-adjusted only part of the way looks like this.
        restated, changes = restate_price_basis(_history(), (), TZ, max_open_gap=CAP)

        self.assertEqual(changes, [(EX_DATE, CHANGE_OPEN_GAP, 4.0)])
        self.assertTrue((restated["Adj Close"].round(6) == 98.0).all())

    def test_a_change_the_vendor_already_bridged_is_not_restated_twice(self):
        # The raw close falls fourfold but the adjusted close runs straight on.
        frame = _history()
        frame["Adj Close"] = 98.0
        for ex_dates in ((), (EX_DATE,)):
            restated, changes = restate_price_basis(
                frame, ex_dates, TZ, max_open_gap=CAP
            )
            self.assertIs(restated, frame)
            self.assertEqual(changes, [])

    def test_a_gap_upwards_is_restated_too(self):
        restated, changes = restate_price_basis(
            _history(pre=10.0, post=100.0), (), TZ, max_open_gap=CAP
        )
        self.assertEqual(changes, [(EX_DATE, CHANGE_OPEN_GAP, 0.1)])
        self.assertTrue((restated["Adj Close"].round(6) == 98.0).all())

    def test_a_fall_traded_through_the_session_stays_a_fall(self):
        frame = _history(ex_open=400.0)
        restated, changes = restate_price_basis(frame, (), TZ, max_open_gap=CAP)
        self.assertIs(restated, frame)
        self.assertEqual(changes, [])

    def test_a_gap_inside_the_cap_stays_a_gap(self):
        frame = _history(pre=120.0, post=100.0)
        restated, changes = restate_price_basis(frame, (), TZ, max_open_gap=CAP)
        self.assertIs(restated, frame)
        self.assertEqual(changes, [])

    def test_an_uncapped_market_restates_no_gap(self):
        frame = _history()
        restated, changes = restate_price_basis(frame, (), TZ, max_open_gap=None)
        self.assertIs(restated, frame)
        self.assertEqual(changes, [])

    def test_a_gap_after_a_long_absence_is_not_one_overnight(self):
        frame = _history(periods=120)
        frame = frame[(frame.index < "2026-07-01") | (frame.index >= "2026-09-21")]
        restated, changes = restate_price_basis(frame, (), TZ, max_open_gap=CAP)
        self.assertEqual(changes, [])

    def test_a_bad_print_is_dropped_and_restates_nothing(self):
        frame = _history(pre=100.0, post=100.0)
        bad = pd.Timestamp("2026-09-10")
        frame.loc[bad, ["Open", "High", "Low", "Close", "Adj Close"]] = [
            10_000.0, 10_100.0, 9_900.0, 10_000.0, 9_800.0,
        ]
        restated, changes = restate_price_basis(frame, (), TZ, max_open_gap=CAP)

        self.assertEqual(changes, [(bad.date(), CHANGE_BAD_PRINT, None)])
        self.assertNotIn(bad, restated.index)
        self.assertEqual(len(restated), len(frame) - 1)
        self.assertTrue((restated["Adj Close"].round(6) == 98.0).all())

    def test_a_change_of_basis_is_not_mistaken_for_a_bad_print(self):
        # Two bars after a split the price is still on the new basis.
        _, changes = restate_price_basis(_history(), (), TZ, max_open_gap=CAP)
        self.assertNotIn(CHANGE_BAD_PRINT, {kind for _, kind, _ in changes})


class LedgerTests(unittest.TestCase):
    START, END = date(2024, 8, 1), date(2026, 10, 6)

    def test_ex_dates_are_served_per_symbol_from_one_fetch(self):
        calls = []

        def loader(start, end):
            calls.append((start, end))
            return [("example", EX_DATE), ("EXAMPLE", date(2025, 3, 3)), ("OTHER", EX_DATE)]

        ledger = ActionLedger("nse_actions", self.START, self.END, loader=loader)
        self.assertEqual(ledger.status, STATUS_NOT_LOADED)
        self.assertEqual(ledger.ex_dates("Example"), (date(2025, 3, 3), EX_DATE))
        self.assertEqual(ledger.ex_dates("NOBODY"), ())
        self.assertEqual(calls, [(self.START, self.END)])
        self.assertEqual(ledger.status, STATUS_OK)

    def test_a_failed_fetch_is_reported_once_and_names_nothing(self):
        calls = []

        def loader(start, end):
            calls.append(start)
            raise ConnectionError("exchange unreachable")

        ledger = ActionLedger("nse_actions", self.START, self.END, loader=loader)
        with self.assertLogs("screener.price_basis", level="WARNING"):
            self.assertEqual(ledger.ex_dates("EXAMPLE"), ())
        self.assertEqual(ledger.ex_dates("EXAMPLE"), ())
        self.assertEqual(len(calls), 1)
        self.assertEqual(ledger.status, STATUS_UNAVAILABLE)


class CollectorTests(unittest.TestCase):
    NOW = datetime(2026, 10, 6, 11, 33, tzinfo=IST)

    def _collect(self, *, enabled, history=None, pairs=(("EXAMPLE", EX_DATE),), fail=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.loader_calls = []

        def loader(start, end):
            self.loader_calls.append((start, end))
            if fail:
                raise ConnectionError("exchange unreachable")
            return list(pairs)

        config = SimpleNamespace(
            OUTPUT_DIR=Path(directory.name),
            PRICE_CACHE_MAX_AGE_HOURS=18,
            FUND_CACHE_MAX_AGE_DAYS=7,
            FACTOR_MODEL_ENABLED=False,
            NSE_MARKET_HOLIDAYS=HOLIDAYS,
            PRICE_BASIS_RESTATEMENT_ENABLED=enabled,
        )
        self.collector = StockDataCollector(
            config, clock=lambda: self.NOW, action_loader=loader
        )
        frame = history if history is not None else _history()
        with patch("screener.data_collection.yf.download", return_value=frame):
            return self.collector.download_stock_data(["EXAMPLE"]).iloc[0]

    def _diagnostic(self, name):
        return self.collector.collection_diagnostics[name]

    def test_a_change_of_basis_is_not_scored_as_a_crash(self):
        row = self._collect(enabled=True)

        self.assertEqual(row["Pct_Change_1M"], 0.0)
        self.assertEqual(row["Pct_Change_3M"], 0.0)
        # The traded price is still the price.
        self.assertEqual(row["Current_Price"], 100.0)
        self.assertEqual(
            self._diagnostic("technical_price_basis_restated_symbols"), ["EXAMPLE"]
        )
        self.assertEqual(self._diagnostic("technical_action_ledger_status"), STATUS_OK)

    def test_disabled_leaves_the_vendor_history_and_never_asks_the_exchange(self):
        row = self._collect(enabled=False)

        self.assertEqual(row["Pct_Change_1M"], -75.0)
        self.assertEqual(self.loader_calls, [])
        self.assertEqual(self._diagnostic("technical_price_basis_restated_symbols"), [])
        self.assertEqual(self._diagnostic("technical_bad_print_symbols"), [])
        self.assertEqual(self._diagnostic("technical_action_ledger_status"), "disabled")

    def test_a_fall_traded_through_the_session_stays_a_fall(self):
        row = self._collect(enabled=True, history=_history(ex_open=400.0), pairs=())

        self.assertEqual(row["Pct_Change_1M"], -75.0)
        self.assertEqual(self._diagnostic("technical_price_basis_restated_symbols"), [])

    def test_an_unreadable_ledger_still_leaves_the_opening_cap(self):
        with self.assertLogs("screener.price_basis", level="WARNING"):
            row = self._collect(enabled=True, fail=True)

        self.assertEqual(row["Pct_Change_1M"], 0.0)
        self.assertEqual(
            self._diagnostic("technical_action_ledger_status"), STATUS_UNAVAILABLE
        )

    def test_a_bad_print_is_dropped_and_reported(self):
        history = _history(pre=100.0, post=100.0)
        history.loc[pd.Timestamp("2026-09-10"), ["Open", "High", "Low", "Close", "Adj Close"]] = [
            10_000.0, 10_100.0, 9_900.0, 10_000.0, 9_800.0,
        ]
        row = self._collect(enabled=True, history=history, pairs=())

        self.assertEqual(row["Pct_Change_1M"], 0.0)
        self.assertEqual(self._diagnostic("technical_bad_print_symbols"), ["EXAMPLE"])
        self.assertEqual(self._diagnostic("technical_price_basis_restated_symbols"), [])


class WiringTests(unittest.TestCase):
    def test_off_unless_a_workflow_opts_in(self):
        # The NSE workflow sets the flag at job level and it leaks into its
        # regression-test step, so the default is read with the variable cleared.
        Config = config_with_env_cleared("PRICE_BASIS_RESTATEMENT_ENABLED")
        self.assertIs(Config.PRICE_BASIS_RESTATEMENT_ENABLED, False)

    def test_only_a_market_with_a_capped_open_reads_gaps(self):
        self.assertEqual(resolve("NSE").action_ledger, "nse_actions")
        self.assertEqual(resolve("NSE").max_open_gap, 1.30)
        # A US open is uncapped, so there a gap of any size can be real.
        self.assertIsNone(resolve("US").action_ledger)
        self.assertIsNone(resolve("US").max_open_gap)

    def test_the_nse_workflow_opts_in(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        pattern = re.compile(r'PRICE_BASIS_RESTATEMENT_ENABLED:\s*"True"')
        self.assertRegex((workflows / "daily-stock-screener.yml").read_text(), pattern)
        self.assertNotRegex(
            (workflows / "daily-us-screener.yml").read_text(), pattern
        )


# --- the chart's side: the archive, the ledger and the security master -------

ISIN = "INE000A01010"
SECURITY = "INE000A01"
SESSIONS = [date(2026, 9, 14) + timedelta(days=offset) for offset in range(12) if (date(2026, 9, 14) + timedelta(days=offset)).weekday() < 5]


def _master(*rows):
    rows = rows or ((SECURITY, ISIN, ISIN, "EXAMPLE"),)
    return SecurityMaster(
        pd.DataFrame(
            [
                {
                    "Security_ID": security_id,
                    "ISIN": isin,
                    "ISIN_History": history,
                    "Symbols": f"{symbol}|2018-01-01|2026-12-31",
                }
                for security_id, isin, history, symbol in rows
            ]
        )
    )


def _actions(*rows):
    return pd.DataFrame(
        [
            {
                "ISIN": isin,
                "Symbol": symbol,
                "Ex_Date": ex_date,
                "Action_Type": action,
                "Price_Factor": factor,
                "Dividend_Per_Share": None,
                "Subject": action,
                "Parse_Status": "ok" if factor else "unadjustable",
            }
            for isin, symbol, ex_date, action, factor in rows
        ]
    )


def _bars(pre, post, *, change=EX_DATE, ex_open=None, quoted=None, skip=()):
    """One security's raw bars: flat at ``pre``, then at ``post`` from ``change``."""
    by_day, last = {}, None
    for day in SESSIONS:
        if day in skip:
            continue
        close = post if day >= change else pre
        opened = ex_open if (ex_open is not None and day == change) else close
        prev_close = quoted if (quoted is not None and day == change) else last
        by_day[day] = (close, 1_000, opened, prev_close)
        last = close
    return {SECURITY: by_day}


def _adjusted(bars, actions, master=None):
    master = master or _master()
    table = AdjustmentTable(actions, master=master)
    report = reconcile_with_prices(bars, SESSIONS, actions, table, CAP)
    closes = [close for close, _ in adjust_observations(bars, table)[SECURITY].values()]
    return closes, report, table


def _outcomes(report):
    return [(day, outcome) for _, day, outcome, _ in report]


class ReconcileTests(unittest.TestCase):
    def test_a_confirmed_split_is_applied_from_the_ledger(self):
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_SPLIT, 10.0))
        closes, report, _ = _adjusted(_bars(1000.0, 100.0), actions)

        self.assertEqual(set(closes), {100.0})
        self.assertEqual(report, [])

    def test_a_demerger_is_priced_from_the_ex_date_open(self):
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_DEMERGER, None))
        closes, report, _ = _adjusted(_bars(400.0, 100.0), actions)

        self.assertEqual(set(closes), {100.0})
        self.assertEqual(_outcomes(report), [(EX_DATE, "priced")])

    def test_a_rights_issue_is_priced_the_same_way(self):
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_RIGHTS, None))
        closes, _, _ = _adjusted(_bars(110.0, 100.0), actions)
        self.assertEqual({round(close, 6) for close in closes}, {100.0})

    def test_the_backtest_still_excludes_a_position_spanning_a_demerger(self):
        # The factor is for drawing: what the holder was handed is not in the
        # series, so a holding period across the ex-date stays blocked.
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_DEMERGER, None))
        _, _, table = _adjusted(_bars(400.0, 100.0), actions)
        self.assertTrue(table.is_blocked(SECURITY, SESSIONS[0], SESSIONS[-1]))

    def test_a_security_suspended_over_its_ex_date_is_priced_when_it_trades(self):
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_DEMERGER, None))
        bars = _bars(400.0, 100.0, skip=(date(2026, 9, 21), date(2026, 9, 22)))
        closes, report, _ = _adjusted(bars, actions)

        self.assertEqual(set(closes), {100.0})
        self.assertEqual(_outcomes(report), [(date(2026, 9, 23), "priced")])

    def test_an_action_with_no_bars_is_reported_and_left_alone(self):
        actions = _actions(("INE999Z01019", "ABSENT", "2026-09-21", ACTION_DEMERGER, None))
        with self.assertLogs("workers.price_series_publisher", level="WARNING"):
            _, report, _ = _adjusted(_bars(100.0, 100.0), actions)
        self.assertEqual([entry[2] for entry in report], ["unpriced"])

    def test_a_ratio_the_price_ignored_is_not_applied(self):
        # The feed dated a bonus on a session where nothing happened. Applying
        # it would draw a jump of its own.
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", "bonus", 2.0))
        with self.assertLogs("workers.price_series_publisher", level="WARNING"):
            closes, report, _ = _adjusted(_bars(100.0, 100.0), actions)

        self.assertEqual(set(closes), {100.0})
        self.assertEqual(_outcomes(report), [(EX_DATE, "dropped")])

    def test_a_ratio_the_price_exceeded_is_replaced_by_the_gap(self):
        # A second action on the same day that the feed left out.
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_SPLIT, 2.0))
        with self.assertLogs("workers.price_series_publisher", level="WARNING"):
            closes, report, _ = _adjusted(_bars(600.0, 100.0), actions)

        self.assertEqual(set(closes), {100.0})
        self.assertEqual(_outcomes(report), [(EX_DATE, "repriced")])

    def test_a_ratio_within_a_normal_overnight_move_is_confirmed(self):
        # Split by two, and the market also opened 10% lower.
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_SPLIT, 2.0))
        closes, report, _ = _adjusted(_bars(220.0, 100.0), actions)

        self.assertEqual(report, [])
        self.assertEqual(closes[0], 110.0)

    def test_two_actions_on_one_day_are_confirmed_as_their_product(self):
        actions = _actions(
            (ISIN, "EXAMPLE", "2026-09-21", ACTION_SPLIT, 2.0),
            (ISIN, "EXAMPLE", "2026-09-21", "bonus", 5.0),
        )
        closes, report, _ = _adjusted(_bars(1000.0, 100.0), actions)

        self.assertEqual(set(closes), {100.0})
        self.assertEqual(report, [])

    def test_a_unit_change_the_ledger_never_reported_is_applied_as_found(self):
        closes, report, _ = _adjusted(_bars(1000.0, 100.0), _actions())

        self.assertEqual(set(closes), {100.0})
        self.assertEqual(_outcomes(report), [(EX_DATE, "open_gap")])

    def test_a_consolidation_is_applied_as_found(self):
        closes, _, _ = _adjusted(_bars(10.0, 100.0), _actions())
        self.assertEqual({round(close, 6) for close in closes}, {100.0})

    def test_a_fall_traded_through_the_session_is_left_alone(self):
        bars = _bars(400.0, 100.0, ex_open=400.0)
        closes, report, _ = _adjusted(bars, _actions())

        self.assertEqual(closes[0], 400.0)
        self.assertEqual(report, [])

    def test_a_session_missing_from_the_archive_is_not_a_change_of_basis(self):
        # The archive lacks a special session in which the price rose 19%; the
        # next bar opens 15% above that, 37% above the last close held. The
        # day-file's own previous close shows the open was traded to.
        bars = _bars(100.0, 137.0, ex_open=137.0, quoted=119.0)
        closes, report, _ = _adjusted(bars, _actions())

        self.assertEqual(closes[0], 100.0)
        self.assertEqual(report, [])

    def test_a_previous_close_the_exchange_restated_does_not_hide_a_split(self):
        # The day-file quotes the previous close already on the new basis.
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_SPLIT, 10.0))
        closes, report, _ = _adjusted(_bars(1000.0, 100.0, quoted=100.0), actions)

        self.assertEqual(set(closes), {100.0})
        self.assertEqual(report, [])

    def test_a_targeted_rebuild_picks_up_a_priced_action(self):
        actions = _actions((ISIN, "EXAMPLE", "2026-09-21", ACTION_DEMERGER, None))
        _, _, table = _adjusted(_bars(400.0, 100.0), actions)
        self.assertEqual(
            table.securities_with_actions_since(date(2026, 9, 1)), {SECURITY}
        )


class ActionKeyTests(unittest.TestCase):
    """An action has to reach the security whose prices it changes."""

    def _closes(self, isin, symbol, master):
        actions = _actions((isin, symbol, "2026-09-21", ACTION_SPLIT, 10.0))
        table = AdjustmentTable(actions, master=master)
        bars = _bars(1000.0, 100.0)
        return {close for close, _ in adjust_observations(bars, table)[SECURITY].values()}

    def test_an_isin_the_security_traded_under(self):
        self.assertEqual(self._closes(ISIN, "EXAMPLE", _master()), {100.0})

    def test_an_isin_superseded_before_the_archive_began(self):
        # Same core, a face value the archive never saw trade. Keyed on the
        # raw ISIN the split matched no price row and the chart drew a 90% fall.
        self.assertEqual(self._closes("INE000A01036", "EXAMPLE", _master()), {100.0})

    def test_an_isin_that_is_not_the_companys_falls_back_to_the_ticker(self):
        for wrong in ("IN0000000000", "INE777Z01011"):
            self.assertEqual(self._closes(wrong, "EXAMPLE", _master()), {100.0})

    def test_a_core_shared_by_two_securities_names_neither(self):
        master = _master(
            ("INE000A01:ONE", ISIN, ISIN, "ONE"),
            ("INE000A01:TWO", "INE000A01028", "INE000A01028", "TWO"),
        )
        self.assertIsNone(master.security_id_for_isin_core("INE000A01036"))
        self.assertEqual(master.security_id_for_isin(ISIN), "INE000A01:ONE")

    def test_a_ticker_is_resolved_as_of_the_ex_date(self):
        master = _master()
        table = AdjustmentTable(_actions(), master=master)
        self.assertEqual(
            table.key_for("IN0000000000", "EXAMPLE", date(2026, 9, 21)), SECURITY
        )
        self.assertEqual(
            table.key_for("IN0000000000", "EXAMPLE", date(2010, 1, 1)), "IN0000000000"
        )


class ConsolidationParseTests(unittest.TestCase):
    def test_a_consolidation_is_a_split_with_a_ratio_below_one(self):
        action, factor, _, status = parse_action(
            "Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share"
        )
        self.assertEqual((action, status), (ACTION_SPLIT, "ok"))
        self.assertAlmostEqual(factor, 0.1)

    def test_a_capital_reduction_is_not_a_ratio(self):
        action, factor, _, _ = parse_action(
            "Capital Reduction Rs 10 To Rs 3.30 / Consolidation Rs 3.30 To Rs.10"
        )
        self.assertEqual(action, ACTION_UNKNOWN)
        self.assertIsNone(factor)


class RawObservationTests(unittest.TestCase):
    def test_bars_keep_the_open_and_the_quoted_previous_close(self):
        class Store:
            def load_day(self, day):
                return pd.DataFrame(
                    [
                        {"ISIN": ISIN, "Symbol": "EXAMPLE", "Open": 99.0, "Close": 100.0, "Prev_Close": 98.0, "Volume": 500},
                        {"ISIN": "INE111B01017", "Symbol": "UNTRADED", "Open": None, "Close": None, "Prev_Close": 5.0, "Volume": 0},
                    ]
                )

        bars, symbols = collect_raw_observations(Store(), SESSIONS[:2], _master())

        self.assertEqual(set(bars), {SECURITY})
        self.assertEqual(bars[SECURITY][SESSIONS[0]], (100.0, 500, 99.0, 98.0))
        self.assertEqual(symbols, {SECURITY: "EXAMPLE"})


if __name__ == "__main__":
    unittest.main()
