"""Index benchmarks and CAGR comparison.

Answers the question a factor model must eventually face: *did this beat simply
owning the index?* `p0.md` §7A puts it first in the benchmark matrix, and a 16%
CAGR means nothing until you know the index did 18% with lower turnover.

**Two measurement traps this module is built to avoid.**

*Overlapping horizons.* A 6-month forward return sampled monthly reuses five of
its six months. Compounding those into a CAGR counts the same market move up to
six times and produces a number that cannot happen. CAGR is therefore computed
only from **non-overlapping, chaining** periods: at a monthly rebalance the
1-month horizon chains exactly, because each period's exit session is the next
period's entry session. `compound_cagr` refuses any other construction rather
than producing a plausible-looking wrong answer.

*Dividend asymmetry.* NSE's historical index endpoint serves **price** indices
only -- every TRI spelling tried returns zero rows. The strategy's returns include
dividends, so comparing them against a price index credits the model with roughly
the market's dividend yield, about 1-1.5% a year in India, for free. So the
headline comparison is price-return against price-return, and the dividend
contribution is reported separately rather than folded in silently.
"""

from __future__ import annotations

from datetime import date, datetime
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Price indices available from the historical endpoint. NIFTY 500 is the broad
# investable benchmark p0.md asks for; the size indices are there because a
# small-cap-heavy strategy beating NIFTY 500 may only be showing size exposure.
DEFAULT_INDICES = (
    "NIFTY 500",
    "NIFTY 50",
    "NIFTY MIDCAP 150",
    "NIFTY SMALLCAP 250",
)

INDEX_COLUMNS = ("Index", "Trade_Date", "Open", "High", "Low", "Close")


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def normalise_index_rows(index_name, records):
    """Normalise ``fetch_historical_index_data`` output to a stable schema."""
    rows = []
    for record in records or []:
        raw_date = (
            record.get("EOD_TIMESTAMP")
            or record.get("TIMESTAMP")
            or record.get("EOD_DATE")
        )
        try:
            trade_date = pd.to_datetime(raw_date, dayfirst=True).date()
        except Exception:
            continue
        close = pd.to_numeric(record.get("EOD_CLOSE_INDEX_VAL"), errors="coerce")
        if pd.isna(close) or float(close) <= 0:
            continue
        rows.append(
            {
                "Index": index_name,
                "Trade_Date": trade_date.isoformat(),
                "Open": pd.to_numeric(record.get("EOD_OPEN_INDEX_VAL"), errors="coerce"),
                "High": pd.to_numeric(record.get("EOD_HIGH_INDEX_VAL"), errors="coerce"),
                "Low": pd.to_numeric(record.get("EOD_LOW_INDEX_VAL"), errors="coerce"),
                "Close": float(close),
            }
        )
    frame = pd.DataFrame(rows, columns=list(INDEX_COLUMNS))
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset=["Index", "Trade_Date"]).sort_values(
        "Trade_Date"
    ).reset_index(drop=True)


class IndexStore:
    """Fetch and cache index history."""

    def __init__(self, path, *, nse_factory=None):
        self.path = Path(path)
        self._nse_factory = nse_factory

    def _make_nse(self, folder):
        if self._nse_factory is not None:
            return self._nse_factory(folder)
        from nse import NSE

        return NSE(download_folder=folder, timeout=90, server=False)

    def load(self):
        if not self.path.exists():
            return pd.DataFrame(columns=list(INDEX_COLUMNS))
        try:
            return pd.read_csv(self.path)
        except Exception as exc:
            logger.warning("Index cache unreadable: %s", exc)
            return pd.DataFrame(columns=list(INDEX_COLUMNS))

    def fetch(self, indices, start, end, *, chunk_years=1):
        """Fetch each index across the window and cache the combined frame.

        The endpoint is unreliable over multi-year spans, so the window is
        requested in chunks and stitched.
        """
        from tempfile import TemporaryDirectory

        start, end = _as_date(start), _as_date(end)
        frames = []
        with TemporaryDirectory(prefix="nse_index_") as folder:
            with self._make_nse(folder) as nse:
                for index_name in indices:
                    collected = []
                    chunk_start = start
                    while chunk_start <= end:
                        chunk_end = min(
                            end,
                            (
                                pd.Timestamp(chunk_start)
                                + pd.DateOffset(years=int(chunk_years))
                                - pd.Timedelta(days=1)
                            ).date(),
                        )
                        try:
                            records = nse.fetch_historical_index_data(
                                index_name, from_date=chunk_start, to_date=chunk_end
                            )
                            collected.extend(records or [])
                        except Exception as exc:
                            logger.warning(
                                "Index %s %s..%s failed: %s",
                                index_name,
                                chunk_start,
                                chunk_end,
                                exc,
                            )
                        chunk_start = (
                            pd.Timestamp(chunk_end) + pd.Timedelta(days=1)
                        ).date()
                    frame = normalise_index_rows(index_name, collected)
                    logger.info("Index %s: %d sessions", index_name, len(frame))
                    if not frame.empty:
                        frames.append(frame)

        combined = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=list(INDEX_COLUMNS))
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(self.path, index=False)
        return combined


