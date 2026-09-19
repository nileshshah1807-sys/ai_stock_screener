"""Point-in-time Model 5 cross-sections with stage features and forward returns.

One row per (rebalance date, security): the production research score, the
factor percentiles, the stage inputs, and 1/3/6/12-month forward returns from
the next session's open. The input to the P4 diagnostics and the P5 overlay
study; building it takes about 20 minutes for 2018-11 to 2026-08.

Usage::

    python -m tools.build_research_panel OUT_DIR 2018-11-01 2026-08-31
"""
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

from backtest.runner import rebalance_dates  # noqa: E402
from backtest.strategies import Model5  # noqa: E402
from tools.run_p0_backtest import build_runner, load_archive  # noqa: E402

out = Path(sys.argv[1])
start, end = sys.argv[2], sys.argv[3]

args = SimpleNamespace(
    root="reports_advanced/backtest", with_fundamentals=True,
    min_turnover=2_000_000.0, min_trading_frequency=0.80, min_history=200,
    delisting_strategy="haircut", recovery_rate=0.5, no_comparison=False,
    gross=False, half_spread=0.0010, impact_coefficient=0.10,
    max_participation=0.10, position_size=100_000.0, horizons="1,3,6,12",
    max_statement_age_days=None, allow_missing_fundamentals=False,
)
archive = load_archive(args.root)
runner, *_ = build_runner(archive, args)
dates = rebalance_dates(archive["calendar"], start, end, frequency="monthly")
logging.info("%d rebalance dates", len(dates))

started = time.monotonic()
fills, _ = runner.run([Model5()], dates)
logging.info("scored %d rows in %.0fs", len(fills), time.monotonic() - started)

keep = [c for c in (
    "Signal_Date", "Security_ID", "Symbol", "Close", "Research_Score",
    "Quality_Percentile", "Growth_Percentile", "Value_Percentile",
    "Momentum_Percentile", "Risk_Percentile",
    "Stage", "Days_In_Stage", "Advance_Age_Days", "Price_To_MA150_Pct",
    "RS_Raw_Pct", "RS_Raw_1M_Ago_Pct", "Price_To_MA200_Pct", "MA200_Slope_Pct",
    "Momentum_12_1_Pct", "Momentum_6_1_Pct", "Pct_Change_6M", "Pct_Change_12M",
    "Median_Turnover_INR", "Volatility_Ann_Pct",
    "Forward_Return_1M_Pct", "Forward_Return_3M_Pct",
    "Forward_Return_6M_Pct", "Forward_Return_12M_Pct",
    "Forward_Return_Chain_Pct", "Cost_Rate_1M",
) if c in fills.columns]
fills[keep].to_csv(out / "research_panel.csv.gz", index=False)
logging.info("wrote %s (%d rows, %d columns)", out / "research_panel.csv.gz", len(fills), len(keep))
