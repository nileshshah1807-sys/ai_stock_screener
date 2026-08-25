"""Model 5.0 eligibility gates, evaluated on point-in-time evidence.

The production score is not what reaches the dashboard. `Research_Score` is
ranked, then `screener.recommendation` applies a gate set that caps ineligible
names at 59.99 (failed a BUY gate) or 69.99 (BUY-eligible, failed a STRONG BUY
gate), and the published order is `Eligibility_Class` first, `Research_Score`
second. So the list a user actually buys from is the *gated* ranking, and every
`p0.md` result so far measured the ungated one.

This module reproduces `RecommendationPolicy._factor_gate_failures` -- the Model
5.0 gate set -- so the two can be compared on the same archive. Note that the
4.x trend gates (MA50, ADX, +DI/-DI, absolute growth) are **not** part of this:
`recommendation.py` disables them when the factor model is active, on the
grounds that Model 5.0 expresses the same intent through the MA200 stack and
the momentum percentile. Reproducing them here would test a policy that never
runs.

**Gates reproduced faithfully**

* price within the MA200 tolerance band, and MA200 slope not falling
* confirmed breakdown (below-MA200 streak + falling average + weak 6M RS)
* 6-month market relative strength positive
* quality percentile floors (BUY 40, STRONG BUY 70)
* per-block coverage sufficiency
* growth and momentum percentile floors (STRONG BUY 60 / 70)
* price > MA50 > MA200 stack, MA200 rising
* 12-month market relative strength positive
* market regime overlay (risk-off and neutral)

**Gates deliberately omitted**, because the archive cannot support them and
guessing would be worse than declaring the gap:

* ``sector relative strength`` -- no point-in-time sector map exists that does
  not reintroduce survivorship. Production only fails on an *observed* negative
  reading and never on absence, so omitting it matches production behaviour for
  a name whose sector is unknown.
* ``Fundamental_Coverage`` / ``Technical_Coverage`` floors -- produced by
  ``screener.scoring.StockScorer``, which the backtest does not run. The
  per-block ``*_Coverage_Sufficient`` flags from ``FactorModel`` are applied and
  cover much of the same ground.
* ``Portfolio_Actionable`` liquidity -- the backtest already applies a turnover
  and trading-frequency screen when it builds the universe, so every name
  reaching a gate has cleared an execution filter of the same kind.
* the shared data-integrity gates (``Data_Quality`` LOW, stale fundamental
  fallback, price bar behind session, fundamental anomalies). These are hygiene
  rules about inputs, not investment bets, and the archive's own point-in-time
  construction already excludes what they exclude.

The omissions all sit on the BUY side, so a gated backtest is *more* permissive
than production, not less. Read a positive result as an upper bound.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Ceilings mirror ``_rating_ceiling``; the ordering they induce is what matters
# here, not the numbers themselves.
CEILING_BUY_FAILED = 59.99
CEILING_STRONG_FAILED = 69.99
CEILING_CLEAR = 100.0

# Eligibility_Class: 0 clears everything, 1 BUY-eligible only, 2 policy-capped.
CLASS_CLEAR = 0
CLASS_BUY_ONLY = 1
CLASS_CAPPED = 2

RISK_OFF = "RISK_OFF"
NEUTRAL = "NEUTRAL"


class GateConfig:
    """Production gate thresholds, defaulted to `screener.runtime.Config`."""

    BUY_MA200_TOLERANCE = 0.98
    BUY_MIN_MA200_SLOPE_PCT = 0.0
    BREAKDOWN_CONFIRM_SESSIONS = 10
    BUY_MIN_RS_6M = 0.0
    BUY_MIN_QUALITY_PCT = 40.0
    STRONG_BUY_MIN_QUALITY_PCT = 70.0
    STRONG_BUY_MIN_GROWTH_PCT = 60.0
    STRONG_BUY_MIN_MOMENTUM_PCT = 0.0        # policy 5.2.0, was 70.0
    STRONG_BUY_MIN_RS_12M = 0.0
    STRONG_BUY_REQUIRE_MA50_ABOVE_MA200 = True
    REGIME_RISK_OFF_DISABLES_STRONG_BUY = True
    REGIME_RISK_OFF_MIN_MOMENTUM_PCT = 90.0
    REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY = 0.0  # policy 5.2.0, was 85.0

    @classmethod
    def from_runtime(cls):
        """Read the live production thresholds so the two cannot drift apart."""
        from screener.runtime import Config

        config = cls()
        for name in dir(cls):
            if name.startswith("_") or name == "from_runtime":
                continue
            if hasattr(Config, name):
                setattr(config, name, getattr(Config, name))
        return config


def _f(value):
    """Float or None -- gates must distinguish 'absent' from 'zero'."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(number) else number


