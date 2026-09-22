"""Fail-closed price-session alignment at the production composition root.

Regression for the 21 Sept 2026 US run: Yahoo returned the session's row
without usable values shortly after the close, so every symbol kept its prior
bar. The run scored Friday under Monday's name, the publisher dated it Friday,
found Friday published and skipped -- a green workflow that refreshed nothing.
"""

import inspect
import re
import unittest
from types import SimpleNamespace

import pandas as pd

import app
import screener.runtime
from app import enforce_price_session_alignment


def _config(floor=0.90):
    return SimpleNamespace(MIN_PRICE_SESSION_ALIGNMENT=floor)


def _frame(aligned, lagging, expected="2026-09-21", prior="2026-09-18"):
    total = aligned + lagging
    return pd.DataFrame(
        {
            "Symbol": [f"S{i}" for i in range(total)],
            "Price_Bar_As_Of": [expected] * aligned + [prior] * lagging,
            "Expected_Price_Bar_As_Of": [expected] * total,
        }
    )


class PriceSessionAlignmentTests(unittest.TestCase):
    def test_a_few_lagging_symbols_do_not_fail_the_run(self):
        enforce_price_session_alignment(_frame(2317, 1), _config())
        enforce_price_session_alignment(_frame(90, 10), _config())

    def test_whole_session_vendor_lag_fails_before_fundamentals(self):
        with self.assertRaisesRegex(
            RuntimeError,
            r"2026-09-21: 0/1495 \(0\.00%\) aligned < 90\.00%; "
            r"latest usable bar is 2026-09-18",
        ):
            enforce_price_session_alignment(_frame(0, 1495), _config())

        source = inspect.getsource(app.run_daily_analysis)
        self.assertLess(
            source.index("collector.download_stock_data"),
            source.index("enforce_price_session_alignment"),
        )
        self.assertLess(
            source.index("enforce_price_session_alignment"),
            source.index("collector.get_fundamental_data"),
        )

    def test_below_floor_fails(self):
        with self.assertRaisesRegex(RuntimeError, r"89/100 \(89\.00%\)"):
            enforce_price_session_alignment(_frame(89, 11), _config())

    def test_missing_or_ambiguous_provenance_fails_closed(self):
        cases = [
            pd.DataFrame({"Symbol": ["A"], "Price_Bar_As_Of": ["2026-09-21"]}),
            pd.DataFrame(
                {
                    "Symbol": ["A", "B"],
                    "Price_Bar_As_Of": ["2026-09-21", "2026-09-21"],
                    "Expected_Price_Bar_As_Of": ["2026-09-21", "2026-09-18"],
                }
            ),
        ]
        for frame in cases:
            with self.subTest(columns=list(frame.columns)), self.assertRaises(RuntimeError):
                enforce_price_session_alignment(frame, _config())

    def test_invalid_floor_fails_closed(self):
        for floor in ("bad", float("nan"), -0.1, 1.1):
            with self.subTest(floor=floor), self.assertRaisesRegex(
                RuntimeError, "MIN_PRICE_SESSION_ALIGNMENT"
            ):
                enforce_price_session_alignment(_frame(1, 0), _config(floor))

    def test_default_floor_is_pinned(self):
        source = inspect.getsource(screener.runtime.Config)
        match = re.search(
            r"MIN_PRICE_SESSION_ALIGNMENT\s*=\s*_env_float\(\s*"
            r"[\"']MIN_PRICE_SESSION_ALIGNMENT[\"']\s*,\s*([0-9.]+)",
            source,
        )
        self.assertIsNotNone(match)
        self.assertEqual(float(match.group(1)), 0.90)


if __name__ == "__main__":
    unittest.main()
