"""Behavioural spec for next-session execution and forward returns.

The property this file exists to lock down: a signal from the close of session *t*
is never filled at that close. Everything else here is about making an unpriceable
position visible instead of approximated.
"""

import unittest
from datetime import date

import pandas as pd

from backtest.calendar import TradingCalendar
from backtest.corporate_actions import ACTION_DEMERGER, ACTION_SPLIT, AdjustmentTable
from backtest.execution import (
    EXIT_DELISTED,
    EXIT_NORMAL,
    SKIP_HORIZON_BEYOND_DATA,
    SKIP_NO_ENTRY_PRICE,
    SKIP_NO_EXIT_PRICE,
    SKIP_UNADJUSTABLE_ACTION,
    ExecutionModel,
    PricePanel,
    attach_forward_returns,
    coverage_report,
)
from backtest.security_master import DelistingPolicy

# Six months of month-start sessions, enough for 1M and 3M horizons.
SESSIONS = [
    date(2026, 1, 5),
    date(2026, 2, 2),
    date(2026, 3, 2),
    date(2026, 4, 1),
    date(2026, 5, 4),
    date(2026, 6, 1),
    date(2026, 7, 1),
]


def panel_for(rows, key_column="Security_ID"):
    return PricePanel(pd.DataFrame(rows), key_column=key_column)


def steady_panel(keys=("SEC1",), prices=None):
    rows = []
    for key in keys:
        for index, day in enumerate(SESSIONS):
            base = 100.0 + index * 10 if prices is None else prices[index]
            rows.append(
                {
                    "Security_ID": key,
                    "Trade_Date": day.isoformat(),
                    "Open": base,
                    "Close": base + 1.0,
                }
            )
    return panel_for(rows)


def model(panel=None, **kwargs):
    return ExecutionModel(
        TradingCalendar(SESSIONS), panel if panel is not None else steady_panel(), **kwargs
    )


class NoSameCloseFillTests(unittest.TestCase):
    def test_entry_session_is_strictly_after_the_signal(self):
        execution = model()
        self.assertEqual(
            execution.entry_session(date(2026, 1, 5)), date(2026, 2, 2)
        )

    def test_entry_price_is_the_next_session_open_not_the_signal_close(self):
        execution = model()
        record = execution.resolve("SEC1", date(2026, 1, 5), 1)
        # Signal close on 2026-01-05 is 101.0; the fill must be February's open.
        self.assertAlmostEqual(record["Entry_Price"], 110.0)
        self.assertNotAlmostEqual(record["Entry_Price"], 101.0)

    def test_signal_on_a_non_session_still_fills_on_the_next_session(self):
        execution = model()
        record = execution.resolve("SEC1", date(2026, 1, 15), 1)
        self.assertEqual(record["Entry_Session"], "2026-02-02")


class ReturnTests(unittest.TestCase):
    def test_return_is_open_to_open(self):
        execution = model()
        record = execution.resolve("SEC1", date(2026, 1, 5), 1)
        # Enter at Feb open 110, exit at Mar open 120.
        self.assertEqual(record["Exit_Session"], "2026-03-02")
        self.assertAlmostEqual(record["Return_Pct"], (120.0 / 110.0 - 1) * 100)

    def test_three_month_horizon_spans_three_calendar_months(self):
        execution = model()
        record = execution.resolve("SEC1", date(2026, 1, 5), 3)
        self.assertEqual(record["Entry_Session"], "2026-02-02")
        self.assertEqual(record["Exit_Session"], "2026-05-04")

    def test_holding_sessions_are_recorded(self):
        execution = model()
        record = execution.resolve("SEC1", date(2026, 1, 5), 1)
        self.assertEqual(record["Holding_Sessions"], 2)

    def test_status_is_ok_on_a_clean_fill(self):
        self.assertEqual(
            model().resolve("SEC1", date(2026, 1, 5), 1)["Status"], "ok"
        )

    def test_horizon_past_the_archive_is_flagged_not_clamped(self):
        record = model().resolve("SEC1", date(2026, 6, 1), 3)
        self.assertEqual(record["Status"], SKIP_HORIZON_BEYOND_DATA)
        self.assertIsNone(record["Return_Pct"])

    def test_signal_after_the_last_session_has_no_entry(self):
        record = model().resolve("SEC1", date(2026, 7, 1), 1)
        self.assertEqual(record["Status"], SKIP_HORIZON_BEYOND_DATA)


