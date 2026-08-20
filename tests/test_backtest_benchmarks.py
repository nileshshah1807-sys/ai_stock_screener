"""Behavioural spec for index benchmarks and the CAGR comparison.

The load-bearing test is ``test_compounding_requires_chaining_periods``: a CAGR
built from overlapping horizons counts the same market move several times and
produces a number that could not have happened.
"""

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from backtest.benchmarks import (
    IndexSeries,
    IndexStore,
    build_comparison,
    compound_cagr,
    normalise_index_rows,
    strategy_period_returns,
    strategy_period_table,
    universe_period_returns,
)
from backtest.calendar import TradingCalendar
from backtest.comparison_pdf import write_comparison_pdf


def index_frame():
    rows = []
    for name, start in (("NIFTY 500", 100.0), ("NIFTY 50", 200.0)):
        level = start
        for month in range(1, 13):
            rows.append(
                {
                    "Index": name,
                    "Trade_Date": date(2024, month, 1).isoformat(),
                    "Open": level,
                    "High": level,
                    "Low": level,
                    "Close": level,
                }
            )
            level *= 1.01
    return pd.DataFrame(rows)


class NormaliseTests(unittest.TestCase):
    def raw(self):
        return [
            {
                "EOD_TIMESTAMP": "01-Jan-2024",
                "EOD_OPEN_INDEX_VAL": 19452,
                "EOD_HIGH_INDEX_VAL": 19543.25,
                "EOD_LOW_INDEX_VAL": 19421.4,
                "EOD_CLOSE_INDEX_VAL": 19469.5,
            },
            {"EOD_TIMESTAMP": "bad-date", "EOD_CLOSE_INDEX_VAL": 100},
            {"EOD_TIMESTAMP": "02-Jan-2024", "EOD_CLOSE_INDEX_VAL": 0},
        ]

    def test_valid_row_is_kept(self):
        frame = normalise_index_rows("NIFTY 500", self.raw())
        self.assertEqual(len(frame), 1)
        self.assertAlmostEqual(frame["Close"].iloc[0], 19469.5)

    def test_unparseable_date_is_dropped(self):
        self.assertEqual(len(normalise_index_rows("X", self.raw())), 1)

    def test_non_positive_close_is_dropped(self):
        frame = normalise_index_rows("X", self.raw())
        self.assertTrue((frame["Close"] > 0).all())

    def test_empty_input_returns_schema(self):
        frame = normalise_index_rows("X", [])
        self.assertTrue(frame.empty)
        self.assertIn("Close", frame.columns)


