"""Summarize the pre-registered growth-reweight grid across the four windows.

Reads the `p1_*.json` results written by `tools.run_p0_backtest
--growth-reweight-grid` and prints the table the decision rule in
`docs/Review/p1_growth_reweight_preregistration.md` is evaluated against.

It prints every variant, including the losers. That is the point of the
exercise: a grid reported selectively is a single variant with extra steps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("reports_advanced/backtest")
WINDOWS = ("bear", "main", "bs_era", "forward")

# Each grid names its own baseline and ladder. P1 varies growth-block weights
# against the ungated model; P2 varies gate thresholds, so its baseline is the
# gated model -- comparing a relaxed-gate variant against the ungated model
# would measure the gates themselves all over again rather than the relaxation.
GRIDS = {
    "p1": {
        "baseline": "model_5",
        "ladder": (
            "model_5_g1_minimal_swap",
            "model_5_g2_decel_tilted",
            "model_5_g3_turning_dominant",
        ),
        "controls": ("value_only", "growth_only", "quality_only",
                     "momentum_only", "model_5_gated", "random_ranking"),
    },
    "p2": {
        "baseline": "model_5_gated",
        "ladder": (
            "model_5_r1_no_6m_rs",
            "model_5_r2_no_rs",
            "model_5_r3_risk_control_only",
        ),
        "controls": ("model_5", "value_only", "momentum_only",
                     "quality_only", "random_ranking"),
    },
}

PREFIX = sys.argv[1] if len(sys.argv) > 1 else "p1"
if PREFIX not in GRIDS:
    raise SystemExit(f"unknown grid {PREFIX!r}; expected one of {sorted(GRIDS)}")
BASELINE = GRIDS[PREFIX]["baseline"]
LADDER = GRIDS[PREFIX]["ladder"]
CONTROLS = GRIDS[PREFIX]["controls"]


def load(window):
    path = ROOT / f"{PREFIX}_{window}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def excess_cagr(payload):
    """Net CAGR minus the equal-weight eligible universe, per strategy."""
    comparison = (payload or {}).get("comparison") or {}
    strategies = comparison.get("strategies") or {}
    universe = strategies.get("equal_weight_universe") or {}
    base = universe.get("net_cagr_pct")
    if base is None:
        return {}
    out = {}
    for name, entry in strategies.items():
        value = entry.get("net_cagr_pct")
        if value is not None:
            out[name] = value - base
    return out


def rank_ic(payload, horizon="3M"):
    """Mean rank IC at one horizon, per strategy."""
    out = {}
    for name, horizons in (payload or {}).get("net", {}).items():
        entry = (horizons.get(horizon) or {}).get("ic") or {}
        if entry.get("mean") is not None:
            out[name] = entry["mean"]
    return out


def table(title, values, order):
    print(f"\n{title}")
    print(f"  {'strategy':<30}" + "".join(f"{w.upper():>10}" for w in WINDOWS))
    for name in order:
        row = f"  {name:<30}"
        for window in WINDOWS:
            value = values.get(window, {}).get(name)
            row += f"{'--':>10}" if value is None else f"{value:>+10.2f}"
        print(row)


def max_drawdown(payload):
    """Worst top-20 drawdown per strategy, when the comparison reports one."""
    comparison = (payload or {}).get("comparison") or {}
    out = {}
    for name, entry in (comparison.get("strategies") or {}).items():
        for key in ("max_drawdown_pct", "net_max_drawdown_pct", "drawdown_pct"):
            if entry.get(key) is not None:
                out[name] = entry[key]
                break
    return out


def main():
    payloads = {window: load(window) for window in WINDOWS}
    missing = [w for w, p in payloads.items() if p is None]
    if missing:
        print(f"!! missing windows (not yet run): {', '.join(missing)}")

    excess = {w: excess_cagr(p) for w, p in payloads.items()}
    ics = {w: rank_ic(p) for w, p in payloads.items()}

    order = [BASELINE, *LADDER]
    table("NET CAGR vs equal-weight universe (percentage points)", excess, order)
    table("  ...controls", excess, list(CONTROLS))
    table("MEAN RANK IC, 3-month horizon", ics, order)
    drawdowns = {w: max_drawdown(p) for w, p in payloads.items()}
    if any(drawdowns.values()):
        table("MAX DRAWDOWN (top 20, net)", drawdowns, order)

    print("\n\nDECISION RULE (declared before the run)")
    baseline = {w: excess.get(w, {}).get(BASELINE) for w in WINDOWS}
    for name in LADDER:
        wins = downgrade = ic_ok = 0
        counted = ic_counted = 0
        for window in WINDOWS:
            mine = excess.get(window, {}).get(name)
            base = baseline.get(window)
            if mine is not None and base is not None:
                counted += 1
                if mine > base:
                    wins += 1
            my_ic = ics.get(window, {}).get(name)
            base_ic = ics.get(window, {}).get(BASELINE)
            if my_ic is not None and base_ic is not None:
                ic_counted += 1
                if my_ic >= base_ic:
                    ic_ok += 1
        fwd = excess.get("forward", {}).get(name)
        fwd_base = baseline.get("forward")
        if fwd is not None and fwd_base is not None:
            downgrade = fwd_base - fwd
        print(f"\n  {name}")
        print(f"    1. beats baseline in >=3 of 4 windows : {wins}/{counted}"
              f"   {'PASS' if wins >= 3 else 'FAIL'}")
        print(f"    2. FORWARD not worse by >2pp          : {downgrade:+.2f}pp"
              f"   {'PASS' if downgrade <= 2 else 'FAIL'}")
        print(f"    3. rank IC >= baseline in >=3 windows : {ic_ok}/{ic_counted}"
              f"   {'PASS' if ic_ok >= 3 else 'FAIL'}")

    print("\n  4. ordered response across the ladder: inspect the table above."
          "\n     An isolated G2 win with G1 and G3 losing is noise, not signal.")
    print("\n  Mixed or failing result => nothing changes; 5.1 ships as it is.")


if __name__ == "__main__":
    main()