class AdjustedPriceTests(unittest.TestCase):
    def test_returns_use_adjusted_prices_when_present(self):
        rows = []
        for index, day in enumerate(SESSIONS):
            raw = 100.0 if index < 2 else 50.0
            rows.append(
                {
                    "Security_ID": "SEC1",
                    "Trade_Date": day.isoformat(),
                    "Open": raw,
                    "Close": raw,
                    "Adj_Open": 50.0,
                    "Adj_Close": 50.0,
                }
            )
        execution = model(panel_for(rows))
        record = execution.resolve("SEC1", date(2026, 1, 5), 1)
        self.assertAlmostEqual(record["Return_Pct"], 0.0)

    def test_dividends_are_added_to_the_return(self):
        table = AdjustmentTable(
            pd.DataFrame(
                [
                    {
                        "ISIN": "SEC1",
                        "Ex_Date": "2026-02-15",
                        "Action_Type": "dividend",
                        "Price_Factor": None,
                        "Dividend_Per_Share": 11.0,
                    }
                ]
            )
        )
        execution = model(adjustment_table=table)
        record = execution.resolve("SEC1", date(2026, 1, 5), 1)
        self.assertAlmostEqual(record["Dividends"], 11.0)
        self.assertAlmostEqual(record["Return_Pct"], (131.0 / 110.0 - 1) * 100)


class BlockedActionTests(unittest.TestCase):
    def test_demerger_inside_the_holding_period_drops_the_position(self):
        table = AdjustmentTable(
            pd.DataFrame(
                [
                    {
                        "ISIN": "SEC1",
                        "Ex_Date": "2026-02-15",
                        "Action_Type": ACTION_DEMERGER,
                        "Price_Factor": None,
                        "Dividend_Per_Share": None,
                    }
                ]
            )
        )
        record = model(adjustment_table=table).resolve("SEC1", date(2026, 1, 5), 1)
        self.assertEqual(record["Status"], SKIP_UNADJUSTABLE_ACTION)
        self.assertIsNone(record["Return_Pct"])

    def test_unquantifiable_split_also_drops_the_position(self):
        table = AdjustmentTable(
            pd.DataFrame(
                [
                    {
                        "ISIN": "SEC1",
                        "Ex_Date": "2026-02-15",
                        "Action_Type": ACTION_SPLIT,
                        "Price_Factor": None,
                        "Dividend_Per_Share": None,
                    }
                ]
            )
        )
        record = model(adjustment_table=table).resolve("SEC1", date(2026, 1, 5), 1)
        self.assertEqual(record["Status"], SKIP_UNADJUSTABLE_ACTION)


class MissingPriceTests(unittest.TestCase):
    def test_no_trade_on_the_fill_session_drops_the_position(self):
        rows = [
            {
                "Security_ID": "SEC1",
                "Trade_Date": day.isoformat(),
                "Open": 100.0,
                "Close": 100.0,
            }
            for day in SESSIONS
            if day != date(2026, 2, 2)
        ]
        record = model(panel_for(rows)).resolve("SEC1", date(2026, 1, 5), 1)
        self.assertEqual(record["Status"], SKIP_NO_ENTRY_PRICE)

    def test_gap_on_the_exit_session_falls_back_to_the_last_close(self):
        """A liquidity gap is not a delisting and needs no assumption."""
        rows = []
        for day in SESSIONS:
            if day == date(2026, 3, 2):
                continue
            rows.append(
                {
                    "Security_ID": "SEC1",
                    "Trade_Date": day.isoformat(),
                    "Open": 100.0,
                    "Close": 105.0,
                }
            )
        record = model(panel_for(rows)).resolve("SEC1", date(2026, 1, 5), 1)
        self.assertEqual(record["Exit_Type"], EXIT_NORMAL)
        self.assertAlmostEqual(record["Exit_Price"], 105.0)

    def test_unknown_security_is_dropped(self):
        record = model().resolve("NOPE", date(2026, 1, 5), 1)
        self.assertEqual(record["Status"], SKIP_NO_ENTRY_PRICE)