class IndexSeriesTests(unittest.TestCase):
    def setUp(self):
        self.series = IndexSeries(index_frame())

    def test_names_are_listed(self):
        self.assertEqual(self.series.names(), ["NIFTY 50", "NIFTY 500"])

    def test_level_on_an_exact_session(self):
        self.assertAlmostEqual(
            self.series.level_on_or_before("NIFTY 500", date(2024, 1, 1)), 100.0
        )

    def test_level_falls_back_to_the_prior_session(self):
        """Index and equity calendars can differ by a session or two."""
        self.assertAlmostEqual(
            self.series.level_on_or_before("NIFTY 500", date(2024, 1, 3)), 100.0
        )

    def test_a_fortnight_old_level_is_refused(self):
        """Two weeks is a data gap, not a calendar mismatch."""
        self.assertIsNone(
            self.series.level_on_or_before("NIFTY 500", date(2024, 1, 15))
        )

    def test_level_before_all_history_is_none(self):
        self.assertIsNone(
            self.series.level_on_or_before("NIFTY 500", date(2023, 1, 1))
        )

    def test_fallback_refuses_to_reach_across_a_data_gap(self):
        """The regression this bound exists for.

        The endpoint silently truncates long requests, leaving months-long holes.
        An unbounded fallback answered a query for October with a level from
        April, turning a +22.7% index move into +4.9% -- a wrong CAGR that looked
        entirely plausible. Beyond the bound the period must be dropped instead.
        """
        gapped = IndexSeries(
            pd.DataFrame(
                [
                    {"Index": "GAPPY", "Trade_Date": "2024-01-01", "Close": 100.0},
                    {"Index": "GAPPY", "Trade_Date": "2024-09-01", "Close": 150.0},
                ]
            )
        )
        self.assertIsNone(
            gapped.level_on_or_before("GAPPY", date(2024, 6, 1))
        )

    def test_fallback_still_bridges_a_one_session_mismatch(self):
        """The bound must not break its actual purpose."""
        gapped = IndexSeries(
            pd.DataFrame(
                [{"Index": "GAPPY", "Trade_Date": "2024-01-01", "Close": 100.0}]
            )
        )
        self.assertAlmostEqual(
            gapped.level_on_or_before("GAPPY", date(2024, 1, 3)), 100.0
        )

    def test_period_return_is_dropped_when_a_leg_is_unresolvable(self):
        gapped = IndexSeries(
            pd.DataFrame(
                [
                    {"Index": "GAPPY", "Trade_Date": "2024-01-01", "Close": 100.0},
                    {"Index": "GAPPY", "Trade_Date": "2024-09-01", "Close": 150.0},
                ]
            )
        )
        self.assertIsNone(
            gapped.period_return_pct("GAPPY", date(2024, 1, 1), date(2024, 6, 1))
        )

    def test_period_return_between_two_sessions(self):
        value = self.series.period_return_pct(
            "NIFTY 500", date(2024, 1, 1), date(2024, 2, 1)
        )
        self.assertAlmostEqual(value, 1.0, places=6)

    def test_unknown_index_yields_no_return(self):
        self.assertIsNone(
            self.series.period_return_pct("NOPE", date(2024, 1, 1), date(2024, 2, 1))
        )

    def test_empty_series_is_safe(self):
        self.assertEqual(IndexSeries(pd.DataFrame()).names(), [])


class CompoundCagrTests(unittest.TestCase):
    def test_twelve_one_percent_months(self):
        self.assertAlmostEqual(
            compound_cagr([1.0] * 12, periods_per_year=12), 12.6825, places=3
        )

    def test_flat_returns_give_zero(self):
        self.assertAlmostEqual(compound_cagr([0.0] * 12, periods_per_year=12), 0.0)

    def test_total_loss_floors_at_minus_one_hundred(self):
        self.assertAlmostEqual(
            compound_cagr([-100.0, 5.0], periods_per_year=12), -100.0
        )

    def test_empty_input_is_none(self):
        self.assertIsNone(compound_cagr([], periods_per_year=12))

    def test_compounding_requires_chaining_periods(self):
        """Overlapping horizons would multiply the same move repeatedly.

        Six 6-month returns of +10%, if they were genuinely consecutive, compound
        to far more than the same six sampled monthly actually earned. The
        function cannot detect the caller's mistake, so this test documents the
        magnitude of the error the contract exists to prevent.
        """
        as_if_chaining = compound_cagr([10.0] * 6, periods_per_year=12)
        truth = compound_cagr([10.0], periods_per_year=2)
        self.assertGreater(as_if_chaining, truth * 2)


def fills_frame():
    rows = []
    for period, signal in enumerate(["2024-01-31", "2024-02-29", "2024-03-31"]):
        for strategy, base in (("model_5", 2.0), ("equal_weight_universe", 0.0)):
            for index in range(30):
                score = 50.0 if strategy == "equal_weight_universe" else float(index)
                rows.append(
                    {
                        "Strategy": strategy,
                        "Signal_Date": signal,
                        "Security_ID": f"INE{index:03d}A01",
                        "Score": score,
                        "Forward_Return_1M_Pct": base + index * 0.1,
                        "Forward_Return_Chain_Pct": base + index * 0.1,
                        "Cost_Rate_1M": 0.004,
                    }
                )
    return pd.DataFrame(rows)


