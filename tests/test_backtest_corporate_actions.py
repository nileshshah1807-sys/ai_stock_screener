"""Behavioural spec for corporate-action parsing and price adjustment.

Every subject string used here is a real NSE ``subject`` value taken from the
2025-01 to 2026-08 equities feed.
"""

import unittest
from datetime import date

import pandas as pd

from backtest.corporate_actions import (
    ACTION_BONUS,
    ACTION_BUYBACK,
    ACTION_DEMERGER,
    ACTION_DIVIDEND,
    ACTION_INTEREST,
    ACTION_RIGHTS,
    ACTION_SPLIT,
    AdjustmentTable,
    adjust_panel,
    normalise_actions,
    parse_action,
)


class ClassifyTests(unittest.TestCase):
    def test_face_value_split(self):
        action, factor, _, status = parse_action(
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
        )
        self.assertEqual(action, ACTION_SPLIT)
        self.assertAlmostEqual(factor, 5.0)
        self.assertEqual(status, "ok")

    def test_split_to_one_rupee_uses_the_re_spelling(self):
        _, factor, _, _ = parse_action(
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share"
        )
        self.assertAlmostEqual(factor, 10.0)

    def test_split_from_two_to_one(self):
        _, factor, _, _ = parse_action(
            "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share"
        )
        self.assertAlmostEqual(factor, 2.0)

    def test_bonus_one_for_one_doubles_the_share_count(self):
        action, factor, _, status = parse_action("Bonus 1:1")
        self.assertEqual(action, ACTION_BONUS)
        self.assertAlmostEqual(factor, 2.0)
        self.assertEqual(status, "ok")

    def test_bonus_four_for_one_gives_five(self):
        _, factor, _, _ = parse_action("Bonus 4:1")
        self.assertAlmostEqual(factor, 5.0)

    def test_bonus_one_for_two_gives_one_and_a_half(self):
        """A:B awards A new per B held, so the factor is (A+B)/B, not A/B."""
        _, factor, _, _ = parse_action("Bonus 1:2")
        self.assertAlmostEqual(factor, 1.5)

    def test_bonus_two_for_five(self):
        _, factor, _, _ = parse_action("Bonus 2:5")
        self.assertAlmostEqual(factor, 1.4)

    def test_dividend_amount_is_extracted(self):
        action, factor, dividend, status = parse_action("Dividend - Re 0.40 Per Sh")
        self.assertEqual(action, ACTION_DIVIDEND)
        self.assertIsNone(factor)
        self.assertAlmostEqual(dividend, 0.40)
        self.assertEqual(status, "ok")

    def test_rupee_dividend(self):
        _, _, dividend, _ = parse_action("Dividend - Rs 2.75 Per Share")
        self.assertAlmostEqual(dividend, 2.75)

    def test_rights_is_flagged_unadjustable_not_guessed(self):
        action, factor, _, status = parse_action("Rights 1:4 @ Premium Rs 90/-")
        self.assertEqual(action, ACTION_RIGHTS)
        self.assertIsNone(factor)
        self.assertEqual(status, "unadjustable")

    def test_demerger_is_flagged_unadjustable(self):
        action, _, _, status = parse_action("Demerger")
        self.assertEqual(action, ACTION_DEMERGER)
        self.assertEqual(status, "unadjustable")

    def test_buyback_is_flagged_unadjustable(self):
        action, _, _, status = parse_action("Buy Back")
        self.assertEqual(action, ACTION_BUYBACK)
        self.assertEqual(status, "unadjustable")

    def test_interest_payment_is_ignored_as_debt(self):
        action, _, _, status = parse_action("Interest Payment")
        self.assertEqual(action, ACTION_INTEREST)
        self.assertEqual(status, "ignored")

    def test_unparseable_split_reports_rather_than_defaulting_to_one(self):
        action, factor, _, status = parse_action("Face Value Split - details awaited")
        self.assertEqual(action, ACTION_SPLIT)
        self.assertIsNone(factor)
        self.assertEqual(status, "unparsed_ratio")

    def test_empty_subject_is_unknown(self):
        self.assertEqual(parse_action("")[0], "unknown")


