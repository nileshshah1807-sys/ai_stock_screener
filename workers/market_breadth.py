"""Daily market breadth for the Market page.

Breadth is a cross-section taken every session: of the stocks that traded that
day, how many closed above their 20/50/100/200-day EMA, how many set a new
52-week closing high or low, how many were in Stage 2, how many carried an RS
rating above 75, and how many had beaten the benchmark over six months. The
page draws each of those as a time series.

Every input is a close, which is why no new data source is needed. Stage and
RS are replayed with the screener's own definitions -- ``classify_stages`` and
the ``RS_HORIZONS`` weighted return -- so the history cannot disagree with the
stage a stock shows on its own page today.

Choices worth stating:

* **Counted on days it traded.** A stock contributes to a session only if it
  printed a close that session. Nothing is forward-filled: a suspended stock is
  absent evidence, not a stock that held its last state.
* **Indicators run over the stock's own observations,** exactly as
  ``stage_features`` does, so a thin stock's 200-day EMA spans 200 of its
  trades rather than 200 calendar sessions padded with repeats.
* **A metric's denominator is only the stocks it is defined for.** A stock with
  60 sessions of history counts toward "above EMA 50" and not toward "above
  EMA 200". Folding it into the second as "not above" would score absence as a
  bearish reading.
* **RS rating is a percentile, so "above 75" is ~25% of the whole universe by
  construction.** It is published per sector and industry, where it is not
  flat. The universe-wide view reads the benchmark-relative count instead.
* **The universe is today's.** Classification comes from the latest snapshot,
  so the history covers the stocks screened now -- a stock delisted in 2021 is
  not in 2021's count. The page says so.

Each output row carries its own session list and a map of integer arrays
(numerator and denominator per metric), delta-encoded with the same scheme as
``workers.price_series``: counts move by a handful a day, so the deltas are one
or two characters.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, timedelta

import numpy as np
import pandas as pd

from screener.numeric import round_half_up
from screener.stage import RS_HORIZONS, STAGE_2, classify_stages

logger = logging.getLogger(__name__)

EMA_SPANS = (20, 50, 100, 200)
YEAR_SESSIONS = 252
BENCHMARK_SESSIONS = 126
RS_THRESHOLD = 75.0

# Smaller industries are noise as a percentage -- one stock is 25 points of a
# four-stock group -- so they are left out of the filter rather than shown as a
# jagged line that implies a signal.
MIN_INDUSTRY_MEMBERS = 5

# Undefined / false / true, as int8. A float matrix of the full history is
# ~60 MB per metric for the US universe; int8 is an eighth of that.
UNDEFINED = -1

SCOPE_MARKET = "market"
SCOPE_SECTOR = "sector"
SCOPE_INDUSTRY = "industry"
SCOPE_INDEX = "index"

# Published metric key -> the flag panel it counts. Keys are short because
# they are repeated in every published row.
FLAG_METRICS = {
    **{f"e{span}": f"ema{span}" for span in EMA_SPANS},
    "s2": "stage2",
    "rs": "rs75",
    "bb": "beat_benchmark",
}

EPOCH = date(1970, 1, 1)


def _delta_list(values) -> list[int]:
    numbers = [int(value) for value in values]
    if not numbers:
        return []
    out = [numbers[0]]
    out.extend(current - previous for previous, current in zip(numbers, numbers[1:]))
    return out


def undelta(values) -> list[int]:
    """Inverse of the delta encoding; exposed for round-trip tests."""
    out: list[int] = []
    for value in values:
        out.append(int(value) + (out[-1] if out else 0))
    return out


def encode_sessions(sessions) -> str:
    """Sessions as delta-encoded days since 1970-01-01."""
    return json.dumps(
        _delta_list((day - EPOCH).days for day in sessions), separators=(",", ":")
    )


def decode_sessions(text) -> list[date]:
    return [EPOCH + timedelta(days=days) for days in undelta(json.loads(text))]


def _as_series(points, sessions_index) -> pd.Series | None:
    """One symbol's observed closes as a Series on its own trading days."""
    days = [day for day in sorted(points) if day in sessions_index]
    closes = [points[day][0] if isinstance(points[day], tuple) else points[day] for day in days]
    series = pd.Series(closes, index=days, dtype=float)
    series = series[series > 0].dropna()
    return series if len(series) >= 2 else None


def _flags(condition, defined) -> np.ndarray:
    out = np.full(len(defined), UNDEFINED, dtype=np.int8)
    defined = np.asarray(defined, dtype=bool)
    out[defined] = np.asarray(condition, dtype=bool)[defined]
    return out


