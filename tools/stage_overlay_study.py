"""Stage as a portfolio overlay: exit on a Stage 4 break, and cash on low breadth.

P3/P4 showed stage does not improve the research *ranking*. This asks the two
questions a ranking backtest cannot see (`docs/Review/p5_stage_overlay_preregistration.md`):

* **Exit rule.** Hold the research top 20; if a holding breaks into Stage 4 (or,
  in the stricter variant, Stage 3 or 4) before the next rebalance, sell it at
  the next session's close and hold the proceeds in cash until then.
* **Breadth rule.** At each rebalance, if the share of the liquid universe in
  Stage 2 is below a threshold fixed from the DISCOVERY period, hold part or
  all of the portfolio in cash for that period.

The simulation is daily, on adjusted closes from the point-in-time archive, so
an exit is priced on the day it would actually have happened. Stages come from
`screener.stage.classify_stages`, the production function. Selection comes from
a research panel of point-in-time Model 5 scores (one row per rebalance and
security), so every variant holds exactly the names the model would have.

Usage::

    python -m tools.stage_overlay_study --panel research_panel.csv.gz --breadth-only
    python -m tools.stage_overlay_study --panel research_panel.csv.gz --out p5.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

import numpy as np
import pandas as pd

logger = logging.getLogger("stage_overlay_study")

DISCOVERY = ("2018-11-01", "2022-12-31")
CONFIRM = ("2023-01-01", "2026-08-31")

TOP_N = 20
COST_PER_SIDE = 0.0030          # fraction of traded value, each buy and each sell
CASH_RATE_ANNUAL = 0.06         # Indian T-bill order of magnitude
SESSIONS_PER_YEAR = 248
MIN_LIQUID_TURNOVER_INR = 2_000_000.0

STAGE_CODES = {"Stage 1": 1, "Stage 2": 2, "S2 Candidate": 25, "Stage 3": 3, "Stage 4": 4}


def load_prices(root):
    """Wide adjusted closes and 60-session median turnover, one column per security."""
    from tools.run_p0_backtest import load_archive

    archive = load_archive(root)
    frame = archive["price_panel"].frame
    frame = frame.assign(Trade_Date=pd.to_datetime(frame["Trade_Date"]))
    close_column = "Adj_Close" if "Adj_Close" in frame.columns else "Close"
    closes = frame.pivot_table(index="Trade_Date", columns="Security_ID", values=close_column)
    turnover = frame.pivot_table(index="Trade_Date", columns="Security_ID", values="Turnover_INR")
    turnover = turnover.reindex(index=closes.index, columns=closes.columns)
    closes.columns = closes.columns.astype(str)
    turnover.columns = turnover.columns.astype(str)
    return closes, turnover.rolling(60, min_periods=40).median()


def stage_codes(closes):
    """Daily stage for every security, via the production classifier."""
    from screener.stage import classify_stages

    coded = {}
    for column in closes.columns:
        series = closes[column]
        valid = series.dropna()
        if len(valid) < 221:
            continue
        labels = classify_stages(valid.reset_index(drop=True))
        coded[column] = pd.Series(
            labels.map(STAGE_CODES).to_numpy(dtype=float), index=valid.index
        )
    return pd.DataFrame(coded).reindex(index=closes.index, columns=closes.columns)


def breadth(stages, liquid_turnover):
    """Share of the liquid, classifiable universe in Stage 2, per session."""
    liquid = (liquid_turnover >= MIN_LIQUID_TURNOVER_INR) & stages.notna()
    in_stage_2 = (stages == 2) & liquid
    return in_stage_2.sum(axis=1) / liquid.sum(axis=1).replace(0, np.nan)


def next_session(index, day):
    position = index.searchsorted(day, side="right")
    return index[position] if position < len(index) else None


def simulate(panel, closes, stages, width, rebalances, *, exit_codes=None,
             cash_fraction_for=None, closing=None):
    """Daily equity curve for one variant over one rebalance schedule.

    ``closing``: the signal date whose next session ends the final period --
    the next rebalance on the schedule after the window. Without it the final
    period would run to the end of the archive, and a DISCOVERY window would
    silently hold its last portfolio through every later year. ``None`` is only
    correct when the window genuinely ends at the end of the data.
    ``exit_codes``: stage codes that trigger an exit, counted only as a break
    *into* them after entry, so a name bought in Stage 4 is not sold for being
    in Stage 4 (the rule is about deterioration, not the entry decision).
    ``cash_fraction_for``: callable(signal_date) -> fraction held in cash.
    """
    sessions = closes.index
    cash_daily = (1.0 + CASH_RATE_ANNUAL) ** (1.0 / SESSIONS_PER_YEAR) - 1.0
    equity, dates = [], []
    value = 1.0
    previous_weights = {}
    exits = 0
    invested_share = []

    for i, signal in enumerate(rebalances):
        entry = next_session(sessions, signal)
        if entry is None:
            break
        if i + 1 < len(rebalances):
            stop = next_session(sessions, rebalances[i + 1])
        elif closing is not None:
            stop = next_session(sessions, closing)
        else:
            stop = sessions[-1]
        if stop is None or stop <= entry:
            break
        cross = panel[panel["Signal_Date"] == signal]
        cross = cross[cross["Security_ID"].isin(closes.columns)]
        cross = cross[closes.loc[entry, cross["Security_ID"]].notna().to_numpy()]
        picks = (
            cross.sort_values(["Research_Score", "Security_ID"], ascending=[False, True])
            .head(TOP_N)["Security_ID"]
            .tolist()
        )
        if not picks:
            continue
        cash_share = float(cash_fraction_for(signal)) if cash_fraction_for else 0.0
        invested_share.append(1.0 - cash_share)
        weight = (1.0 - cash_share) / len(picks)
        target = {name: weight for name in picks}
        if cash_share:
            target["CASH"] = cash_share

        # Rebalance cost: one side on every unit of weight that changes hands,
        # cash included as a costless asset.
        names = set(target) | set(previous_weights)
        traded = sum(
            abs(target.get(n, 0.0) - previous_weights.get(n, 0.0))
            for n in names
            if n != "CASH"
        )
        value *= 1.0 - COST_PER_SIDE * traded

        window = sessions[(sessions >= entry) & (sessions <= stop)]
        prices = closes.loc[window, picks].ffill()
        base = prices.iloc[0]
        growth = prices / base                      # per-name value multiple
        entry_stage = stages.loc[entry, picks]
        position_value = pd.DataFrame(growth.to_numpy() * weight,
                                      index=window, columns=picks)
        if exit_codes:
            period_stages = stages.loc[window, picks]
            for name in picks:
                if entry_stage.get(name) in exit_codes:
                    continue
                broke = period_stages[name].isin(exit_codes).to_numpy()
                if not broke[1:].any():
                    continue
                first = int(np.argmax(broke[1:])) + 1
                sell_at = min(first + 1, len(window) - 1)
                proceeds = position_value[name].iloc[sell_at] * (1.0 - COST_PER_SIDE)
                days_in_cash = np.arange(len(window) - sell_at)
                position_value.iloc[sell_at:, position_value.columns.get_loc(name)] = (
                    proceeds * (1.0 + cash_daily) ** days_in_cash
                )
                exits += 1
                # Re-marked as cash so the next rebalance pays to buy it back.
                growth.loc[window[sell_at]:, name] = np.nan
        cash_path = cash_share * (1.0 + cash_daily) ** np.arange(len(window))
        total = position_value.sum(axis=1).to_numpy() + cash_path
        period = value * total / total[0]

        start = 1 if equity else 0  # the entry session closes the previous period
        equity.extend(period[start:])
        dates.extend(window[start:])
        value = float(period[-1])

        ending = position_value.iloc[-1]
        still_held = growth.iloc[-1].notna()
        end_total = total[-1]
        previous_weights = {
            name: float(ending[name] / end_total) for name in picks if still_held[name]
        }
        sold = float(sum(ending[name] for name in picks if not still_held[name]))
        previous_weights["CASH"] = float((cash_path[-1] + sold) / end_total)

    curve = pd.Series(equity, index=pd.DatetimeIndex(dates))
    return curve, exits, (float(np.mean(invested_share)) if invested_share else np.nan)


def metrics(curve):
    daily = curve.pct_change().dropna()
    years = len(daily) / SESSIONS_PER_YEAR
    cagr = curve.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan
    cash_daily = (1.0 + CASH_RATE_ANNUAL) ** (1.0 / SESSIONS_PER_YEAR) - 1.0
    excess = daily - cash_daily
    sharpe = excess.mean() / excess.std(ddof=1) * np.sqrt(SESSIONS_PER_YEAR)
    drawdown = (curve / curve.cummax() - 1.0).min()
    return {
        "cagr_pct": round(100 * cagr, 2),
        "vol_pct": round(100 * daily.std(ddof=1) * np.sqrt(SESSIONS_PER_YEAR), 2),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown_pct": round(100 * float(drawdown), 2),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, help="research panel CSV")
    parser.add_argument("--root", default="reports_advanced/backtest")
    parser.add_argument("--breadth-only", action="store_true",
                        help="print DISCOVERY breadth percentiles and stop")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    panel = pd.read_csv(args.panel, usecols=["Signal_Date", "Security_ID", "Research_Score"],
                        dtype={"Security_ID": str})
    panel["Signal_Date"] = pd.to_datetime(panel["Signal_Date"])
    closes, liquid = load_prices(args.root)
    logger.info("classifying %d securities", closes.shape[1])
    stages = stage_codes(closes)
    width = breadth(stages, liquid)

    all_dates = sorted(panel["Signal_Date"].unique())
    discovery_dates = [d for d in all_dates if DISCOVERY[0] <= str(d.date()) <= DISCOVERY[1]]
    discovery_breadth = width.reindex(discovery_dates)
    percentiles = {p: float(discovery_breadth.quantile(p / 100)) for p in (10, 20, 50)}
    print("DISCOVERY breadth (share of liquid universe in Stage 2) at rebalances:",
          {f"p{k}": round(v, 3) for k, v in percentiles.items()})
    if args.breadth_only:
        return 0

    thresholds = {"p10": percentiles[10], "p20": percentiles[20]}

    def cash_rule(threshold, fraction):
        return lambda day: fraction if width.asof(day) < threshold else 0.0

    variants = {
        "B0 baseline": {},
        "X4 exit on Stage 4 break": {"exit_codes": {4}},
        "X34 exit on Stage 3/4 break": {"exit_codes": {3, 4}},
        "C10-50 half cash, breadth < p10": {"cash_fraction_for": cash_rule(thresholds["p10"], 0.5)},
        "C10-100 all cash, breadth < p10": {"cash_fraction_for": cash_rule(thresholds["p10"], 1.0)},
        "C20-50 half cash, breadth < p20": {"cash_fraction_for": cash_rule(thresholds["p20"], 0.5)},
        "C20-100 all cash, breadth < p20": {"cash_fraction_for": cash_rule(thresholds["p20"], 1.0)},
    }

    report = {"thresholds": thresholds, "cost_per_side": COST_PER_SIDE,
              "cash_rate": CASH_RATE_ANNUAL, "results": {}}
    for window_name, (start, end) in (("DISCOVERY", DISCOVERY), ("CONFIRM", CONFIRM)):
        dates = [d for d in all_dates if start <= str(d.date()) <= end]
        for schedule in ("monthly", "quarterly"):
            offsets = [0] if schedule == "monthly" else [0, 1, 2]
            for name, options in variants.items():
                if schedule == "quarterly" and name.startswith("C"):
                    continue  # the breadth rule is declared on the monthly schedule only
                rows = []
                for offset in offsets:
                    step = 1 if schedule == "monthly" else 3
                    schedule_dates = dates if schedule == "monthly" else dates[offset::3]
                    if not schedule_dates:
                        continue
                    following = all_dates.index(schedule_dates[-1]) + step
                    closing = all_dates[following] if following < len(all_dates) else None
                    curve, exits, invested = simulate(
                        panel, closes, stages, width, schedule_dates,
                        closing=closing, **options
                    )
                    rows.append({**metrics(curve), "exits": exits, "invested": invested})
                averaged = {k: round(float(np.mean([r[k] for r in rows])), 3) for k in rows[0]}
                report["results"].setdefault(window_name, {}).setdefault(schedule, {})[name] = averaged
                logger.info("%s %s %s %s", window_name, schedule, name, averaged)

    for window_name, schedules in report["results"].items():
        for schedule, results in schedules.items():
            print(f"\n{window_name} -- {schedule}")
            print(pd.DataFrame(results).T.to_string())
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