class NormaliseTests(unittest.TestCase):
    def raw(self):
        return [
            {
                "isin": "INE117Z01011",
                "symbol": "NARMADA",
                "exDate": "31-Jul-2026",
                "subject": "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Per Share",
            },
            {
                "isin": "INE0OFM01015",
                "symbol": "DSFCL",
                "exDate": "01-Jul-2026",
                "subject": "Dividend - Re 0.40 Per Sh",
            },
            {"isin": "", "symbol": "NOISIN", "exDate": "01-Jul-2026", "subject": "Bonus 1:1"},
            {"isin": "INE999Z01011", "symbol": "NODATE", "exDate": "-", "subject": "Bonus 1:1"},
        ]

    def test_rows_without_isin_or_ex_date_are_dropped(self):
        frame = normalise_actions(self.raw())
        self.assertEqual(len(frame), 2)

    def test_ex_date_is_normalised_to_iso(self):
        frame = normalise_actions(self.raw())
        self.assertIn("2026-07-31", set(frame["Ex_Date"]))

    def test_split_factor_is_computed(self):
        frame = normalise_actions(self.raw())
        row = frame[frame["Symbol"] == "NARMADA"].iloc[0]
        self.assertAlmostEqual(row["Price_Factor"], 2.0)

    def test_empty_input_returns_empty_schema(self):
        frame = normalise_actions([])
        self.assertTrue(frame.empty)
        self.assertIn("Ex_Date", frame.columns)


def actions_frame(rows):
    return pd.DataFrame(rows)


class AdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.table = AdjustmentTable(
            actions_frame(
                [
                    {
                        "ISIN": "INE117Z01011",
                        "Ex_Date": "2026-07-31",
                        "Action_Type": ACTION_SPLIT,
                        "Price_Factor": 2.0,
                        "Dividend_Per_Share": None,
                    }
                ]
            )
        )

    def test_price_before_the_ex_date_is_divided_by_the_factor(self):
        self.assertAlmostEqual(
            self.table.price_factor("INE117Z01011", date(2026, 7, 30)), 2.0
        )

    def test_price_on_the_ex_date_is_unadjusted(self):
        self.assertAlmostEqual(
            self.table.price_factor("INE117Z01011", date(2026, 7, 31)), 1.0
        )

    def test_price_after_the_ex_date_is_unadjusted(self):
        self.assertAlmostEqual(
            self.table.price_factor("INE117Z01011", date(2026, 8, 11)), 1.0
        )

    def test_unaffected_security_has_a_unit_factor(self):
        self.assertAlmostEqual(
            self.table.price_factor("INE000A01011", date(2026, 7, 30)), 1.0
        )

    def test_the_real_narmada_split_return_becomes_flat_not_minus_53_percent(self):
        """The regression this module exists to prevent."""
        before = 36.19 / self.table.price_factor("INE117Z01011", date(2026, 7, 30))
        after = 17.02 / self.table.price_factor("INE117Z01011", date(2026, 7, 31))
        naive = (17.02 / 36.19) - 1
        adjusted = (after / before) - 1
        self.assertLess(naive, -0.5)
        self.assertGreater(adjusted, -0.10)

    def test_sequential_actions_compound(self):
        table = AdjustmentTable(
            actions_frame(
                [
                    {
                        "ISIN": "INE001A01036",
                        "Ex_Date": "2026-03-01",
                        "Action_Type": ACTION_SPLIT,
                        "Price_Factor": 2.0,
                        "Dividend_Per_Share": None,
                    },
                    {
                        "ISIN": "INE001A01036",
                        "Ex_Date": "2026-06-01",
                        "Action_Type": ACTION_BONUS,
                        "Price_Factor": 3.0,
                        "Dividend_Per_Share": None,
                    },
                ]
            )
        )
        self.assertAlmostEqual(
            table.price_factor("INE001A01036", date(2026, 1, 1)), 6.0
        )
        self.assertAlmostEqual(
            table.price_factor("INE001A01036", date(2026, 4, 1)), 3.0
        )
        self.assertAlmostEqual(
            table.price_factor("INE001A01036", date(2026, 7, 1)), 1.0
        )


class BlockingTests(unittest.TestCase):
    def setUp(self):
        self.table = AdjustmentTable(
            actions_frame(
                [
                    {
                        "ISIN": "INE555A01011",
                        "Ex_Date": "2026-05-15",
                        "Action_Type": ACTION_DEMERGER,
                        "Price_Factor": None,
                        "Dividend_Per_Share": None,
                    },
                    {
                        "ISIN": "INE666A01011",
                        "Ex_Date": "2026-05-15",
                        "Action_Type": ACTION_SPLIT,
                        "Price_Factor": None,
                        "Dividend_Per_Share": None,
                    },
                ]
            )
        )

    def test_demerger_blocks_a_spanning_holding_period(self):
        self.assertTrue(
            self.table.is_blocked("INE555A01011", date(2026, 5, 1), date(2026, 6, 1))
        )

    def test_action_outside_the_period_does_not_block(self):
        self.assertFalse(
            self.table.is_blocked("INE555A01011", date(2026, 6, 1), date(2026, 7, 1))
        )

    def test_unquantifiable_split_blocks_rather_than_being_skipped(self):
        """A structural action we cannot measure must not pass through as 1.0."""
        self.assertTrue(
            self.table.is_blocked("INE666A01011", date(2026, 5, 1), date(2026, 6, 1))
        )

    def test_blocked_reasons_are_reportable(self):
        self.assertEqual(
            self.table.blocked_reasons(
                "INE555A01011", date(2026, 5, 1), date(2026, 6, 1)
            ),
            [ACTION_DEMERGER],
        )


