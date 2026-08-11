"""A bar behind the expected session must never be labelled complete.

`_select_completed_price_bars` rejects a misaligned symbol, but the usable-rows
filter that runs afterwards can drop the expected session's row when the vendor
leaves a NaN close or volume on it. Alignment was therefore established before
the step that invalidates it. In the 2026-08-11 validation run that let 1,503 of
2,364 rows (64%) carry a three-session-old bar flagged Price_Bar_Complete=True,
with a null session lag hiding it.
"""

import unittest
from datetime import date
from types import SimpleNamespace

import pandas as pd

from screener.market_data import expected_sessions_behind
from screener.recommendation import finalize_recommendations


class ExpectedSessionsBehindTests(unittest.TestCase):
    def test_aligned_bar_is_zero_sessions_behind(self):
        self.assertEqual(
            expected_sessions_behind(date(2026, 8, 10), date(2026, 8, 10)), 0
        )

    def test_weekend_is_not_counted_as_a_missed_session(self):
        # Friday 2026-08-07 -> Monday 2026-08-10 is one session, not three days.
        self.assertEqual(
            expected_sessions_behind(date(2026, 8, 7), date(2026, 8, 10)), 1
        )

    def test_configured_holiday_is_not_counted(self):
        # With Monday declared a holiday, Friday is the expected session itself.
        self.assertEqual(
            expected_sessions_behind(
                date(2026, 8, 7), date(2026, 8, 10), ("2026-08-10",)
            ),
            0,
        )

    def test_multi_session_lag_is_a_real_count_not_null(self):
        self.assertEqual(
            expected_sessions_behind(date(2026, 8, 5), date(2026, 8, 10)), 3
        )

    def test_missing_dates_return_none(self):
        self.assertIsNone(expected_sessions_behind(None, date(2026, 8, 10)))
        self.assertIsNone(expected_sessions_behind(date(2026, 8, 10), None))


def config(**overrides):
    values = {
        "REVERSE_DCF_RANKING_WEIGHT": 0.10,
        "TRANSCRIPT_SENTIMENT_WEIGHT": 0.15,
        "REQUIRE_UPTREND_FOR_BUY": True,
        "BUY_MIN_MA50_SLOPE": 0.0,
        "BUY_MIN_3M_RETURN": 0.0,
        "STRONG_BUY_MIN_GROWTH": 0.05,
        "STRONG_BUY_MIN_TECH_SCORE": 55.0,
        "STRONG_BUY_MIN_ADX": 20.0,
        "REQUIRE_ALIGNED_PRICE_BAR_FOR_BUY": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def strong_row(**overrides):
    values = {
        "Symbol": "ALIGNED",
        "Combined_Score": 78.0,
        "Technical_Price": 120.0,
        "MA50": 100.0,
        "MA50_Slope_Pct": 5.0,
        "Pct_Change_3M": 12.0,
        "Revenue_Growth": 0.20,
        "Earnings_Growth": 0.25,
        "ADX_14": 30.0,
        "ADX_Plus_DI": 30.0,
        "ADX_Minus_DI": 10.0,
        "Technical_Score": 75.0,
        "Data_Quality": "FULL",
        "Price_Bar_Aligned": True,
        "Price_Bar_Session_Lag": 0,
    }
    values.update(overrides)
    return values


class StalePriceBarPolicyTests(unittest.TestCase):
    def test_aligned_row_keeps_strong_buy(self):
        result = finalize_recommendations(pd.DataFrame([strong_row()]), config())

        self.assertEqual(result.loc[0, "Rating"], "STRONG BUY")
        self.assertEqual(result.loc[0, "Decision_Score"], 78.0)

    def test_stale_bar_cannot_hold_buy_conviction(self):
        stale = strong_row(
            Symbol="STALE", Price_Bar_Aligned=False, Price_Bar_Session_Lag=3
        )
        result = finalize_recommendations(pd.DataFrame([stale]), config())

        self.assertEqual(result.loc[0, "Rating"], "HOLD")
        self.assertEqual(result.loc[0, "Decision_Score"], 59.99)
        self.assertIn(
            "price bar behind expected session (3 session(s) behind)",
            result.loc[0, "Buy_Gate_Reason"],
        )

    def test_stale_row_is_published_not_dropped(self):
        """Excluding lagging symbols would discard most of a gap-day universe."""

        frame = pd.DataFrame([
            strong_row(),
            strong_row(Symbol="STALE", Price_Bar_Aligned=False, Price_Bar_Session_Lag=1),
        ])
        result = finalize_recommendations(frame, config())

        self.assertEqual(len(result), 2)
        self.assertEqual(set(result["Symbol"]), {"ALIGNED", "STALE"})

    def test_policy_can_be_disabled(self):
        stale = strong_row(Price_Bar_Aligned=False, Price_Bar_Session_Lag=3)
        result = finalize_recommendations(
            pd.DataFrame([stale]),
            config(REQUIRE_ALIGNED_PRICE_BAR_FOR_BUY=False),
        )

        self.assertEqual(result.loc[0, "Rating"], "STRONG BUY")

    def test_absent_alignment_column_is_not_treated_as_stale(self):
        row = strong_row()
        row.pop("Price_Bar_Aligned")
        row.pop("Price_Bar_Session_Lag")
        result = finalize_recommendations(pd.DataFrame([row]), config())

        self.assertEqual(result.loc[0, "Rating"], "STRONG BUY")


if __name__ == "__main__":
    unittest.main()