def symbol_signals(closes: pd.Series, benchmark_return: pd.Series | None = None):
    """Per-observation breadth flags for one stock.

    ``closes`` is the stock's observed series, oldest first. ``benchmark_return``
    maps a date to the benchmark's trailing six-month return. Returns a dict of
    int8 flag arrays (``UNDEFINED`` where a lookback is not full) plus the raw
    RS return as floats, all aligned to ``closes``.
    """
    values = closes.to_numpy(dtype=float)
    series = pd.Series(values)
    out: dict[str, np.ndarray] = {}

    for span in EMA_SPANS:
        ema = series.ewm(span=span, adjust=False, min_periods=span).mean()
        out[f"ema{span}"] = _flags(series > ema, ema.notna())

    prior = series.shift(1)
    prior_high = prior.rolling(YEAR_SESSIONS - 1, min_periods=YEAR_SESSIONS - 1).max()
    prior_low = prior.rolling(YEAR_SESSIONS - 1, min_periods=YEAR_SESSIONS - 1).min()
    out["high52"] = _flags(series > prior_high, prior_high.notna())
    out["low52"] = _flags(series < prior_low, prior_low.notna())

    labels = classify_stages(series)
    out["stage2"] = _flags(labels == STAGE_2, labels.notna())

    raw = pd.Series(0.0, index=series.index)
    for sessions, weight in RS_HORIZONS:
        raw = raw + weight * (series / series.shift(sessions) - 1.0)
    out["rs_raw"] = (raw * 100.0).to_numpy(dtype=float)

    if benchmark_return is not None:
        own = series / series.shift(BENCHMARK_SESSIONS) - 1.0
        bench = pd.Series(
            benchmark_return.reindex(pd.Index(closes.index)).to_numpy(dtype=float)
        )
        out["beat_benchmark"] = _flags(own > bench, own.notna() & bench.notna())
    return out


def benchmark_trailing_return(points) -> pd.Series:
    """Trailing six-month return of the benchmark, indexed by date."""
    closes = pd.Series(
        {day: value[0] if isinstance(value, tuple) else value for day, value in points.items()},
        dtype=float,
    ).sort_index()
    closes = closes[closes > 0]
    return (closes / closes.shift(BENCHMARK_SESSIONS) - 1.0).dropna()


def build_panels(observations, sessions, benchmark_return=None):
    """Stack every symbol's flags into (session x symbol) int8 panels.

    Returns ``(symbols, panels)`` where each panel has one column per symbol in
    ``symbols`` order. The RS panel is derived last: it is a cross-sectional
    percentile of the raw return, so it needs every symbol before any one of
    them can be rated.
    """
    position_of = {day: index for index, day in enumerate(sessions)}
    session_set = set(position_of)
    symbols = sorted(observations)
    names = [f"ema{span}" for span in EMA_SPANS] + ["high52", "low52", "stage2"]
    if benchmark_return is not None:
        names.append("beat_benchmark")

    shape = (len(sessions), len(symbols))
    panels = {name: np.full(shape, UNDEFINED, dtype=np.int8) for name in names}
    traded = np.zeros(shape, dtype=bool)
    rs_raw = np.full(shape, np.nan, dtype=np.float32)

    for column, symbol in enumerate(symbols):
        closes = _as_series(observations[symbol], session_set)
        if closes is None:
            continue
        rows = np.fromiter((position_of[day] for day in closes.index), dtype=np.int64)
        signals = symbol_signals(closes, benchmark_return)
        traded[rows, column] = True
        for name in names:
            panels[name][rows, column] = signals[name]
        rs_raw[rows, column] = signals["rs_raw"]

    rated = pd.DataFrame(rs_raw).rank(axis=1, pct=True, method="average").to_numpy()
    rating = 1.0 + 98.0 * rated
    rs = np.full(shape, UNDEFINED, dtype=np.int8)
    defined = ~np.isnan(rs_raw)
    rs[defined] = rating[defined] > RS_THRESHOLD
    panels["rs75"] = rs
    panels["traded"] = traded
    return symbols, panels