class DelistingExitTests(unittest.TestCase):
    def truncated_panel(self):
        """SEC1 stops trading after 2026-03-02."""
        rows = [
            {
                "Security_ID": "SEC1",
                "Trade_Date": day.isoformat(),
                "Open": 100.0,
                "Close": 80.0,
            }
            for day in SESSIONS[:3]
        ]
        rows += [
            {
                "Security_ID": "SEC2",
                "Trade_Date": day.isoformat(),
                "Open": 50.0,
                "Close": 50.0,
            }
            for day in SESSIONS
        ]
        return panel_for(rows)

    def test_mid_period_delisting_uses_the_policy_terminal_value(self):
        execution = model(
            self.truncated_panel(),
            delisting_policy=DelistingPolicy("haircut", recovery_rate=0.5),
        )
        record = execution.resolve("SEC1", date(2026, 1, 5), 3)
        self.assertEqual(record["Exit_Type"], EXIT_DELISTED)
        self.assertAlmostEqual(record["Exit_Price"], 40.0)

    def test_delisting_loss_reaches_the_return(self):
        """The whole point: a failure must not vanish from the result."""
        execution = model(
            self.truncated_panel(),
            delisting_policy=DelistingPolicy("zero"),
        )
        record = execution.resolve("SEC1", date(2026, 1, 5), 3)
        self.assertAlmostEqual(record["Return_Pct"], -100.0)

    def test_without_a_policy_the_position_is_dropped_not_carried(self):
        execution = model(self.truncated_panel(), delisting_policy=None)
        record = execution.resolve("SEC1", date(2026, 1, 5), 3)
        self.assertEqual(record["Status"], SKIP_NO_EXIT_PRICE)

    def test_delisting_after_the_horizon_is_irrelevant(self):
        execution = model(
            self.truncated_panel(),
            delisting_policy=DelistingPolicy("zero"),
        )
        record = execution.resolve("SEC1", date(2026, 1, 5), 1)
        self.assertEqual(record["Exit_Type"], EXIT_NORMAL)


class PanelTests(unittest.TestCase):
    def test_universe_on_a_session_is_what_traded_that_session(self):
        panel = steady_panel(keys=("SEC1", "SEC2"))
        self.assertEqual(panel.keys_on(date(2026, 1, 5)), {"SEC1", "SEC2"})

    def test_zero_and_negative_prices_are_not_stored(self):
        panel = panel_for(
            [
                {
                    "Security_ID": "SEC1",
                    "Trade_Date": "2026-01-05",
                    "Open": 0.0,
                    "Close": -5.0,
                }
            ]
        )
        self.assertIsNone(panel.open_price("SEC1", date(2026, 1, 5)))
        self.assertFalse(panel.traded_on("SEC1", date(2026, 1, 5)))

    def test_empty_panel_is_safe(self):
        panel = PricePanel(pd.DataFrame())
        self.assertEqual(len(panel), 0)
        self.assertIsNone(panel.open_price("SEC1", date(2026, 1, 5)))


class AttachTests(unittest.TestCase):
    def test_one_column_per_horizon_is_attached(self):
        scores = pd.DataFrame({"Security_ID": ["SEC1"], "Score": [70.0]})
        out = attach_forward_returns(
            scores, model(), date(2026, 1, 5), horizons=(1, 3)
        )
        for horizon in (1, 3):
            self.assertIn(f"Forward_Return_{horizon}M_Pct", out.columns)
            self.assertIn(f"Forward_Status_{horizon}M", out.columns)

    def test_skip_reason_is_visible_rather_than_a_bare_nan(self):
        scores = pd.DataFrame({"Security_ID": ["SEC1"], "Score": [70.0]})
        out = attach_forward_returns(
            scores, model(), date(2026, 6, 1), horizons=(3,)
        )
        self.assertEqual(
            out["Forward_Status_3M"].iloc[0], SKIP_HORIZON_BEYOND_DATA
        )

    def test_coverage_report_counts_fills_per_horizon(self):
        scores = pd.DataFrame({"Security_ID": ["SEC1", "NOPE"], "Score": [70.0, 1.0]})
        out = attach_forward_returns(
            scores, model(), date(2026, 1, 5), horizons=(1,)
        )
        report = coverage_report(out, horizons=(1,))
        self.assertEqual(report["1M"]["total"], 2)
        self.assertEqual(report["1M"]["ok"], 1)
        self.assertAlmostEqual(report["1M"]["coverage"], 0.5)


if __name__ == "__main__":
    unittest.main()
