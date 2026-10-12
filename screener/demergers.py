"""Restate a vendor's price history across a demerger.

On a demerger's ex-date the parent's price falls by the value of the business
carved out of it. Holders lose nothing -- they are handed shares in the new
company -- but the vendor's adjusted close does not know that: Yahoo records no
adjustment for an NSE demerger and serves ``Adj Close`` falling in step with
the raw close (verified 12 Oct 2026 against every 2026 demerger in the feed).
Left alone, every return, moving average and stage label for the parent reads
a crash that never happened, for as long as the ex-date stays inside the
history window.

The exchange's corporate-action feed says *which* symbols demerged and when; the
vendor's own bars say by how much. The ex-date opens through a special
price-discovery session, so ``previous close / ex-date open`` is the market's
split of the old price, and every adjusted close before the ex-date is divided
by it. Only ``Adj Close`` moves: raw closes still price turnover, and the high
and low follow the adjusted close as they already do.

Guards, each chosen so a miss leaves the history exactly as the vendor served it:

* Only symbols the feed names are touched. A large fall with no demerger behind
  it is a fall.
* A feed that cannot be fetched is reported once and adjusts nothing.
* An ex-date bar that opens at or above the previous close is not a ratio.
* The ex-date bar has to be in the frame. A parent suspended past its ex-date
  is restated on the run that first sees it trade again.
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# A demerged parent can stay suspended for a few sessions past its ex-date; its
# first bar after that is still the price discovery. Calendar days.
MAX_DAYS_TO_FIRST_BAR = 21

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NOT_LOADED = "not_loaded"


def _load_nse_demergers(start, end):
    # Imported here so a market without a ledger never loads the NSE client.
    from tempfile import TemporaryDirectory

    from nse import NSE

    from backtest.corporate_actions import ACTION_DEMERGER, normalise_actions

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
    demergers = frame[frame["Action_Type"] == ACTION_DEMERGER]
    return [
        (str(record["Symbol"]), pd.Timestamp(record["Ex_Date"]).date())
        for record in demergers.to_dict("records")
    ]


_LOADERS = {"nse_actions": _load_nse_demergers}


class DemergerLedger:
    """Demerger ex-dates per symbol for one run's history window.

    Fetched once, on the first lookup. The loader returns ``(symbol, ex_date)``
    pairs under the symbol the exchange lists *today*, which is what the feed
    serves: a parent renamed after its demerger is reported under the new name.
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
                "Demerger ledger (%s) unavailable for %s..%s; demerged parents "
                "keep the vendor's unadjusted history this run: %s",
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
            "Demerger ledger (%s) loaded %d symbols for %s..%s",
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


def restate_for_demergers(frame, ex_dates, market_timezone):
    """Return ``(frame, applied)`` with pre-demerger adjusted closes restated.

    ``applied`` lists ``(session, factor)`` for each ex-date that was priced
    from the frame's own bars; it is empty when the frame comes back untouched.
    """
    if not ex_dates or frame is None or frame.empty:
        return frame, []
    if not {"Open", "Close"} <= set(frame.columns):
        return frame, []
    if not isinstance(frame.index, pd.DatetimeIndex):
        return frame, []

    # Same rule as the chart, so the two cannot disagree about one demerger.
    from backtest.corporate_actions import demerger_price_factor

    index = frame.index
    local = index.tz_convert(market_timezone) if index.tz is not None else index
    dates = np.array([stamp.date() for stamp in local])
    close = pd.to_numeric(frame["Close"], errors="coerce").to_numpy(dtype=float)
    opens = pd.to_numeric(frame["Open"], errors="coerce").to_numpy(dtype=float)
    traded = np.isfinite(close) & (close > 0)

    scale = np.ones(len(frame))
    applied = []
    for ex_date in sorted(ex_dates):
        after = np.flatnonzero((dates >= ex_date) & traded)
        before = np.flatnonzero((dates < ex_date) & traded)
        if len(after) == 0 or len(before) == 0:
            continue
        first, last = after[0], before[-1]
        if (dates[first] - ex_date).days > MAX_DAYS_TO_FIRST_BAR:
            continue
        factor = demerger_price_factor(close[last], opens[first])
        if factor is None:
            continue
        scale[:first] /= factor
        applied.append((dates[first], factor))

    if not applied:
        return frame, []
    restated = frame.copy()
    adjusted = pd.to_numeric(
        restated.get("Adj Close", restated["Close"]), errors="coerce"
    ).astype(float)
    restated["Adj Close"] = adjusted * scale
    return restated, applied