class PeriodReturnTests(unittest.TestCase):
    def test_top_n_selects_the_highest_scores(self):
        _dates, returns = strategy_period_returns(
            fills_frame(), "model_5", size=5
        )
        # Top 5 of index 25..29 -> base 2.0 plus mean 2.7
        self.assertAlmostEqual(returns[0], 2.0 + 2.7, places=6)

    def test_constant_score_uses_the_whole_universe(self):
        """A flat score cannot rank; its portfolio is the eligible universe."""
        _dates, returns = strategy_period_returns(
            fills_frame(), "equal_weight_universe", size=5
        )
        self.assertAlmostEqual(returns[0], 1.45, places=6)

    def test_one_return_per_rebalance(self):
        dates, returns = strategy_period_returns(fills_frame(), "model_5", size=5)
        self.assertEqual(len(dates), 3)
        self.assertEqual(len(returns), 3)

    def test_universe_return_counts_each_security_once(self):
        _dates, returns = universe_period_returns(
            fills_frame(), return_column="Forward_Return_Chain_Pct"
        )
        self.assertAlmostEqual(returns[0], 1.45, places=6)

    def test_unknown_strategy_yields_nothing(self):
        self.assertEqual(strategy_period_returns(fills_frame(), "nope"), ([], []))


class BuildComparisonTests(unittest.TestCase):
    def calendar(self):
        return TradingCalendar(
            [date(2024, month, 1) for month in range(1, 13)]
            + [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)]
        )

    def test_comparison_reports_cagr_per_strategy_and_index(self):
        result = build_comparison(
            fills_frame(), IndexSeries(index_frame()), self.calendar(), size=5
        )
        self.assertIn("model_5", result["strategies"])
        self.assertIn("NIFTY 500", result["indices"])
        self.assertIsNotNone(result["strategies"]["model_5"]["gross_cagr_pct"])

    def test_difference_is_strategy_minus_index(self):
        result = build_comparison(
            fills_frame(), IndexSeries(index_frame()), self.calendar(), size=5
        )
        versus = result["strategies"]["model_5"]["versus"]["NIFTY 500"]
        self.assertAlmostEqual(
            versus["cagr_difference_pct"],
            versus["strategy_cagr_pct"] - versus["index_cagr_pct"],
            places=4,
        )

    def test_net_basis_is_used_when_available(self):
        result = build_comparison(
            fills_frame(), IndexSeries(index_frame()), self.calendar(), size=5
        )
        self.assertEqual(
            result["strategies"]["model_5"]["versus"]["NIFTY 500"]["basis"], "net"
        )

    def test_eligible_universe_cagr_is_reported(self):
        result = build_comparison(
            fills_frame(), IndexSeries(index_frame()), self.calendar(), size=5
        )
        self.assertIsNotNone(result["eligible_universe"]["cagr_pct"])

    def test_empty_fills_yield_no_comparison(self):
        self.assertEqual(
            build_comparison(pd.DataFrame(), IndexSeries(index_frame()), self.calendar()),
            {},
        )