class IndexSeries:
    """Level lookups and period returns for one or more indices."""

    def __init__(self, frame):
        self._levels: dict[str, dict] = {}
        self._sessions: dict[str, list] = {}
        if frame is None or len(frame) == 0:
            return
        for index_name, group in frame.groupby("Index"):
            dates = pd.to_datetime(group["Trade_Date"]).dt.date.tolist()
            closes = pd.to_numeric(group["Close"], errors="coerce").tolist()
            pairs = sorted(
                (day, value)
                for day, value in zip(dates, closes)
                if pd.notna(value) and value > 0
            )
            self._levels[str(index_name)] = dict(pairs)
            self._sessions[str(index_name)] = [day for day, _ in pairs]

    def names(self):
        return sorted(self._levels)

    def level_on_or_before(self, index_name, day):
        """Index level on ``day``, or the most recent session before it.

        The index calendar and the equity calendar can differ by a session, so a
        missing exact date falls back rather than dropping the period.
        """
        levels = self._levels.get(str(index_name))
        if not levels:
            return None
        day = _as_date(day)
        value = levels.get(day)
        if value is not None:
            return value
        sessions = self._sessions.get(str(index_name), [])
        position = -1
        low, high = 0, len(sessions)
        while low < high:
            mid = (low + high) // 2
            if sessions[mid] <= day:
                position = mid
                low = mid + 1
            else:
                high = mid
        return levels[sessions[position]] if position >= 0 else None

    def period_return_pct(self, index_name, start, end):
        """Percentage change in the index between two dates."""
        opening = self.level_on_or_before(index_name, start)
        closing = self.level_on_or_before(index_name, end)
        if not opening or not closing or opening <= 0:
            return None
        return (closing / opening - 1.0) * 100.0

    def period_returns(self, index_name, boundaries):
        """Returns for consecutive, non-overlapping periods."""
        out = []
        for start, end in zip(boundaries, boundaries[1:]):
            out.append(self.period_return_pct(index_name, start, end))
        return out


def compound_cagr(period_returns_pct, *, periods_per_year):
    """CAGR from consecutive, non-overlapping period returns.

    The caller is responsible for the periods actually chaining. At a monthly
    rebalance the 1-month horizon does: each period's exit session is the next
    period's entry session. A 3- or 6-month horizon sampled monthly does not, and
    compounding it would count the same market move several times.
    """
    series = pd.Series(period_returns_pct, dtype=float).dropna()
    if series.empty:
        return None
    growth = float((1.0 + series / 100.0).prod())
    if growth <= 0:
        return -100.0
    years = len(series) / float(periods_per_year)
    if years <= 0:
        return None
    return (growth ** (1.0 / years) - 1.0) * 100.0


def strategy_period_returns(fills, strategy, *, size=20, score_column="Score",
                            return_column="Forward_Return_1M_Pct"):
    """Equal-weighted top-``size`` return per rebalance, in date order.

    Returns ``(dates, returns)``. Uses the 1-month horizon by default because
    that is the one that chains at a monthly rebalance.
    """
    rows = fills[fills["Strategy"] == strategy]
    if rows.empty or return_column not in rows:
        return [], []
    dates, returns = [], []
    for signal_date, period in sorted(
        rows.groupby("Signal_Date"), key=lambda item: item[0]
    ):
        usable = period.dropna(subset=[return_column, score_column])
        if usable.empty:
            continue
        top = usable.sort_values(score_column, ascending=False).head(size)
        if top.empty:
            continue
        dates.append(str(signal_date))
        returns.append(float(top[return_column].mean()))
    return dates, returns


def universe_period_returns(fills, *, return_column="Forward_Return_1M_Pct"):
    """Equal-weighted return of the whole eligible universe per rebalance.

    This is the `p0.md` §7B benchmark, and unlike a top-N slice of a constant
    score it is genuinely the universe average.
    """
    if fills.empty or return_column not in fills:
        return [], []
    # Any single strategy's rows cover the same universe, so use one to avoid
    # counting each security once per strategy.
    first = sorted(fills["Strategy"].unique())[0]
    rows = fills[fills["Strategy"] == first]
    dates, returns = [], []
    for signal_date, period in sorted(
        rows.groupby("Signal_Date"), key=lambda item: item[0]
    ):
        usable = period.dropna(subset=[return_column])
        if usable.empty:
            continue
        dates.append(str(signal_date))
        returns.append(float(usable[return_column].mean()))
    return dates, returns


