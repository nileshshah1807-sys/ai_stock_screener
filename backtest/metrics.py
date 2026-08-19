"""Evaluation metrics for the walk-forward test.

Deliberately split into cross-sectional evidence (does the ranking order future
returns?) and portfolio evidence (does acting on it make money after costs?).
They answer different questions and a model can pass one while failing the other:
a ranking with real predictive power can still be unusable if capturing it
requires more turnover than the edge supports.

`p0.md` is explicit that an average IC alone is not evidence. So `ic_summary`
reports the median, the share of positive periods, the dispersion and the worst
period alongside the mean -- a mean IC carried by two extraordinary months is a
different claim from a mean IC earned consistently, and only the second is worth
trading.

Spearman correlation is computed as Pearson correlation on average ranks, which is
its definition. ``Series.corr(method="spearman")`` would import scipy, and scipy is
not a dependency of this project -- adding one for a rank correlation that is four
lines of pandas would be a poor trade.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Trading sessions per year, for annualising. NSE runs ~250; 252 is the
# conventional figure and the difference is immaterial next to the noise here.
SESSIONS_PER_YEAR = 252
MONTHS_PER_YEAR = 12


def spearman(left, right):
    """Spearman rank correlation, as Pearson correlation on average ranks.

    ``method="average"`` on ties is what makes this equal the textbook Spearman
    coefficient rather than an ordering-dependent approximation.
    """
    left = pd.Series(left, dtype=float).reset_index(drop=True)
    right = pd.Series(right, dtype=float).reset_index(drop=True)
    value = left.rank(method="average").corr(right.rank(method="average"))
    return None if pd.isna(value) else float(value)


def _clean_pair(scores, returns):
    """Align two series and drop rows where either side is missing."""
    frame = pd.DataFrame(
        {
            "score": pd.to_numeric(pd.Series(scores).reset_index(drop=True), errors="coerce"),
            "ret": pd.to_numeric(pd.Series(returns).reset_index(drop=True), errors="coerce"),
        }
    )
    return frame.dropna()


def rank_ic(scores, returns, *, min_observations=20):
    """Spearman rank correlation between a score and a forward return.

    Returns None rather than a number when the cross-section is too thin to mean
    anything. A rank IC computed on eight names is noise wearing a statistic's
    clothing, and letting it into an average corrupts the average.
    """
    pair = _clean_pair(scores, returns)
    if len(pair) < int(min_observations):
        return None
    if pair["score"].nunique() < 2 or pair["ret"].nunique() < 2:
        return None
    return spearman(pair["score"], pair["ret"])


def ic_summary(values):
    """Distributional summary of per-period ICs.

    ``t_stat`` treats the per-period ICs as independent draws, which overlapping
    horizons violate -- a 6-month horizon sampled monthly reuses most of its
    window. It is reported as a rough guide, not a significance test.
    """
    series = pd.Series([v for v in values if v is not None], dtype=float).dropna()
    if series.empty:
        return {
            "periods": 0,
            "mean": None,
            "median": None,
            "std": None,
            "positive_share": None,
            "worst": None,
            "best": None,
            "t_stat": None,
        }
    std = float(series.std(ddof=1)) if len(series) > 1 else 0.0
    return {
        "periods": int(len(series)),
        "mean": round(float(series.mean()), 4),
        "median": round(float(series.median()), 4),
        "std": round(std, 4) if len(series) > 1 else None,
        "positive_share": round(float((series > 0).mean()), 4),
        "worst": round(float(series.min()), 4),
        "best": round(float(series.max()), 4),
        "t_stat": (
            round(float(series.mean() / (std / np.sqrt(len(series)))), 3)
            if std > 0 and len(series) > 1
            else None
        ),
    }


def bucket_returns(scores, returns, buckets=10, *, min_observations=None):
    """Mean forward return per score bucket, bucket 1 being the highest score.

    Uses rank-based bucketing rather than equal score intervals so a skewed score
    distribution still divides the population evenly.
    """
    pair = _clean_pair(scores, returns)
    minimum = buckets * 2 if min_observations is None else int(min_observations)
    if len(pair) < minimum:
        return None
    # Descending rank: the best score lands in bucket 1.
    ranks = pair["score"].rank(ascending=False, method="first")
    try:
        labels = pd.qcut(ranks, buckets, labels=False, duplicates="drop") + 1
    except ValueError:
        return None
    grouped = pair.assign(bucket=labels).groupby("bucket")["ret"]
    return pd.DataFrame(
        {
            "count": grouped.count(),
            "mean_return_pct": grouped.mean().round(4),
            "median_return_pct": grouped.median().round(4),
            "hit_rate_pct": (grouped.apply(lambda s: (s > 0).mean() * 100)).round(2),
        }
    ).reset_index()


def bucket_spread(bucket_frame):
    """Top-bucket minus bottom-bucket mean return, or None."""
    if bucket_frame is None or bucket_frame.empty:
        return None
    ordered = bucket_frame.sort_values("bucket")
    return round(
        float(
            ordered["mean_return_pct"].iloc[0] - ordered["mean_return_pct"].iloc[-1]
        ),
        4,
    )


def monotonicity(bucket_frame):
    """Spearman correlation between bucket order and mean return.

    ``p0.md`` asks whether buckets decline "reasonably monotonically" rather than
    perfectly. This gives that a number: +1 is a perfect ladder from best to
    worst, 0 is no ordering, -1 is fully inverted.
    """
    if bucket_frame is None or len(bucket_frame) < 3:
        return None
    ordered = bucket_frame.sort_values("bucket")
    # Negate so a correctly ordered ladder (bucket 1 highest) scores +1.
    value = spearman(ordered["bucket"], ordered["mean_return_pct"])
    return None if value is None else round(-value, 4)


def turnover(previous_weights, new_weights):
    """One-way turnover between two weight maps.

    ``0.5 * sum(|new - old|)``, per `p0.md` §5. A full replacement of a fully
    invested portfolio is 1.0.
    """
    previous_weights = previous_weights or {}
    new_weights = new_weights or {}
    keys = set(previous_weights) | set(new_weights)
    if not keys:
        return 0.0
    total = sum(
        abs(float(new_weights.get(key, 0.0)) - float(previous_weights.get(key, 0.0)))
        for key in keys
    )
    return round(0.5 * total, 6)


def max_drawdown(equity_curve):
    """Worst peak-to-trough fraction of an equity curve, as a negative number."""
    series = pd.Series(equity_curve, dtype=float).dropna()
    if series.empty:
        return None
    running_peak = series.cummax()
    drawdown = series / running_peak - 1.0
    return round(float(drawdown.min()), 6)


def equity_curve(period_returns_pct):
    """Compound a sequence of period returns into an equity curve starting at 1."""
    series = pd.Series(period_returns_pct, dtype=float).dropna() / 100.0
    if series.empty:
        return pd.Series(dtype=float)
    return (1.0 + series).cumprod()


def portfolio_metrics(period_returns_pct, *, periods_per_year=MONTHS_PER_YEAR):
    """Summarise a sequence of realised period returns.

    ``periods_per_year`` describes the *rebalance* cadence, not the holding
    horizon. Compounding monthly rebalances at 12 while the underlying return is a
    6-month overlapping horizon would double-count, so overlapping horizons must
    be evaluated with `ic_summary` and bucket spreads rather than through this
    function.
    """
    series = pd.Series(period_returns_pct, dtype=float).dropna()
    if series.empty:
        return {
            "periods": 0,
            "cagr_pct": None,
            "mean_period_return_pct": None,
            "volatility_ann_pct": None,
            "sharpe": None,
            "max_drawdown_pct": None,
            "hit_rate_pct": None,
        }
    curve = equity_curve(series)
    total_growth = float(curve.iloc[-1])
    years = len(series) / float(periods_per_year)
    cagr = (total_growth ** (1.0 / years) - 1.0) * 100.0 if years > 0 and total_growth > 0 else None
    period_std = float(series.std(ddof=1)) if len(series) > 1 else None
    volatility = (
        period_std * np.sqrt(periods_per_year) if period_std is not None else None
    )
    mean_return = float(series.mean())
    sharpe = (
        (mean_return * periods_per_year) / volatility
        if volatility not in (None, 0.0)
        else None
    )
    return {
        "periods": int(len(series)),
        "cagr_pct": round(cagr, 4) if cagr is not None else None,
        "mean_period_return_pct": round(mean_return, 4),
        "volatility_ann_pct": round(volatility, 4) if volatility is not None else None,
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "max_drawdown_pct": (
            round(max_drawdown(curve) * 100.0, 4)
            if max_drawdown(curve) is not None
            else None
        ),
        "hit_rate_pct": round(float((series > 0).mean() * 100.0), 2),
    }


def excess_metrics(strategy_returns_pct, benchmark_returns_pct, *, periods_per_year=MONTHS_PER_YEAR):
    """Strategy performance relative to a benchmark, period by period."""
    frame = pd.DataFrame(
        {
            "strategy": pd.Series(strategy_returns_pct, dtype=float).reset_index(drop=True),
            "benchmark": pd.Series(benchmark_returns_pct, dtype=float).reset_index(drop=True),
        }
    ).dropna()
    if frame.empty:
        return {
            "periods": 0,
            "mean_excess_pct": None,
            "tracking_error_ann_pct": None,
            "information_ratio": None,
            "periods_beaten_share": None,
        }
    excess = frame["strategy"] - frame["benchmark"]
    tracking = (
        float(excess.std(ddof=1)) * np.sqrt(periods_per_year)
        if len(excess) > 1
        else None
    )
    mean_excess = float(excess.mean())
    return {
        "periods": int(len(excess)),
        "mean_excess_pct": round(mean_excess, 4),
        "tracking_error_ann_pct": round(tracking, 4) if tracking else None,
        "information_ratio": (
            round((mean_excess * periods_per_year) / tracking, 4)
            if tracking
            else None
        ),
        "periods_beaten_share": round(float((excess > 0).mean()), 4),
    }
