"""Judge the P11 group relative strength variants by the pre-registered rules.

Usage::

    python -m tools.p11_report reports_advanced/p11_fills.csv

See `docs/Review/p11_group_rs_preregistration.md`. Prints only.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from backtest.benchmarks import strategy_period_table
from backtest.metrics import portfolio_metrics

BASE = "model_5"
SPLIT = "2022-10-01"
SIZE = 20
RETURN = "Forward_Return_Chain_Pct"
VARIANTS = (
    "model_5_group_score",
    "model_5_group_gate",
    "model_5_group_score_no_backfill",
    "model_5_group_gate_no_backfill",
)


def net_series(fills, strategy):
    table = strategy_period_table(
        fills, strategy, size=SIZE, return_column=RETURN, cost_rate_column="Cost_Rate_1M",
    )
    return pd.Series(table["Net_Pct"].to_numpy(), index=table["Signal_Date"].astype(str))


def summary(returns_pct):
    halves = (returns_pct[returns_pct.index < SPLIT], returns_pct[returns_pct.index >= SPLIT])
    return [portfolio_metrics(part.to_numpy()) for part in (returns_pct, *halves)]


def passes(base, variant):
    return (
        variant[0]["cagr_pct"] - base[0]["cagr_pct"] >= 2.0
        and variant[1]["cagr_pct"] > base[1]["cagr_pct"]
        and variant[2]["cagr_pct"] > base[2]["cagr_pct"]
        and variant[0]["max_drawdown_pct"] >= base[0]["max_drawdown_pct"] - 3.0
    )


def holdings(fills, strategy):
    """The Top 20 each month, chosen as `strategy_period_table` chooses them."""
    rows = fills[fills["Strategy"] == strategy].dropna(subset=[RETURN, "Score"])
    return (
        rows.sort_values("Score", ascending=False)
        .groupby("Signal_Date", sort=False)
        .head(SIZE)[["Signal_Date", "Security_ID", RETURN]]
    )


def excess_by_group(fills, variant, labels):
    """Gross excess return over `BASE`, summed over months, by the holding's group."""
    def contribution(strategy):
        held = holdings(fills, strategy).merge(labels, on=["Signal_Date", "Security_ID"], how="left")
        held["Group"] = held["Group"].fillna("Unmapped")
        return held.groupby("Group")[RETURN].sum() / SIZE

    return contribution(variant).sub(contribution(BASE), fill_value=0.0).sort_values()


def _residual(values, regressors):
    beta, *_ = np.linalg.lstsq(regressors, values, rcond=None)
    return values - regressors @ beta


def rank_ic(rows):
    """Monthly Spearman of Group_RS_6M with next-month return, raw and partial."""
    raw, partial = [], []
    for _date, period in rows.groupby("Signal_Date"):
        period = period.dropna(subset=["Group_RS_6M", RETURN, "Pct_Change_6M"])
        if len(period) < 30:
            continue
        ranks = period[["Group_RS_6M", RETURN, "Pct_Change_6M"]].rank()
        raw.append(ranks["Group_RS_6M"].corr(ranks[RETURN]))
        own = np.column_stack([np.ones(len(ranks)), ranks["Pct_Change_6M"]])
        partial.append(_residual(ranks["Group_RS_6M"], own).corr(_residual(ranks[RETURN], own)))

    def describe(values):
        values = pd.Series(values).dropna()
        return values.mean(), values.mean() / values.std(ddof=1) * np.sqrt(len(values)), len(values)

    return describe(raw), describe(partial)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("fills")
    args = parser.parse_args(argv)
    fills = pd.read_csv(args.fills, low_memory=False)

    gate = fills[fills["Strategy"] == "model_5_group_gate"]
    print(
        f"Coverage, universe stock-months: mapped {gate['Group'].notna().mean():.1%}, "
        f"back-filled {gate['Group_Backfilled'].astype(bool).mean():.1%}, "
        f"with a reading {gate['Group_RS_6M'].notna().mean():.1%} (kill below 85%)"
    )
    base_top = holdings(fills, BASE).merge(
        gate[["Signal_Date", "Security_ID", "Group"]], on=["Signal_Date", "Security_ID"], how="left"
    )
    print(f"Coverage, model_5 Top 20 holdings: mapped {base_top['Group'].notna().mean():.1%}\n")

    results = {name: summary(net_series(fills, name)) for name in (BASE, *VARIANTS)}
    print(f"Monthly Top 20, net. Halves split at signal {SPLIT}.")
    print(f"{'strategy':34} {'CAGR':>6} {'1st':>6} {'2nd':>6} {'maxDD':>7} {'Sharpe':>6}  pass")
    for name, (full, first, second) in results.items():
        verdict = "" if name == BASE else ("yes" if passes(results[BASE], results[name]) else "no")
        print(f"{name:34} {full['cagr_pct']:6.1f} {first['cagr_pct']:6.1f} {second['cagr_pct']:6.1f} "
              f"{full['max_drawdown_pct']:7.1f} {full['sharpe']:6.2f}  {verdict}")

    for variant in VARIANTS[:2]:
        labels = fills.loc[fills["Strategy"] == variant, ["Signal_Date", "Security_ID", "Group"]]
        excess = excess_by_group(fills, variant, labels)
        total = excess.sum()
        top = excess.drop("Unmapped", errors="ignore")
        share = top.max() / total if total > 0 else float("nan")
        print(f"\n{variant}: gross excess {total:+.1f} pts summed over months; "
              f"largest single group {top.idxmax()} {top.max():+.1f} ({share:.0%} of total)")
        print("  " + ", ".join(f"{group} {value:+.1f}" for group, value in excess.items()))

    (raw, raw_t, months), (partial, partial_t, _) = rank_ic(gate)
    print(f"\nDiagnostic: Group_RS_6M rank IC with next-month return {raw:+.3f} (t {raw_t:.1f}), "
          f"own 6M return partialled out {partial:+.3f} (t {partial_t:.1f}); {months} months")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