def gate_failures(row, config=None, *, regime=None):
    """``(buy_failures, strong_failures)`` for one scored row.

    Mirrors the structure of the production method: STRONG BUY inherits every
    BUY failure, so a name failing a BUY gate is never STRONG BUY eligible.
    """
    config = config or GateConfig()
    buy = []
    strong = []

    price = _f(row.get("Close"))
    ma200 = _f(row.get("MA200"))
    ma200_slope = _f(row.get("MA200_Slope_Pct"))
    # MA50 is not carried directly; both ratios are against the same MA200, so
    # the level reconstructs exactly rather than being re-derived from prices.
    ma50_to_ma200 = _f(row.get("MA50_To_MA200_Pct"))
    ma50 = (
        ma200 * (1.0 + ma50_to_ma200 / 100.0)
        if ma200 is not None and ma50_to_ma200 is not None
        else None
    )

    # --- long-term trend, with a tolerance band --------------------------
    tolerance = float(config.BUY_MA200_TOLERANCE)
    if price is None or price <= 0 or ma200 is None or ma200 <= 0:
        buy.append("price/MA200 unavailable")
    elif price < tolerance * ma200:
        buy.append(f"price below MA200 tolerance band ({tolerance:.0%})")

    if ma200_slope is None:
        buy.append("MA200 slope unavailable")
    elif ma200_slope < float(config.BUY_MIN_MA200_SLOPE_PCT):
        buy.append("MA200 slope falling")

    streak = _f(row.get("Below_MA200_Streak"))
    rs_6m = _f(row.get("RS_Market_6M_Pct"))
    if (
        streak is not None
        and streak >= float(config.BREAKDOWN_CONFIRM_SESSIONS)
        and ma200_slope is not None
        and ma200_slope < 0
        and rs_6m is not None
        and rs_6m < 0
    ):
        buy.append("confirmed trend breakdown below MA200")

    # --- relative strength -----------------------------------------------
    rs_floor = float(config.BUY_MIN_RS_6M)
    if rs_6m is None:
        buy.append("market relative strength unavailable")
    elif rs_6m <= rs_floor:
        buy.append("6M market relative strength not positive")

    # --- factor percentile floors -----------------------------------------
    quality_pct = _f(row.get("Quality_Percentile"))
    if quality_pct is None:
        buy.append("quality percentile unavailable")
    elif quality_pct < float(config.BUY_MIN_QUALITY_PCT):
        buy.append("quality percentile below BUY floor")

    for block in ("Quality", "Growth", "Value", "Momentum", "Risk"):
        column = f"{block}_Coverage_Sufficient"
        value = row.get(column)
        if value is not None and not pd.isna(value) and not bool(value):
            buy.append(f"{block.lower()} factor coverage insufficient")

    # --- STRONG BUY --------------------------------------------------------
    if quality_pct is not None and quality_pct < float(
        config.STRONG_BUY_MIN_QUALITY_PCT
    ):
        strong.append("quality percentile below STRONG BUY floor")

    growth_pct = _f(row.get("Growth_Percentile"))
    if growth_pct is None:
        strong.append("growth percentile unavailable")
    elif growth_pct < float(config.STRONG_BUY_MIN_GROWTH_PCT):
        strong.append("growth percentile below STRONG BUY floor")

    momentum_pct = _f(row.get("Momentum_Percentile"))
    if momentum_pct is None:
        strong.append("momentum percentile unavailable")
    elif momentum_pct < float(config.STRONG_BUY_MIN_MOMENTUM_PCT):
        strong.append("momentum percentile below STRONG BUY floor")

    if bool(config.STRONG_BUY_REQUIRE_MA50_ABOVE_MA200):
        if ma50 is None or ma200 is None or price is None:
            strong.append("MA50/MA200 stack unavailable")
        elif not (price > ma50 > ma200):
            strong.append("price/MA50/MA200 not stacked bullishly")

    if ma200_slope is not None and ma200_slope <= 0:
        strong.append("MA200 not rising")

    rs_12m = _f(row.get("RS_Market_12M_Pct"))
    if rs_12m is None:
        strong.append("12M relative strength unavailable")
    elif rs_12m <= float(config.STRONG_BUY_MIN_RS_12M):
        strong.append("12M relative strength not positive")

    # --- market regime overlay ---------------------------------------------
    regime = str(regime or "").upper()
    if regime == RISK_OFF:
        if bool(config.REGIME_RISK_OFF_DISABLES_STRONG_BUY):
            strong.append("market regime risk-off: STRONG BUY disabled")
        floor = float(config.REGIME_RISK_OFF_MIN_MOMENTUM_PCT)
        if momentum_pct is None or momentum_pct < floor:
            buy.append("market regime risk-off: BUY requires top-decile momentum")
    elif regime == NEUTRAL:
        floor = float(config.REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY)
        if momentum_pct is None or momentum_pct < floor:
            strong.append(
                "market regime neutral: STRONG BUY requires exceptional momentum"
            )

    buy = list(dict.fromkeys(buy))
    # Production extends strong_failures with buy_failures: failing a BUY gate
    # necessarily fails STRONG BUY.
    strong = list(dict.fromkeys(strong + buy))
    return buy, strong


