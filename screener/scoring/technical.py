"""Technical component scoring.

Each component (RSI, moving averages, MACD, volume, momentum, ...) is scored
continuously and then confidence-shrunk by how much evidence the row actually
carries, so a sparse technical row is neutral rather than implicitly penalised.
"""

import numpy as np

from ..numeric import safe_float
from .constants import TECH_COMPONENT_MAX

MAX_TECH_SCORE = sum(TECH_COMPONENT_MAX.values())

# Scales that turn raw demand proxies into 0..1 weights.
DEMAND_CMF_SCALE = 0.10
DEMAND_RETURN_SCALE_PCT = 10.0
DEMAND_VOLUME_SCALE = 1.50


def _interpolate(value, knots):
    xs, ys = zip(*knots)
    return float(np.interp(float(value), xs, ys))

def technical_score_details(row):
    """Return continuous component scores plus explicit evidence coverage."""
    s = safe_float
    scores = dict.fromkeys(TECH_COMPONENT_MAX)
    # Every price-relative indicator below is derived from adjusted OHLC.
    # Current_Price intentionally remains raw for valuation/display only.
    price = s(row.get("Technical_Price"))

    rsi = s(row.get("RSI_14"))
    if rsi is not None:
        scores["RSI"] = _interpolate(
            rsi,
            [(0, 3), (20, 4), (30, 8), (40, 11), (50, 12),
             (60, 11), (70, 8), (80, 5), (100, 3)],
        )

    ma20 = s(row.get("MA20"))
    if price is not None and price > 0 and ma20 is not None and ma20 > 0:
        distance = (price / ma20 - 1.0) * 100.0
        scores["MA20"] = _interpolate(
            distance,
            [(-30, 3), (-10, 5), (-5, 7), (0, 10), (5, 13),
             (7.5, 15), (15, 11), (30, 8)],
        )

    ma50 = s(row.get("MA50"))
    slope = s(row.get("MA50_Slope_Pct"))
    if (
        price is not None and price > 0
        and ma50 is not None and ma50 > 0
        and slope is not None
    ):
        distance = (price / ma50 - 1.0) * 100.0
        ma50_points = _interpolate(
            distance,
            [(-30, 2), (-15, 4), (-5, 7), (0, 10), (5, 13),
             (8, 15), (15, 11), (35, 7)],
        )
        adjustment = _interpolate(
            slope,
            [(-10, -6), (-3, -6), (0, 0), (3, 2), (10, 2)],
        )
        ma50_points += adjustment
        scores["MA50"] = float(np.clip(ma50_points, 1.0, 15.0))

    macd = s(row.get("MACD"))
    signal = s(row.get("MACD_Signal"))
    if (
        price is not None and price > 0
        and macd is not None and signal is not None
    ):
        spread_pct = (macd - signal) / price * 100.0
        scores["MACD"] = _interpolate(
            spread_pct,
            [(-3, 3), (-1, 5), (0, 8), (0.5, 12), (2, 15), (5, 15)],
        )

    vol_ratio = s(row.get("Vol_Ratio"))
    cmf_21 = s(row.get("CMF_21"))
    return_20d = s(row.get("Price_Return_20D_Pct"))
    demand_cmf_signal = None
    demand_return_signal = None
    demand_signal = None
    demand_volume_weight = None
    demand_inputs_complete = bool(
        cmf_21 is not None
        and return_20d is not None
        and vol_ratio is not None
        and vol_ratio >= 0
    )
    if demand_inputs_complete:
        # CMF and price return supply direction; relative volume controls
        # confidence in that direction. tanh keeps the result bounded and
        # continuous, eliminating category jumps at exactly zero.
        demand_cmf_signal = float(np.tanh(cmf_21 / DEMAND_CMF_SCALE))
        demand_return_signal = float(
            np.tanh(return_20d / DEMAND_RETURN_SCALE_PCT)
        )
        demand_signal = (demand_cmf_signal + demand_return_signal) / 2.0
        demand_volume_weight = float(
            np.tanh(vol_ratio / DEMAND_VOLUME_SCALE)
        )
        scores["VOL"] = float(np.clip(
            7.5 + 7.5 * demand_signal * demand_volume_weight,
            0.0,
            TECH_COMPONENT_MAX["VOL"],
        ))

    pct_1m = s(row.get("Pct_Change_1M"))
    if pct_1m is not None:
        # Monotonically non-decreasing and saturating. The previous curve
        # peaked at +5..15% then fell away, so a stock up 48% scored 7.2
        # while a flat stock scored 8 and one down 5% scored 6 -- a strong
        # advance was ranked below a decline, which no momentum or reversal
        # result supports.
        #
        # Extension risk is still priced, but once: RSI, StochRSI, Bollinger
        # position and ATR already spend 40 of the 132 technical points
        # penalising an overbought, stretched, volatile chart. Discounting
        # it a fifth time here made the technical score structurally unable
        # to rank a breakout above neutral.
        #
        # Saturating rather than rising without limit keeps a parabolic move
        # from dominating the component, which is the defensible half of the
        # short-term reversal evidence at this one-month horizon.
        scores["MOM"] = _interpolate(
            pct_1m,
            [(-30, 1), (-10, 2), (-5, 6), (0, 8), (5, 14),
             (15, 18), (25, 20), (40, 20), (80, 20)],
        )

    bb_pos = s(row.get("BB_Position"))
    if bb_pos is not None:
        scores["BB"] = _interpolate(
            bb_pos,
            [(-0.5, 5), (0, 7), (0.15, 8), (0.3, 6), (0.7, 6),
             (0.9, 5), (1.0, 3), (1.5, 2)],
        )

    adx = s(row.get("ADX_14"))
    plus_di = s(row.get("ADX_Plus_DI"))
    minus_di = s(row.get("ADX_Minus_DI"))
    direction = None
    if adx is not None and plus_di is not None and minus_di is not None:
        denominator = abs(plus_di) + abs(minus_di)
        direction = (plus_di - minus_di) / denominator if denominator else 0.0
        strength = float(np.clip((adx - 15.0) / 25.0, 0.0, 1.0))
        scores["ADX"] = float(np.clip(3.0 + 9.0 * strength * direction, 1.0, 12.0))

    stoch_rsi = s(row.get("StochRSI_14"))
    if stoch_rsi is not None:
        if stoch_rsi <= 0 or stoch_rsi >= 100 or stoch_rsi < 20 and direction is not None and direction < 0:
            scores["STOCH"] = 6.0
        else:
            scores["STOCH"] = _interpolate(
                stoch_rsi,
                [(0, 10), (15, 12), (30, 8), (50, 8), (70, 8),
                 (80, 6), (100, 3)],
            )

    atr = s(row.get("ATR_14"))
    if price is not None and price > 0 and atr is not None and atr >= 0:
        atr_pct = atr / price * 100.0
        scores["ATR"] = _interpolate(
            atr_pct,
            [(0, 8), (0.5, 8), (1, 7), (2, 5), (4, 2), (6, 1), (10, 0)],
        )

    observed = [name for name, value in scores.items() if value is not None]
    missing = [name for name, value in scores.items() if value is None]
    observed_max = sum(TECH_COMPONENT_MAX[name] for name in observed)
    raw = sum(float(scores[name]) for name in observed)
    coverage = observed_max / MAX_TECH_SCORE if MAX_TECH_SCORE else 0.0
    observed_score = raw / observed_max * 100.0 if observed_max else 50.0
    adjusted_score = 50.0 + coverage * (observed_score - 50.0)
    adjusted_score = float(np.clip(adjusted_score, 0.0, 100.0))
    return {
        "components": scores,
        "raw": raw,
        "observed_max": observed_max,
        "coverage": coverage,
        "observed_score": observed_score,
        "adjusted_score": adjusted_score,
        "adjusted_raw": adjusted_score / 100.0 * MAX_TECH_SCORE,
        "missing_components": missing,
        "demand_proxy_input_complete": demand_inputs_complete,
        "demand_proxy_cmf_signal": demand_cmf_signal,
        "demand_proxy_return_signal": demand_return_signal,
        "demand_proxy_signal": demand_signal,
        "demand_proxy_volume_weight": demand_volume_weight,
    }

def score_technical(row):
    """Backward-compatible raw score on the declared MAX_TECH_SCORE scale."""
    return technical_score_details(row)["adjusted_raw"]
