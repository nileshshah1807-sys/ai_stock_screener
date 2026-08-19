"""Behavioural spec for the P0 PDF report.

The renderer must survive a partial payload without raising, because a run that
produced results should never fail at the last step over a missing optional
section.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backtest.report_pdf import write_pdf


def payload(**overrides):
    base = {
        "generated_at": "2026-08-19T16:00:00",
        "window": {"start": "2022-07-01", "end": "2026-08-11"},
        "frequency": "monthly",
        "rebalance_dates": ["2022-07-29", "2022-08-31"],
        "horizons": [3, 6],
        "universe_rule": {
            "min_median_turnover_inr": 2000000.0,
            "min_trading_frequency": 0.8,
            "min_history_sessions": 200,
            "require_identifier_prefix": "INE",
            "excluded_symbols": [],
        },
        "delisting_policy": "haircut@0.50",
        "cost_model": {
            "half_spread_rate": 0.001,
            "impact_coefficient": 0.1,
            "max_participation_rate": 0.1,
            "value_per_position": 100000.0,
        },
        "securities": {
            "securities_total": 2900,
            "active": 2700,
            "delisted": 80,
            "suspended_at_end": 7,
            "renamed": 114,
            "reused_symbols": 9,
            "face_value_changes": 145,
        },
        "corporate_actions": {
            "ratio_actions": 150,
            "dividend_events": 5000,
            "blocking_events": 60,
        },
        "universe_diagnostics": [
            {"signal_date": "2022-07-29", "input": 1800, "eligible": 1200},
            {"signal_date": "2022-08-31", "input": 1810, "eligible": 1220},
        ],
        "fill_coverage": {
            "3M": {"total": 2400, "ok": 2390, "coverage": 0.9958,
                   "skipped": {"no_entry_price": 10}},
            "6M": {"total": 2400, "ok": 2380, "coverage": 0.9917,
                   "skipped": {"no_entry_price": 20}},
        },
        "turnover": {
            "momentum_only": {"mean_one_way_turnover": 0.52, "periods": 2},
            "equal_weight_universe": {"mean_one_way_turnover": 0.07, "periods": 2},
        },
        "gross": {
            "momentum_only": {
                "3M": {
                    "ic": {"periods": 2, "mean": 0.08, "median": 0.07,
                           "std": 0.02, "positive_share": 1.0, "worst": 0.06,
                           "best": 0.09, "t_stat": 3.1},
                    "buckets": None,
                    "bucket_spread": 6.5,
                    "monotonicity": 0.87,
                    "universe_mean_return_pct": 2.0,
                    "portfolios": {
                        "top_20": {"mean_period_return_pct": 3.4,
                                   "periods": 2, "vs_universe_pct": 1.4}
                    },
                },
                "6M": {
                    "ic": {"periods": 2, "mean": 0.09, "median": 0.09,
                           "std": 0.01, "positive_share": 1.0, "worst": 0.08,
                           "best": 0.1, "t_stat": 4.0},
                    "buckets": None,
                    "bucket_spread": 12.2,
                    "monotonicity": 0.92,
                    "universe_mean_return_pct": 4.0,
                    "portfolios": {
                        "top_20": {"mean_period_return_pct": 8.0,
                                   "periods": 2, "vs_universe_pct": 4.0}
                    },
                },
            },
            "equal_weight_universe": {
                "3M": {
                    "ic": {"periods": 0, "mean": None, "median": None,
                           "std": None, "positive_share": None, "worst": None,
                           "best": None, "t_stat": None},
                    "buckets": None,
                    "bucket_spread": None,
                    "monotonicity": None,
                    "universe_mean_return_pct": 2.0,
                    "portfolios": {"top_20": {"mean_period_return_pct": 2.0,
                                              "periods": 2, "vs_universe_pct": 0.0}},
                }
            },
        },
        "net": None,
    }
    base.update(overrides)
    return base


class WritePdfTests(unittest.TestCase):
    def render(self, data):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.pdf"
            result = write_pdf(data, path)
            self.assertIsNotNone(result)
            self.assertTrue(path.exists())
            return path.read_bytes()

    def test_produces_a_valid_pdf(self):
        content = self.render(payload())
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertGreater(len(content), 2000)

    def test_creates_missing_parent_directories(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deeper" / "report.pdf"
            write_pdf(payload(), path)
            self.assertTrue(path.exists())

    def test_renders_without_a_net_section(self):
        self.assertTrue(self.render(payload(net=None)).startswith(b"%PDF"))

    def test_renders_with_both_gross_and_net(self):
        data = payload()
        data["net"] = data["gross"]
        self.assertTrue(self.render(data).startswith(b"%PDF"))

    def test_renders_without_a_cost_model(self):
        self.assertTrue(self.render(payload(cost_model=None)).startswith(b"%PDF"))

    def test_renders_with_empty_turnover_and_coverage(self):
        data = payload(turnover={}, fill_coverage={})
        self.assertTrue(self.render(data).startswith(b"%PDF"))

    def test_renders_with_no_universe_diagnostics(self):
        self.assertTrue(
            self.render(payload(universe_diagnostics=[])).startswith(b"%PDF")
        )

    def test_renders_when_every_metric_is_none(self):
        """A run that produced nothing must still yield a readable document."""
        data = payload()
        data["gross"] = {
            "momentum_only": {
                "3M": {
                    "ic": {"periods": 0, "mean": None, "median": None,
                           "std": None, "positive_share": None,
                           "worst": None, "best": None, "t_stat": None},
                    "buckets": None,
                    "bucket_spread": None,
                    "monotonicity": None,
                    "universe_mean_return_pct": None,
                    "portfolios": {"top_20": {}},
                }
            }
        }
        self.assertTrue(self.render(data).startswith(b"%PDF"))

    def test_renders_with_an_empty_payload(self):
        self.assertTrue(self.render({}).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