class DividendTests(unittest.TestCase):
    def setUp(self):
        self.table = AdjustmentTable(
            actions_frame(
                [
                    {
                        "ISIN": "INE001A01036",
                        "Ex_Date": "2026-05-15",
                        "Action_Type": ACTION_DIVIDEND,
                        "Price_Factor": None,
                        "Dividend_Per_Share": 4.0,
                    },
                    {
                        "ISIN": "INE001A01036",
                        "Ex_Date": "2026-08-15",
                        "Action_Type": ACTION_DIVIDEND,
                        "Price_Factor": None,
                        "Dividend_Per_Share": 2.5,
                    },
                ]
            )
        )

    def test_dividends_inside_the_holding_period_accumulate(self):
        self.assertAlmostEqual(
            self.table.dividends_between(
                "INE001A01036", date(2026, 1, 1), date(2026, 12, 31)
            ),
            6.5,
        )

    def test_period_start_is_exclusive(self):
        self.assertAlmostEqual(
            self.table.dividends_between(
                "INE001A01036", date(2026, 5, 15), date(2026, 6, 1)
            ),
            0.0,
        )

    def test_period_end_is_inclusive(self):
        self.assertAlmostEqual(
            self.table.dividends_between(
                "INE001A01036", date(2026, 5, 1), date(2026, 5, 15)
            ),
            4.0,
        )

    def test_a_dividend_does_not_change_the_price_factor(self):
        self.assertAlmostEqual(
            self.table.price_factor("INE001A01036", date(2026, 1, 1)), 1.0
        )


class MasterBridgeTests(unittest.TestCase):
    class FakeMaster:
        def security_id_for_isin(self, isin):
            return "INE117Z01" if str(isin).startswith("INE117Z01") else None

    def test_action_on_a_pre_split_isin_applies_to_the_bridged_security(self):
        table = AdjustmentTable(
            actions_frame(
                [
                    {
                        "ISIN": "INE117Z01011",
                        "Ex_Date": "2026-07-31",
                        "Action_Type": ACTION_SPLIT,
                        "Price_Factor": 2.0,
                        "Dividend_Per_Share": None,
                    }
                ]
            ),
            master=self.FakeMaster(),
        )
        self.assertAlmostEqual(
            table.price_factor("INE117Z01", date(2026, 7, 30)), 2.0
        )


class AdjustPanelTests(unittest.TestCase):
    def test_adjusted_close_is_continuous_across_a_split(self):
        table = AdjustmentTable(
            actions_frame(
                [
                    {
                        "ISIN": "SEC1",
                        "Ex_Date": "2026-07-31",
                        "Action_Type": ACTION_SPLIT,
                        "Price_Factor": 2.0,
                        "Dividend_Per_Share": None,
                    }
                ]
            )
        )
        panel = pd.DataFrame(
            {
                "Security_ID": ["SEC1", "SEC1"],
                "Trade_Date": ["2026-07-30", "2026-07-31"],
                "Open": [36.0, 20.0],
                "High": [37.0, 20.5],
                "Low": [35.0, 16.5],
                "Close": [36.19, 17.02],
            }
        )
        out = adjust_panel(panel, table)
        self.assertAlmostEqual(out["Adj_Close"].iloc[0], 18.095)
        self.assertAlmostEqual(out["Adj_Close"].iloc[1], 17.02)
        self.assertGreater(out["Adj_Close"].iloc[1] / out["Adj_Close"].iloc[0], 0.9)

    def test_volume_is_left_raw(self):
        table = AdjustmentTable(actions_frame([]))
        panel = pd.DataFrame(
            {
                "Security_ID": ["SEC1"],
                "Trade_Date": ["2026-07-30"],
                "Open": [10.0],
                "High": [10.0],
                "Low": [10.0],
                "Close": [10.0],
                "Volume": [1000],
            }
        )
        out = adjust_panel(panel, table)
        self.assertNotIn("Adj_Volume", out.columns)
        self.assertEqual(out["Volume"].iloc[0], 1000)

    def test_empty_panel_passes_through(self):
        table = AdjustmentTable(actions_frame([]))
        self.assertTrue(adjust_panel(pd.DataFrame(), table).empty)


if __name__ == "__main__":
    unittest.main()