def aggregate(panels, columns) -> dict[str, np.ndarray]:
    """Numerator and denominator per metric for one group of columns."""
    columns = np.asarray(columns, dtype=np.int64)
    counts: dict[str, np.ndarray] = {
        "n": panels["traded"][:, columns].sum(axis=1),
    }
    for key, name in FLAG_METRICS.items():
        if name not in panels:
            continue
        block = panels[name][:, columns]
        counts[key] = (block == 1).sum(axis=1)
        counts[f"{key}d"] = (block != UNDEFINED).sum(axis=1)
    highs = panels["high52"][:, columns]
    lows = panels["low52"][:, columns]
    counts["hi"] = (highs == 1).sum(axis=1)
    counts["lo"] = (lows == 1).sum(axis=1)
    counts["hld"] = (highs != UNDEFINED).sum(axis=1)
    return counts


def _series_row(scope, name, parent, sessions, arrays, *, members=None, position=None):
    return {
        "scope": scope,
        "name": name,
        "parent": parent,
        "members": members,
        "position": position,
        "points": len(sessions),
        "first_session": sessions[0].isoformat(),
        "last_session": sessions[-1].isoformat(),
        "sessions": encode_sessions(sessions),
        "series": json.dumps(
            {key: _delta_list(values) for key, values in arrays.items()},
            separators=(",", ":"),
        ),
    }


def group_row(scope, name, parent, sessions, counts, members):
    """Encode one group, trimming the sessions before any member traded."""
    active = np.flatnonzero(counts["n"] > 0)
    if not len(active):
        return None
    start = int(active[0])
    trimmed = {key: values[start:] for key, values in counts.items()}
    return _series_row(scope, name, parent, list(sessions[start:]), trimmed, members=members)


def index_row(label, points, position):
    """An index level series, closes in hundredths so the values are integers."""
    days = sorted(points)
    closes = [
        round_half_up((points[day][0] if isinstance(points[day], tuple) else points[day]) * 100, 0)
        for day in days
    ]
    if len(days) < 2:
        return None
    return _series_row(SCOPE_INDEX, label, None, days, {"c": closes}, position=position)


def build_rows(
    observations,
    sessions,
    classification,
    *,
    benchmark_points=None,
    index_points=None,
    min_industry_members=MIN_INDUSTRY_MEMBERS,
):
    """Every row the Market page reads for one market.

    ``observations`` maps symbol -> {date: close or (close, volume)}.
    ``classification`` maps symbol -> (sector, industry) for the latest run; it
    is also the universe, so symbols outside it are ignored. ``index_points``
    is an ordered list of (label, {date: close}).
    """
    universe = {
        symbol: points for symbol, points in observations.items() if symbol in classification
    }
    missing = len(classification) - len(universe)
    if missing:
        logger.info("%d classified symbols have no price history", missing)
    if not universe:
        raise ValueError("No overlap between the price history and the latest snapshot")

    benchmark_return = (
        benchmark_trailing_return(benchmark_points) if benchmark_points else None
    )
    symbols, panels = build_panels(universe, sessions, benchmark_return)
    column_of = {symbol: index for index, symbol in enumerate(symbols)}

    rows = []
    market = group_row(
        SCOPE_MARKET, "", None, sessions, aggregate(panels, range(len(symbols))), len(symbols)
    )
    if market:
        rows.append(market)

    sectors: dict[str, list[int]] = {}
    industries: dict[str, list[int]] = {}
    industry_sectors: dict[str, Counter] = {}
    for symbol in symbols:
        sector, industry = classification[symbol]
        if sector:
            sectors.setdefault(sector, []).append(column_of[symbol])
        if industry:
            industries.setdefault(industry, []).append(column_of[symbol])
            if sector:
                industry_sectors.setdefault(industry, Counter())[sector] += 1

    for sector, columns in sorted(sectors.items()):
        row = group_row(SCOPE_SECTOR, sector, None, sessions, aggregate(panels, columns), len(columns))
        if row:
            rows.append(row)

    skipped = 0
    for industry, columns in sorted(industries.items()):
        if len(columns) < min_industry_members:
            skipped += 1
            continue
        # The parent groups the industry under a sector in the filter. The
        # vendor occasionally files one industry under two sectors; the
        # majority wins so the industry appears once.
        tally = industry_sectors.get(industry)
        sector = tally.most_common(1)[0][0] if tally else None
        row = group_row(
            SCOPE_INDUSTRY, industry, sector, sessions, aggregate(panels, columns), len(columns)
        )
        if row:
            rows.append(row)
    if skipped:
        logger.info(
            "Left out %d industries with fewer than %d members", skipped, min_industry_members
        )

    for position, (label, points) in enumerate(index_points or []):
        row = index_row(label, points, position) if points else None
        if row:
            rows.append(row)
        else:
            logger.warning("No history for index %s; its chart will be absent", label)

    return rows
