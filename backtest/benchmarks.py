"""Index benchmarks and CAGR comparison.

Answers the question a factor model must eventually face: *did this beat simply
owning the index?* `p0.md` §7A puts it first in the benchmark matrix, and a 16%
CAGR means nothing until you know the index did 18% with lower turnover.

**Two measurement traps this module is built to avoid.**

*Overlapping horizons.* A 6-month forward return sampled monthly reuses five of
its six months. Compounding those into a CAGR counts the same market move up to
six times and produces a number that cannot happen.

A calendar-month horizon is not safe either, which is subtler. "Entry plus one
month" and "the next rebalance's entry" land on different sessions whenever the
month-end and the horizon date disagree: on this archive that happened in 16 of
51 periods, overlapping by 1-2 days each (once by 11), counting ~2.4% of market
time twice and overstating every CAGR by roughly a point. CAGR is therefore
computed from ``Forward_Return_Chain_Pct``, whose exit *is* the next period's
entry, so the series chains by construction rather than by coincidence. The final
period has no successor and is dropped rather than closed on a different basis.

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
from bisect import bisect_right

import pandas as pd

logger = logging.getLogger(__name__)

# The historical endpoint truncates a response at roughly this many rows without
# erroring. Requests are sized to stay under it.
ENDPOINT_ROW_CAP = 70
DEFAULT_CHUNK_MONTHS = 3

# How far back level_on_or_before may reach for a missing session. It exists to
# bridge a one-session mismatch between the index and equity calendars, not to
# paper over a data gap: reaching across a hole returns a stale level and turns a
# wrong CAGR into a plausible-looking one.
MAX_LEVEL_STALENESS_DAYS = 7

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

    def fetch(self, indices, start, end, *, chunk_months=DEFAULT_CHUNK_MONTHS):
        """Fetch each index across the window and cache the combined frame.

        **The endpoint silently caps a response at about 70 rows** regardless of
        the window requested: a quarter returns 61 rows, six months returns 70,
        and a full year also returns 71. It does not error or paginate -- it just
        truncates, so a naive yearly loop yields roughly a third of the sessions
        and leaves months-long holes that look like ordinary missing data.

        Chunking by quarter keeps every request under the cap. A chunk that comes
        back at or above the cap is reported, because that is the signature of the
        truncation returning.
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
                                + pd.DateOffset(months=int(chunk_months))
                                - pd.Timedelta(days=1)
                            ).date(),
                        )
                        try:
                            records = nse.fetch_historical_index_data(
                                index_name, from_date=chunk_start, to_date=chunk_end
                            )
                            if len(records or []) >= ENDPOINT_ROW_CAP:
                                logger.warning(
                                    "Index %s %s..%s returned %d rows, at the "
                                    "endpoint cap -- the response was probably "
                                    "truncated. Reduce chunk_months.",
                                    index_name,
                                    chunk_start,
                                    chunk_end,
                                    len(records),
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

        # Merge with whatever is already cached rather than replacing it. The
        # endpoint returns intermittent 500s on individual quarters, so a run can
        # come back with holes; overwriting would discard sessions a previous run
        # fetched successfully and make the gaps permanent. Merging means simply
        # re-running the fetch heals them.
        existing = self.load()
        combined = pd.concat(
            [frame for frame in ([existing] if not existing.empty else []) + frames],
            ignore_index=True,
        ) if (frames or not existing.empty) else pd.DataFrame(columns=list(INDEX_COLUMNS))

        if not combined.empty:
            combined = (
                combined.drop_duplicates(subset=["Index", "Trade_Date"], keep="last")
                .sort_values(["Index", "Trade_Date"])
                .reset_index(drop=True)
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

    def level_on_or_before(self, index_name, day, *,
                           max_staleness_days=MAX_LEVEL_STALENESS_DAYS):
        """Index level on ``day``, or the most recent session shortly before it.

        The fallback is **bounded**. It exists because the index and equity
        calendars can differ by a session; it must not reach across a gap in the
        data, because a level from months earlier produces a wrong return that
        looks entirely reasonable. Beyond the bound this returns None and the
        period is dropped instead.
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
        if position < 0:
            return None
        nearest = sessions[position]
        if max_staleness_days is not None and (day - nearest).days > int(
            max_staleness_days
        ):
            logger.debug(
                "Index %s has no session within %s days of %s (nearest %s)",
                index_name,
                max_staleness_days,
                day,
                nearest,
            )
            return None
        return levels[nearest]

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


def strategy_period_table(fills, strategy, *, size=20, score_column="Score",
                          return_column="Forward_Return_Chain_Pct",
                          cost_rate_column=None):
    """Per-rebalance gross return, turnover, cost and net return for one strategy.

    **Costs are charged on what actually traded, not on everything held.** A
    position carried from one rebalance to the next incurs nothing; only the
    fraction replaced pays. Charging a full round trip to every holding every
    period -- which is what a naive per-position net return does -- makes a
    9%-turnover benchmark look as expensive as a 96%-turnover one, and destroys
    precisely the comparison `p0.md` §7C exists for: a model with twice the
    turnover may be worse after costs even when its gross ranking is better.

    With one-way turnover ``T`` and a round-trip rate ``c``, the period cost is
    ``T * c``. That is consistent at both ends: a full replacement (``T = 1``)
    pays one complete round trip, and an initial build from cash (``T = 0.5``)
    pays one buy leg.
    """
    rows = fills[fills["Strategy"] == strategy]
    if rows.empty or return_column not in rows:
        return pd.DataFrame(
            columns=["Signal_Date", "Gross_Pct", "Turnover", "Cost_Pct", "Net_Pct"]
        )

    from .metrics import turnover as one_way_turnover

    records = []
    previous: dict = {}
    for signal_date, period in sorted(
        rows.groupby("Signal_Date"), key=lambda item: item[0]
    ):
        usable = period.dropna(subset=[return_column, score_column])
        if usable.empty:
            continue
        if usable[score_column].nunique() <= 1:
            held = usable
        else:
            held = usable.sort_values(score_column, ascending=False).head(size)
        if held.empty:
            continue

        weight = 1.0 / len(held)
        current = {str(key): weight for key in held["Security_ID"]}
        traded = one_way_turnover(previous, current)
        previous = current

        gross = float(held[return_column].mean())
        cost_pct = 0.0
        if cost_rate_column and cost_rate_column in held:
            rate = pd.to_numeric(held[cost_rate_column], errors="coerce").mean()
            if pd.notna(rate):
                cost_pct = float(traded) * float(rate) * 100.0
        records.append(
            {
                "Signal_Date": str(signal_date),
                "Gross_Pct": gross,
                "Turnover": traded,
                "Cost_Pct": cost_pct,
                "Net_Pct": gross - cost_pct,
            }
        )
    return pd.DataFrame(records)


def strategy_period_returns(fills, strategy, *, size=20, score_column="Score",
                            return_column="Forward_Return_Chain_Pct"):
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
        if usable[score_column].nunique() <= 1:
            # A constant score cannot rank, so "top N" would be whichever rows
            # happen to sort first -- an arbitrary fixed subset masquerading as a
            # selection. The equal-weight benchmark's portfolio is the whole
            # eligible universe, which is what its score actually expresses.
            returns.append(float(usable[return_column].mean()))
        else:
            top = usable.sort_values(score_column, ascending=False).head(size)
            if top.empty:
                continue
            returns.append(float(top[return_column].mean()))
        dates.append(str(signal_date))
    return dates, returns


def universe_period_returns(fills, *, return_column="Forward_Return_Chain_Pct"):
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


def regime_provider(index_series, index_name="NIFTY 500"):
    """A ``signal_date -> regime`` callable over point-in-time index closes.

    Reuses `screener.benchmark.classify_regime` unchanged -- the production
    classifier is the thing under test, so reimplementing its thresholds here
    would test a lookalike. Returns ``None`` when the index has no history at
    the signal date, which leaves the regime overlay inert rather than guessing
    a regime the model could not have known.
    """
    from screener.benchmark import classify_regime

    frame = index_series.frame if hasattr(index_series, "frame") else index_series
    rows = frame[frame["Index"].astype(str) == str(index_name)].copy()
    if rows.empty:
        return lambda signal_date: None
    rows["_date"] = pd.to_datetime(rows["Trade_Date"]).dt.date
    rows = rows.sort_values("_date")
    dates = rows["_date"].tolist()
    closes = pd.to_numeric(rows["Close"], errors="coerce").tolist()
    cache = {}

    def provide(signal_date):
        day = _as_date(signal_date)
        if day in cache:
            return cache[day]
        # Strictly at-or-before the signal date: the classifier may not see a
        # close that had not printed when the signal was formed.
        cut = bisect_right(dates, day)
        regime = None
        if cut:
            regime = classify_regime(closes[:cut]).get("Market_Regime")
            if regime == "UNKNOWN":
                regime = None
        cache[day] = regime
        return regime

    return provide


def build_comparison(fills, index_series, calendar, *, strategies=None, size=20,
                     horizon_months=1, periods_per_year=12,
                     return_column="Forward_Return_Chain_Pct",
                     cost_rate_column="Cost_Rate_1M"):
    """CAGR of each strategy against each index over the same rebalance dates.

    Index returns are measured between the same entry and exit sessions the
    strategy actually traded, not between month-ends, so the comparison is not
    quietly measuring a different span of market time.
    """
    from .metrics import excess_metrics, portfolio_metrics

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
    # Each period ends where the next begins. Measuring the index over a calendar
    # month instead would compare it against a strategy series held to the next
    # rebalance, so the two sides would cover different spans of market time.
    exits = entries[1:] + [
        calendar.session_after_calendar_months(entries[-1], horizon_months)
    ]
    # The final period has no successor, so it cannot chain; drop it rather than
    # close it on a differently-measured horizon.
    entries, exits = entries[:-1], exits[:-1]

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
        table = strategy_period_table(
            fills,
            name,
            size=size,
            return_column=return_column,
            cost_rate_column=cost_rate_column,
        )
        gross = table["Gross_Pct"].tolist() if not table.empty else []
        # Net is charged on the fraction actually traded, so a low-turnover
        # strategy keeps most of its gross return instead of paying a full round
        # trip on every holding every period.
        net = (
            table["Net_Pct"].tolist()
            if not table.empty and table["Cost_Pct"].abs().sum() > 0
            else []
        )
        entry = {
            "mean_turnover": _round(
                float(table["Turnover"].mean()) if not table.empty else None
            ),
            "mean_cost_pct_per_period": _round(
                float(table["Cost_Pct"].mean()) if not table.empty else None
            ),
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
        # Periods actually compounded. The final rebalance has no successor to
        # chain into, so it is excluded; reporting the raw rebalance count would
        # overstate the elapsed time the CAGR is annualised over.
        "rebalances": len(entries),
        "rebalances_available": len(boundaries),
        "final_period_excluded": len(boundaries) - len(entries),
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