class ComparisonPdfTests(unittest.TestCase):
    def payload(self, comparison):
        return {
            "generated_at": "2026-08-20T12:00:00",
            "window": {"start": "2024-01-01", "end": "2024-04-01"},
            "frequency": "monthly",
            "turnover": {"model_5": {"mean_one_way_turnover": 0.34, "periods": 3}},
            "comparison": comparison,
        }

    def comparison(self):
        return build_comparison(
            fills_frame(),
            IndexSeries(index_frame()),
            TradingCalendar(
                [date(2024, m, 1) for m in range(1, 13)]
                + [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)]
            ),
            size=5,
        )

    def test_produces_a_valid_pdf(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "comparison.pdf"
            result = write_comparison_pdf(self.payload(self.comparison()), path)
            self.assertIsNotNone(result)
            self.assertTrue(path.read_bytes().startswith(b"%PDF"))

    def test_missing_comparison_is_skipped_not_fatal(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "comparison.pdf"
            self.assertIsNone(write_comparison_pdf({"window": {}}, path))

    def test_renders_without_turnover(self):
        with TemporaryDirectory() as tmp:
            payload = self.payload(self.comparison())
            payload.pop("turnover")
            path = Path(tmp) / "comparison.pdf"
            self.assertIsNotNone(write_comparison_pdf(payload, path))


class IndexStoreTests(unittest.TestCase):
    def test_missing_cache_loads_empty(self):
        with TemporaryDirectory() as tmp:
            store = IndexStore(Path(tmp) / "indices.csv")
            self.assertTrue(store.load().empty)

    def test_round_trip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "indices.csv"
            index_frame().to_csv(path, index=False)
            self.assertEqual(len(IndexStore(path).load()), 24)

    def test_fetch_merges_with_the_cache_instead_of_replacing_it(self):
        """The endpoint returns intermittent 500s, so a run can come back with
        holes. Overwriting would discard sessions an earlier run fetched and make
        the gaps permanent; merging means re-running heals them."""

        class StubNSE:
            def __init__(self, folder):
                self.folder = folder

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def fetch_historical_index_data(self, index, from_date, to_date):
                return [
                    {
                        "EOD_TIMESTAMP": "05-Feb-2024",
                        "EOD_CLOSE_INDEX_VAL": 999.0,
                    }
                ]

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "indices.csv"
            index_frame().to_csv(path, index=False)
            store = IndexStore(path, nse_factory=StubNSE)
            merged = store.fetch(["NIFTY 500"], date(2024, 2, 1), date(2024, 2, 28))
            # The 24 pre-existing rows survive alongside the newly fetched one.
            self.assertEqual(len(merged), 25)
            self.assertIn("2024-02-05", set(merged["Trade_Date"]))


if __name__ == "__main__":
    unittest.main()


class TurnoverAwareCostTests(unittest.TestCase):
    """Costs must fall on what actually traded, not on everything held.

    Charging a full round trip to every holding every period made a 9%-turnover
    benchmark look as expensive as a 96%-turnover one, wiping ~22 annualised
    points off both alike and destroying the p0.md §7C comparison.
    """

    def table(self, strategy):
        return strategy_period_table(
            fills_frame(), strategy, size=5, cost_rate_column="Cost_Rate_1M"
        )

    def test_cost_scales_with_turnover(self):
        ranked = self.table("model_5")
        # A stable ranking turns over nothing after the initial build.
        self.assertAlmostEqual(ranked["Turnover"].iloc[1], 0.0, places=6)
        self.assertAlmostEqual(ranked["Cost_Pct"].iloc[1], 0.0, places=6)

    def test_initial_build_pays_one_buy_leg(self):
        ranked = self.table("model_5")
        # Building from cash is a one-way turnover of 0.5 at a 0.4% round trip.
        self.assertAlmostEqual(ranked["Turnover"].iloc[0], 0.5, places=6)
        self.assertAlmostEqual(ranked["Cost_Pct"].iloc[0], 0.5 * 0.4, places=6)

    def test_net_never_exceeds_gross(self):
        ranked = self.table("model_5")
        self.assertTrue((ranked["Net_Pct"] <= ranked["Gross_Pct"] + 1e-9).all())

    def test_a_held_position_is_not_charged_again(self):
        ranked = self.table("model_5")
        self.assertAlmostEqual(
            ranked["Net_Pct"].iloc[1], ranked["Gross_Pct"].iloc[1], places=9
        )

    def test_missing_cost_column_yields_zero_cost(self):
        table = strategy_period_table(fills_frame(), "model_5", size=5)
        self.assertTrue((table["Cost_Pct"] == 0.0).all())

    def test_unknown_strategy_yields_empty_table(self):
        self.assertTrue(
            strategy_period_table(fills_frame(), "nope", size=5).empty
        )