def apply_gates(frame, config=None, *, regime=None, score_column="Score"):
    """Attach eligibility columns and a gated score to a scored cross-section.

    Adds ``Eligibility_Class``, ``Gate_Severity``, ``Decision_Score_Ceiling``,
    ``Gate_Failures`` and ``Gated_Score``. ``Gated_Score`` is the *capped*
    score, which is deliberately flat across a whole class -- ranking on it
    alone would sort a constant. Callers must order by
    ``(Eligibility_Class, score_column desc)``, exactly as production does.
    """
    config = config or GateConfig()
    working = frame.copy()
    if len(working) == 0:
        for column in ("Eligibility_Class", "Gate_Severity",
                       "Decision_Score_Ceiling", "Gated_Score"):
            working[column] = pd.Series(dtype=float)
        working["Gate_Failures"] = pd.Series(dtype=object)
        return working

    classes, severities, ceilings, reasons = [], [], [], []
    for _, row in working.iterrows():
        buy, strong = gate_failures(row, config, regime=regime)
        if buy:
            ceiling, klass = CEILING_BUY_FAILED, CLASS_CAPPED
        elif strong:
            ceiling, klass = CEILING_STRONG_FAILED, CLASS_BUY_ONLY
        else:
            ceiling, klass = CEILING_CLEAR, CLASS_CLEAR
        classes.append(klass)
        severities.append(len(strong))
        ceilings.append(ceiling)
        reasons.append("; ".join(strong))

    working["Eligibility_Class"] = classes
    working["Gate_Severity"] = severities
    working["Decision_Score_Ceiling"] = ceilings
    working["Gate_Failures"] = reasons
    score = pd.to_numeric(working[score_column], errors="coerce")
    working["Gated_Score"] = np.minimum(score, working["Decision_Score_Ceiling"])
    return working


def gate_summary(frame):
    """Class counts for one rebalance, so gate behaviour is auditable per period."""
    if "Eligibility_Class" not in frame or len(frame) == 0:
        return {}
    counts = frame["Eligibility_Class"].value_counts().to_dict()
    return {
        "total": int(len(frame)),
        "clear": int(counts.get(CLASS_CLEAR, 0)),
        "buy_only": int(counts.get(CLASS_BUY_ONLY, 0)),
        "capped": int(counts.get(CLASS_CAPPED, 0)),
    }
