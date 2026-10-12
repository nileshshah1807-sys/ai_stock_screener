"""Restate a vendor's price history across changes of basis it missed.

A share's price history is only comparable with itself on one basis. A split, a
demerger or a rights issue moves the basis, and the vendor's adjusted close is
supposed to move every earlier price with it. Yahoo does not, reliably, for
NSE (measured across the whole market on 12 Oct 2026):

* A demerger or a rights issue is not adjusted at all. The parent's ex-date
  price cut stays in the adjusted close as a loss its holders never took.
* Some splits and bonuses are back-adjusted only part of the way, leaving a
  cliff of exactly the ratio at the point where the adjustment stopped.
* An occasional bar is a bad print, a hundred times its neighbours.

Left alone, every return, moving average and stage label on the affected
symbol is computed across a cliff that never happened, for as long as it stays
inside the history window.

Two things recognise a change of basis, and the frame's own bars size it:

* The exchange's action feed names the symbols with a demerger or a rights
  issue and their ex-dates. The factor is ``previous close / ex-date open``,
  whatever its size.
* Where the market caps its opening auction (``MarketProfile.max_open_gap``),
  an open beyond the cap was not traded to. The same factor applies, in either
  direction, with no feed needed. A market with an uncapped open has no such
  rule, because there a gap of any size can be real.

Every adjusted close before the change is divided by the factor. Only ``Adj
Close`` moves: raw closes still price turnover, and the high and low follow the
adjusted close as they already do.

The gap is measured on the vendor's *adjusted* basis -- each bar's open and
close scaled by its own ``Adj Close / Close``. Where the vendor did bridge a
change in its adjusted close, there is then no gap left to find, and nothing is
restated twice.

A bar that gaps beyond the cap and straight back is not a change of basis but a
bad print, and is dropped.

Guards, each chosen so a miss leaves the history exactly as the vendor served it:

* A feed that cannot be fetched is reported once; the opening-cap rule still
  catches every change large enough to breach it.
* An ex-date bar that opens at or above the previous close is not a ratio.
* A gap is read only between bars close enough in time to be one overnight
  apart in any useful sense, and only above the price where tick size alone
  could produce it.
* The bar has to be in the frame. A security suspended past its ex-date is
  restated on the run that first sees it trade again.
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# A security can stay suspended for a few sessions past its ex-date; its first
# bar after that is still the price discovery. Calendar days.
MAX_DAYS_TO_FIRST_BAR = 21
# Past this the two bars either side of a gap are not one overnight apart, and
# the opening cap says nothing about them. Calendar days.
MAX_DAYS_BETWEEN_BARS = 45

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NOT_LOADED = "not_loaded"

CHANGE_ACTION = "action"
CHANGE_OPEN_GAP = "open_gap"
CHANGE_BAD_PRINT = "bad_print"


def _load_nse_actions(start, end):
    # Imported here so a market without a ledger never loads the NSE client.
    from tempfile import TemporaryDirectory

    from nse import NSE

    from backtest.corporate_actions import (
        ACTION_DEMERGER,
        ACTION_RIGHTS,
        normalise_actions,
    )

    with TemporaryDirectory(prefix="nse_actions_") as folder, NSE(
        download_folder=folder, timeout=90, server=False
    ) as nse:
        records = nse.actions(
            segment="equities",
            from_date=datetime.combine(start, datetime.min.time()),
            to_date=datetime.combine(end, datetime.max.time()),
        )
    frame = normalise_actions(records)
    if frame.empty:
        # Two years of NSE actions is thousands of rows; none at all is a
        # failed fetch, not a quiet period.
        raise ValueError("corporate-action feed returned no actions")
    unadjusted = frame[frame["Action_Type"].isin({ACTION_DEMERGER, ACTION_RIGHTS})]
    return [
        (str(record["Symbol"]), pd.Timestamp(record["Ex_Date"]).date())
        for record in unadjusted.to_dict("records")
    ]


_LOADERS = {"nse_actions": _load_nse_actions}


class ActionLedger:
    """Ex-dates of actions the vendor does not adjust for, per symbol.

    Fetched once, on the first lookup. The loader returns ``(symbol, ex_date)``
    pairs under the symbol the exchange lists *today*, which is what the feed
    serves: a company renamed after the action is reported under the new name.
    """

    def __init__(self, provider, start, end, *, loader=None):
        self.provider = provider
        self.start = start
        self.end = end
        self.status = STATUS_NOT_LOADED
        self._loader = loader or _LOADERS[provider]
        self._ex_dates = None

    def _load(self):
        try:
            pairs = self._loader(self.start, self.end)
        except Exception as exc:  # an overlay must never be why a run dies
            logger.warning(
                "Action ledger (%s) unavailable for %s..%s; a demerger or "
                "rights issue too small to breach the opening cap keeps the "
                "vendor's unadjusted history this run: %s",
                self.provider,
                self.start,
                self.end,
                exc,
            )
            self.status = STATUS_UNAVAILABLE
            return {}
        ex_dates = {}
        for symbol, ex_date in pairs or ():
            symbol = str(symbol).strip().upper()
            if symbol and ex_date is not None:
                ex_dates.setdefault(symbol, set()).add(ex_date)
        self.status = STATUS_OK
        logger.info(
            "Action ledger (%s) loaded %d symbols for %s..%s",
            self.provider,
            len(ex_dates),
            self.start,
            self.end,
        )
        return {symbol: tuple(sorted(days)) for symbol, days in ex_dates.items()}

    def ex_dates(self, symbol):
        if self._ex_dates is None:
            self._ex_dates = self._load()
        return self._ex_dates.get(str(symbol).strip().upper(), ())


def history_window(as_of, *, days=800):
    """The span of ex-dates that can fall inside a two-year price history."""
    return as_of - timedelta(days=days), as_of


def _bars(frame, market_timezone):
    index = frame.index
    local = index.tz_convert(market_timezone) if index.tz is not None else index
    dates = np.array([stamp.date() for stamp in local])
    raw = pd.to_numeric(frame["Close"], errors="coerce").to_numpy(dtype=float)
    opens = pd.to_numeric(frame["Open"], errors="coerce").to_numpy(dtype=float)
    traded = np.flatnonzero(np.isfinite(raw) & (raw > 0))
    # Onto the vendor's adjusted basis, bar by bar.
    close = raw
    if "Adj Close" in frame.columns:
        adjusted = pd.to_numeric(frame["Adj Close"], errors="coerce").to_numpy(
            dtype=float
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(np.isfinite(adjusted) & (raw > 0), adjusted / raw, 1.0)
        close, opens = raw * ratio, opens * ratio
    return dates, opens, close, traded


def _bad_prints(dates, opens, close, traded, max_open_gap):
    """Positions of bars that gap beyond the cap and straight back."""
    from backtest.corporate_actions import open_gap_factor

    bad = []
    for before, bar, after in zip(traded, traded[1:], traded[2:]):
        if (dates[after] - dates[before]).days > MAX_DAYS_BETWEEN_BARS:
            continue
        into = open_gap_factor(close[before], opens[bar], close[bar], max_open_gap)
        out = open_gap_factor(close[bar], opens[after], close[after], max_open_gap)
        if into is None or out is None:
            continue
        # Either side of the bar agrees with the other: nothing changed but it.
        across = close[before] / opens[after]
        if max(across, 1.0 / across) <= max_open_gap:
            bad.append(bar)
    return bad


def restate_price_basis(frame, ex_dates, market_timezone, *, max_open_gap=None):
    """Return ``(frame, changes)`` with earlier adjusted closes on today's basis.

    ``ex_dates`` are the symbol's ledger ex-dates; ``max_open_gap`` is the
    market's opening cap as a ratio, or ``None`` where the open is uncapped.
    ``changes`` lists ``(session, kind, factor)`` for everything done, and is
    empty when the frame comes back untouched.
    """
    if frame is None or frame.empty or (not ex_dates and max_open_gap is None):
        return frame, []
    if not {"Open", "Close"} <= set(frame.columns):
        return frame, []
    if not isinstance(frame.index, pd.DatetimeIndex):
        return frame, []

    # Same rules as the chart, so the two cannot disagree about one change.
    from backtest.corporate_actions import ex_date_price_factor, open_gap_factor

    changes = []
    dates, opens, close, traded = _bars(frame, market_timezone)
    if max_open_gap is not None:
        bad = _bad_prints(dates, opens, close, traded, max_open_gap)
        if bad:
            changes.extend((dates[bar], CHANGE_BAD_PRINT, None) for bar in bad)
            frame = frame.drop(index=frame.index[bad])
            dates, opens, close, traded = _bars(frame, market_timezone)

    # The first traded bar on or after each ex-date is where the action lands.
    action_bars = set()
    for ex_date in ex_dates or ():
        after = traded[dates[traded] >= ex_date]
        if len(after) and (dates[after[0]] - ex_date).days <= MAX_DAYS_TO_FIRST_BAR:
            action_bars.add(int(after[0]))

    scale = np.ones(len(frame))
    restated_any = False
    for before, bar in zip(traded, traded[1:]):
        if int(bar) in action_bars:
            factor = ex_date_price_factor(close[before], opens[bar])
            kind = CHANGE_ACTION
        elif (
            max_open_gap is not None
            and (dates[bar] - dates[before]).days <= MAX_DAYS_BETWEEN_BARS
        ):
            factor = open_gap_factor(
                close[before], opens[bar], close[bar], max_open_gap
            )
            kind = CHANGE_OPEN_GAP
        else:
            factor = None
        if factor is None:
            continue
        scale[:bar] /= factor
        restated_any = True
        changes.append((dates[bar], kind, factor))

    if not changes:
        return frame, []
    if restated_any:
        frame = frame.copy()
        adjusted = pd.to_numeric(
            frame.get("Adj Close", frame["Close"]), errors="coerce"
        ).astype(float)
        frame["Adj Close"] = adjusted * scale
    return frame, sorted(changes, key=lambda change: change[0])
