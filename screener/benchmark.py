"""Benchmark index history, market-relative strength, and regime detection.

The screener previously judged every stock's trend in isolation. A stock can sit
above a rising 50-day average while the whole market is breaking down, and the
resulting BUY carries far more risk than the same reading in an advancing
market. This module supplies the missing market context.

The regime is a *policy overlay*: it changes how much conviction a passing
candidate is allowed to carry, never the underlying factor scores. That keeps
the research ranking visible and auditable in every regime.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RISK_ON = "RISK_ON"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK_OFF"
UNKNOWN = "UNKNOWN"


def classify_regime(
    closes,
    *,
    ma_sessions=200,
    slope_sessions=20,
    neutral_band_pct=2.0,
):
    """Classify the broad-market regime from an index close series.

    RISK_ON  : index above its long average and that average rising.
    RISK_OFF : index below its long average and that average falling.
    NEUTRAL  : anything mixed, including the band around the average where a
               single session would otherwise flip the classification.
    """
    result = {
        "Market_Regime": UNKNOWN,
        "Market_Index_Close": np.nan,
        "Market_Index_MA": np.nan,
        "Market_Index_Distance_Pct": np.nan,
        "Market_Index_MA_Slope_Pct": np.nan,
        "Market_Regime_Reason": "insufficient index history",
    }
    values = pd.to_numeric(pd.Series(closes), errors="coerce").dropna()
    if len(values) < ma_sessions + slope_sessions:
        return result

    ma = values.rolling(ma_sessions).mean()
    ma_now = float(ma.iloc[-1])
    ma_then = float(ma.iloc[-(slope_sessions + 1)])
    close_now = float(values.iloc[-1])
    if not np.isfinite(ma_now) or not np.isfinite(ma_then) or ma_now <= 0 or ma_then <= 0:
        return result

    distance_pct = (close_now / ma_now - 1.0) * 100.0
    slope_pct = (ma_now / ma_then - 1.0) * 100.0
    result.update(
        {
            "Market_Index_Close": round(close_now, 2),
            "Market_Index_MA": round(ma_now, 2),
            "Market_Index_Distance_Pct": round(distance_pct, 3),
            "Market_Index_MA_Slope_Pct": round(slope_pct, 4),
        }
    )

    band = abs(float(neutral_band_pct))
    if distance_pct > band and slope_pct > 0:
        result["Market_Regime"] = RISK_ON
        result["Market_Regime_Reason"] = "index above a rising long average"
    elif distance_pct < -band and slope_pct < 0:
        result["Market_Regime"] = RISK_OFF
        result["Market_Regime_Reason"] = "index below a falling long average"
    else:
        result["Market_Regime"] = NEUTRAL
        result["Market_Regime_Reason"] = (
            "index within the neutral band or trend and level disagree"
        )
    return result


class BenchmarkProvider:
    """Download/cache the benchmark index and expose regime plus RS inputs."""

    def __init__(self, config, *, downloader=None):
        self.config = config
        # Injectable so tests never reach the network.
        self._downloader = downloader

    def _download(self, symbol, period):
        if self._downloader is not None:
            return self._downloader(symbol, period)
        import yfinance as yf

        return yf.download(
            symbol,
            period=period,
            progress=False,
            auto_adjust=False,
            threads=False,
        )

    @staticmethod
    def _close_series(frame):
        if frame is None or getattr(frame, "empty", True):
            return None
        candidate = frame
        if isinstance(frame.columns, pd.MultiIndex):
            for level in ("Adj Close", "Close"):
                if level in frame.columns.get_level_values(0):
                    candidate = frame[level]
                    break
            else:
                return None
            series = candidate.iloc[:, 0]
        else:
            column = "Adj Close" if "Adj Close" in frame.columns else "Close"
            if column not in frame.columns:
                return None
            series = frame[column]
        series = pd.to_numeric(series, errors="coerce").dropna()
        return series if not series.empty else None

    def load(self):
        """Return (symbol, close series) for the benchmark, or (None, None)."""
        period = getattr(self.config, "PRICE_HISTORY_PERIOD", "2y")
        candidates = [
            getattr(self.config, "BENCHMARK_INDEX_SYMBOL", "^CRSLDX"),
            getattr(self.config, "BENCHMARK_INDEX_FALLBACK", "^NSEI"),
        ]
        for symbol in [c for c in candidates if c]:
            try:
                series = self._close_series(self._download(symbol, period))
            except Exception as exc:
                logger.warning("Benchmark download failed for %s: %s", symbol, exc)
                continue
            if series is not None and len(series) >= 60:
                logger.info(
                    "Benchmark %s loaded (%d sessions)", symbol, len(series)
                )
                return symbol, series
            logger.warning("Benchmark %s returned insufficient history", symbol)
        return None, None

    def market_context(self):
        """Return regime fields plus benchmark returns used for relative strength."""
        symbol, series = self.load()
        context = {
            "Benchmark_Symbol": symbol or "unavailable",
            "Benchmark_Sessions": 0 if series is None else int(len(series)),
            "Benchmark_Return_6M_Pct": np.nan,
            "Benchmark_Return_12M_Pct": np.nan,
            "Benchmark_Return_12_1_Pct": np.nan,
            "Benchmark_Return_6_1_Pct": np.nan,
        }
        context.update(
            {
                "Market_Regime": UNKNOWN,
                "Market_Index_Close": np.nan,
                "Market_Index_MA": np.nan,
                "Market_Index_Distance_Pct": np.nan,
                "Market_Index_MA_Slope_Pct": np.nan,
                "Market_Regime_Reason": "benchmark unavailable",
            }
        )
        if series is None:
            return context

        if getattr(self.config, "MARKET_REGIME_ENABLED", True):
            context.update(
                classify_regime(
                    series,
                    ma_sessions=int(
                        getattr(self.config, "MARKET_REGIME_MA_SESSIONS", 200)
                    ),
                    slope_sessions=int(
                        getattr(self.config, "MARKET_REGIME_SLOPE_SESSIONS", 20)
                    ),
                    neutral_band_pct=float(
                        getattr(self.config, "MARKET_REGIME_NEUTRAL_BAND_PCT", 2.0)
                    ),
                )
            )
        else:
            context["Market_Regime_Reason"] = "regime overlay disabled"

        context["Benchmark_Return_6M_Pct"] = _lookback_return(series, 126)
        context["Benchmark_Return_12M_Pct"] = _lookback_return(series, 252)
        context["Benchmark_Return_12_1_Pct"] = _skip_month_return(series, 252)
        context["Benchmark_Return_6_1_Pct"] = _skip_month_return(series, 126)
        return context


def _lookback_return(series, sessions):
    values = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
    if len(values) <= sessions:
        return np.nan
    prior = float(values.iloc[-(sessions + 1)])
    latest = float(values.iloc[-1])
    if prior <= 0 or not np.isfinite(prior) or not np.isfinite(latest):
        return np.nan
    return round((latest / prior - 1.0) * 100.0, 4)


def _skip_month_return(series, sessions, skip=21):
    """Formation return that ends one month ago.

    Skipping the most recent month is the standard construction: it keeps
    short-horizon reversal and single-event noise out of a medium-term
    momentum signal.
    """
    values = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
    if len(values) <= sessions:
        return np.nan
    latest = float(values.iloc[-(skip + 1)])
    prior = float(values.iloc[-(sessions + 1)])
    if prior <= 0 or not np.isfinite(prior) or not np.isfinite(latest):
        return np.nan
    return round((latest / prior - 1.0) * 100.0, 4)