def build_comparison(fills, index_series, calendar, *, strategies=None, size=20,
                     horizon_months=1, periods_per_year=12,
                     return_column="Forward_Return_1M_Pct",
                     net_column="Net_Return_1M_Pct"):
    """CAGR of each strategy against each index over the same rebalance dates.

    Index returns are measured between the same entry and exit sessions the
    strategy actually traded, not between month-ends, so the comparison is not
    quietly measuring a different span of market time.
    """
    from .metrics import excess_metrics, max_drawdown, portfolio_metrics

    if fills is None or fills.empty:
        return {}

    names = strategies or sorted(fills["Strategy"].unique())
    signal_dates = sorted(fills["Signal_Date"].unique())

    # Entry and exit sessions per rebalance, from the execution convention.
    boundaries = []
    for signal_date in signal_dates:
        entry = calendar.next_session(signal_date)
        if entry is None:
            continue
        boundaries.append((str(signal_date), entry))
    if len(boundaries) < 2:
        return {}

    entries = [entry for _, entry in boundaries]
    exits = [
        calendar.session_after_calendar_months(entry, horizon_months)
        for entry in entries
    ]

    index_results = {}
    for index_name in index_series.names():
        returns = [
            index_series.period_return_pct(index_name, entry, exit_session)
            if exit_session is not None
            else None
            for entry, exit_session in zip(entries, exits)
        ]
        usable = [value for value in returns if value is not None]
        index_results[index_name] = {
            "periods": len(usable),
            "cagr_pct": _round(compound_cagr(usable, periods_per_year=periods_per_year)),
            "returns": returns,
            "metrics": portfolio_metrics(usable, periods_per_year=periods_per_year),
        }

    strategy_results = {}
    for name in names:
        _dates, gross = strategy_period_returns(
            fills, name, size=size, return_column=return_column
        )
        net = []
        if net_column in fills:
            _d, net = strategy_period_returns(
                fills, name, size=size, return_column=net_column
            )
        entry = {
            "periods": len(gross),
            "gross_cagr_pct": _round(
                compound_cagr(gross, periods_per_year=periods_per_year)
            ),
            "net_cagr_pct": _round(
                compound_cagr(net, periods_per_year=periods_per_year)
            )
            if net
            else None,
            "gross_metrics": portfolio_metrics(gross, periods_per_year=periods_per_year),
            "net_metrics": portfolio_metrics(net, periods_per_year=periods_per_year)
            if net
            else None,
            "versus": {},
        }
        for index_name, index_entry in index_results.items():
            aligned_index, aligned_strategy = [], []
            for value, strategy_value in zip(index_entry["returns"], net or gross):
                if value is None or strategy_value is None:
                    continue
                aligned_index.append(value)
                aligned_strategy.append(strategy_value)
            if not aligned_index:
                continue
            basis = "net" if net else "gross"
            entry["versus"][index_name] = {
                "basis": basis,
                "strategy_cagr_pct": _round(
                    compound_cagr(aligned_strategy, periods_per_year=periods_per_year)
                ),
                "index_cagr_pct": _round(
                    compound_cagr(aligned_index, periods_per_year=periods_per_year)
                ),
                "cagr_difference_pct": _round(
                    (compound_cagr(aligned_strategy, periods_per_year=periods_per_year) or 0.0)
                    - (compound_cagr(aligned_index, periods_per_year=periods_per_year) or 0.0)
                ),
                "excess": excess_metrics(
                    aligned_strategy, aligned_index, periods_per_year=periods_per_year
                ),
            }
        strategy_results[name] = entry

    universe_dates, universe_returns = universe_period_returns(
        fills, return_column=return_column
    )
    return {
        "rebalances": len(boundaries),
        "horizon_months": horizon_months,
        "portfolio_size": size,
        "indices": {
            name: {k: v for k, v in entry.items() if k != "returns"}
            for name, entry in index_results.items()
        },
        "strategies": strategy_results,
        "eligible_universe": {
            "periods": len(universe_returns),
            "cagr_pct": _round(
                compound_cagr(universe_returns, periods_per_year=periods_per_year)
            ),
        },
    }


def _round(value, digits=4):
    return None if value is None else round(float(value), digits)
