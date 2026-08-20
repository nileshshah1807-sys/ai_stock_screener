"""Point-in-time price features for a historical cross-section.

Every feature is computed from adjusted closes **up to and including** the signal
date and never past it. That is the whole discipline of this module: the history
slice is truncated at the signal date before any arithmetic happens, so a feature
physically cannot see the future.

The feature definitions themselves are not reimplemented here.
`screener.market_data.calculate_trend_risk_features` is pure and side-effect free,
so it is called directly. That matters for the ablation runs: if this module
recomputed momentum with its own slightly different convention, a "momentum-only"
result would be measuring a strategy the production model does not actually run,
and the comparison in `p0.md` §7E would be meaningless.
"""

from __future__ import annotations

from datetime import date, datetime
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Sessions of history required before a security can be scored. Twelve-month
# momentum needs 252 closes plus the skipped month; below that the feature is NaN
# and the security would be ranked on absence rather than evidence.
MIN_HISTORY_SESSIONS = 200

# Window for the liquidity statistics that drive capacity and the impact model.
TURNOVER_WINDOW_SESSIONS = 60

PRICE_FEATURE_COLUMNS = (
    "Security_ID",
    "Symbol",
    "Signal_Date",
    "Close",
    "Price_History_Sessions",
    "Momentum_12_1_Pct",
    "Momentum_6_1_Pct",
    "Pct_Change_12M",
    # FactorModel derives RS_Market_6M_Pct from this, not from Momentum_6_1_Pct.
    # Without it the market-relative momentum term is NaN for every security.
    "Pct_Change_6M",
    "Volatility_Ann_Pct",
    "Downside_Deviation_Pct",
    "Max_Drawdown_1Y_Pct",
    "Gap_Risk_Pct",
    "Return_Concentration_1Y",
    "Trend_Quality_R2",
    "MA200",
    "Price_To_MA200_Pct",
    "MA50_To_MA200_Pct",
    # Read by the Model 5.0 BUY gates, not by the factor blocks. Both already
    # come out of calculate_trend_risk_features; they were simply not carried.
    "MA200_Slope_Pct",
    "Below_MA200_Streak",
    "Median_Turnover_INR",
    "Trading_Frequency",
    "RiskAdj_Momentum_12_1",
    "RiskAdj_Momentum_6_1",
)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


class HistoryPanel:
    """Per-security adjusted price history, sliceable by signal date.

    Built once for a whole run. Holding the full window in memory and slicing it
    per rebalance is far cheaper than re-reading day-files for every date, and the
    slice boundary is the single place look-ahead could enter -- so there is
    exactly one of them.
    """

    def __init__(self, frame, *, key_column="Security_ID"):
        self.key_column = key_column
        self._history: dict[str, dict] = {}
        if frame is None or len(frame) == 0:
            return

        working = frame.copy()
        working["_date"] = pd.to_datetime(working["Trade_Date"]).dt.date
        close_column = "Adj_Close" if "Adj_Close" in working.columns else "Close"
        open_column = "Adj_Open" if "Adj_Open" in working.columns else "Open"
        working = working.sort_values([key_column, "_date"])

        for key, group in working.groupby(key_column, sort=False):
            self._history[str(key)] = {
                "dates": group["_date"].tolist(),
                "close": pd.to_numeric(group[close_column], errors="coerce").tolist(),
                "open": pd.to_numeric(group[open_column], errors="coerce").tolist(),
                "turnover": pd.to_numeric(
                    group.get("Turnover_INR", pd.Series(index=group.index)),
                    errors="coerce",
                ).tolist(),
                "symbol": (
                    str(group["Symbol"].iloc[-1]) if "Symbol" in group else str(key)
                ),
            }

    def keys(self):
        return list(self._history)

    def slice_upto(self, key, signal_date):
        """History for ``key`` truncated at ``signal_date`` inclusive."""
        record = self._history.get(str(key))
        if record is None:
            return None
        signal_date = _as_date(signal_date)
        dates = record["dates"]
        # Rightmost index whose date is <= signal_date.
        low, high = 0, len(dates)
        while low < high:
            mid = (low + high) // 2
            if dates[mid] <= signal_date:
                low = mid + 1
            else:
                high = mid
        if low == 0:
            return None
        return {
            "dates": dates[:low],
            "close": record["close"][:low],
            "open": record["open"][:low],
            "turnover": record["turnover"][:low],
            "symbol": record["symbol"],
        }

    def __len__(self):
        return len(self._history)


