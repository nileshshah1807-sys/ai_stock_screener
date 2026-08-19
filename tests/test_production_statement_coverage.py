"""Fail-closed statement coverage checks at the production composition root."""

import inspect
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

import app
import screener.runtime
from app import enforce_factor_statement_coverage
from validation.reproducibility import DEFAULT_REPRODUCIBILITY_CONFIG_KEYS


def _config(*, enabled=True, floor=0.95):
    return SimpleNamespace(
        FACTOR_MODEL_ENABLED=enabled,
        FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE=floor,
    )


def _frame(available):
    actual = sum(available) / len(available)
    return pd.DataFrame(
        {
            "Symbol": [f"S{i}" for i in range(len(available))],
            "Statement_Record_Available": available,
            "Statement_Universe_Coverage": round(actual, 4),
        }
    )


class ProductionStatementCoverageTests(unittest.TestCase):
    def test_factor_model_passes_at_configured_floor(self):
        enforce_factor_statement_coverage(
            _frame([True] * 95 + [False] * 5), _config()
        )

    def test_factor_model_fails_below_floor_before_scoring(self):
        with self.assertRaisesRegex(
            RuntimeError, r"90/100 \(90\.00%\) < 95\.00%"
        ):
            enforce_factor_statement_coverage(
                _frame([True] * 90 + [False] * 10), _config()
            )

        source = inspect.getsource(app.run_daily_analysis)
        self.assertLess(
            source.index("enforce_factor_statement_coverage"),
            source.index("scorer.score_all_stocks"),
        )

    def test_factor_model_rejects_missing_or_malformed_evidence(self):
        cases = [
            pd.DataFrame({"Symbol": ["A"]}),
            pd.DataFrame(
                {
                    "Symbol": ["A"],
                    "Statement_Record_Available": ["true"],
                    "Statement_Universe_Coverage": [1.0],
                }
            ),
            pd.DataFrame(
                {
                    "Symbol": ["A"],
                    "Statement_Record_Available": [True],
                    "Statement_Universe_Coverage": [np.nan],
                }
            ),
            pd.DataFrame(
                {
                    "Symbol": ["A", "B"],
                    "Statement_Record_Available": [True, False],
                    "Statement_Universe_Coverage": [1.0, 1.0],
                }
            ),
        ]
        for frame in cases:
            with self.subTest(columns=list(frame.columns)):
                with self.assertRaisesRegex(RuntimeError, "coverage check failed"):
                    enforce_factor_statement_coverage(frame, _config())

    def test_invalid_floor_fails_closed(self):
        for floor in ("not-a-number", np.nan, -0.01, 1.01):
            with self.subTest(floor=floor):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE",
                ):
                    enforce_factor_statement_coverage(
                        _frame([True]), _config(floor=floor)
                    )

    def test_factor_model_disabled_is_completely_unaffected(self):
        enforce_factor_statement_coverage(
            pd.DataFrame({"unrelated": ["malformed"]}),
            _config(enabled=False, floor="bad"),
        )

    def test_safe_defaults_and_manifest_wiring_are_pinned(self):
        source = inspect.getsource(screener.runtime.Config)
        fetch_match = re.search(
            r"STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN\s*=\s*_env_int\(\s*"
            r"[\"']STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN[\"']\s*,\s*(\d+)",
            source,
        )
        floor_match = re.search(
            r"FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE\s*=\s*_env_float\(\s*"
            r"[\"']FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE[\"']\s*,\s*([0-9.]+)",
            source,
        )
        self.assertIsNotNone(fetch_match)
        self.assertGreaterEqual(int(fetch_match.group(1)), 2500)
        self.assertIsNotNone(floor_match)
        self.assertEqual(float(floor_match.group(1)), 0.95)
        self.assertIn(
            "FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE",
            DEFAULT_REPRODUCIBILITY_CONFIG_KEYS,
        )


if __name__ == "__main__":
    unittest.main()