def price_features(history, signal_date, *, min_history=MIN_HISTORY_SESSIONS):
    """Compute production-definition price features from a truncated history."""
    from screener.market_data import calculate_trend_risk_features

    closes = pd.Series(history["close"], dtype=float).dropna()
    if len(closes) < int(min_history):
        return None

    opens = pd.Series(history["open"], dtype=float)
    features = calculate_trend_risk_features(closes, opens=opens)
    # calculate_trend_risk_features publishes the 12-month plain return but not
    # the 6-month one. Computed here with the production helper and lookback so
    # the definition cannot drift from screener.market_data.
    from screener.market_data import TechnicalEnhancer

    features["Pct_Change_6M"] = TechnicalEnhancer.calculate_pct_return(closes, 126)

    turnover = pd.Series(history["turnover"], dtype=float).dropna()
    recent = turnover.iloc[-TURNOVER_WINDOW_SESSIONS:]
    median_turnover = float(recent.median()) if len(recent) else np.nan
    # Sessions actually traded out of the sessions available: a security that
    # trades three days a week cannot be built into at any size.
    frequency = (
        float(len(recent) / min(TURNOVER_WINDOW_SESSIONS, len(turnover)))
        if len(turnover)
        else np.nan
    )

    volatility = features.get("Volatility_Ann_Pct")
    # Guard against dividing by a near-zero volatility, which would manufacture an
    # enormous risk-adjusted momentum for a barely-traded name.
    safe_volatility = (
        float(volatility) if volatility and float(volatility) > 1.0 else np.nan
    )

    record = {
        "Signal_Date": _as_date(signal_date).isoformat(),
        "Symbol": history.get("symbol", ""),
        "Close": float(closes.iloc[-1]),
        "Median_Turnover_INR": median_turnover,
        "Trading_Frequency": frequency,
    }
    for column in (
        "Price_History_Sessions",
        "Momentum_12_1_Pct",
        "Momentum_6_1_Pct",
        "Pct_Change_12M",
        "Pct_Change_6M",
        "Volatility_Ann_Pct",
        "Downside_Deviation_Pct",
        "Max_Drawdown_1Y_Pct",
        "Gap_Risk_Pct",
        "Return_Concentration_1Y",
        "Trend_Quality_R2",
        "MA200",
        "Price_To_MA200_Pct",
        "MA50_To_MA200_Pct",
        "MA200_Slope_Pct",
        "Below_MA200_Streak",
    ):
        record[column] = features.get(column)

    for horizon in ("12_1", "6_1"):
        raw = features.get(f"Momentum_{horizon}_Pct")
        record[f"RiskAdj_Momentum_{horizon}"] = (
            float(raw) / safe_volatility
            if raw is not None
            and not pd.isna(raw)
            and not pd.isna(safe_volatility)
            else np.nan
        )
    return record


def build_cross_section(panel, signal_date, keys=None, *, min_history=MIN_HISTORY_SESSIONS):
    """Point-in-time feature frame for every eligible security on ``signal_date``."""
    signal_date = _as_date(signal_date)
    candidates = list(keys) if keys is not None else panel.keys()
    rows = []
    for key in candidates:
        history = panel.slice_upto(key, signal_date)
        if history is None:
            continue
        # A security whose last observed session is well before the signal date
        # was not trading then; scoring it would resurrect a delisted name.
        if history["dates"][-1] != signal_date:
            continue
        record = price_features(history, signal_date, min_history=min_history)
        if record is None:
            continue
        record["Security_ID"] = str(key)
        rows.append(record)
    if not rows:
        return pd.DataFrame(columns=list(PRICE_FEATURE_COLUMNS))
    frame = pd.DataFrame(rows)
    ordered = [column for column in PRICE_FEATURE_COLUMNS if column in frame.columns]
    remaining = [column for column in frame.columns if column not in ordered]
    return frame.loc[:, ordered + remaining]
