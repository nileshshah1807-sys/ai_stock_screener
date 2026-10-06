"""Exchange-published bar for the expected session, when the vendor lacks it.

Yahoo is the price source, and it is usually complete within an hour or two of
the close. On 5 Oct 2026 it was not: twenty hours after the NSE close it still
served no bar for that session on two thirds of the universe -- 1 Oct, then the
live 6 Oct row, with a hole between. Waiting does not help with a hole, and the
alignment guard in ``app.py`` rightly refused to score the cross-section.

NSE publishes the session itself every evening as the bhavcopy. This module
fills *one bar* from it -- the expected completed session, for a symbol whose
Yahoo history stops exactly one bar short -- and leaves everything else to
Yahoo. It is deliberately narrow:

* Only the expected session is ever patched. History, adjustment factors and
  every earlier bar stay the vendor's.
* A bar is patched only when it continues the vendor's history: the exchange's
  previous close must equal the vendor's last close. That rejects a symbol
  missing more than one session and a symbol whose two sources are on different
  price scales.
* A one-session move beyond ``MAX_SESSION_MOVE`` is not patched. A split or
  bonus the vendor has not yet applied looks exactly like that, and joining an
  unadjusted bar to adjusted history would manufacture a crash.

A symbol that fails any of these is left as it was -- one session behind, the
state the guard already counts -- so the patch can only raise alignment.

The adjusted close of a patched bar carries the previous bar's adjustment
factor. That is exact unless the patched session is itself an ex-dividend date,
in which case that one day's adjusted return is understated by the dividend
yield until the vendor serves the bar; the next run then replaces it.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# NSE's widest daily price band is 20%. Names without a band can move further,
# but so does an unapplied split, and the two cannot be told apart from one bar.
MAX_SESSION_MOVE = 0.25
# Yahoo serves closes as float32, so 1094.2 arrives as 1094.199951.
PREV_CLOSE_TOLERANCE = 0.005

_PRICE_FIELDS = ("Open", "High", "Low", "Close")


def _load_nse_bhavcopy(session, cache_root):
    # Imported here so a market without a fallback never loads the NSE client.
    from backtest.bhavcopy import BhavcopyStore

    return BhavcopyStore(cache_root).get_day(session)


_LOADERS = {"nse_bhavcopy": _load_nse_bhavcopy}


class SessionBarSource:
    """One session's exchange-published bars, fetched on first use.

    Most runs never need it, so nothing is requested until a symbol is found
    short of the expected session. A failed fetch is reported once and every
    later lookup answers ``None``: before the exchange has published the file
    the run simply behaves as it did without a fallback.
    """

    def __init__(self, provider, session, cache_root, *, loader=None):
        self.provider = provider
        self.session = session
        self.cache_root = cache_root
        self._loader = loader or _LOADERS[provider]
        self._bars = None

    def _load(self):
        try:
            frame = self._loader(self.session, self.cache_root)
        except Exception as exc:  # a fallback must never be why a run dies
            logger.warning(
                "Session-bar fallback (%s) unavailable for %s: %s",
                self.provider,
                self.session,
                exc,
            )
            return {}
        if frame is None or frame.empty or "Symbol" not in frame.columns:
            logger.warning(
                "Session-bar fallback (%s) returned no bars for %s",
                self.provider,
                self.session,
            )
            return {}
        frame = frame.drop_duplicates(subset=["Symbol"], keep="first")
        logger.info(
            "Session-bar fallback (%s) loaded %d bars for %s",
            self.provider,
            len(frame),
            self.session,
        )
        return {
            str(record["Symbol"]).strip().upper(): record
            for record in frame.to_dict("records")
        }

    def bar(self, symbol):
        if self._bars is None:
            self._bars = self._load()
        return self._bars.get(str(symbol).strip().upper())


def _number(value):
    number = pd.to_numeric(value, errors="coerce")
    return float(number) if np.isfinite(number) else None


def patch_expected_session_bar(frame, expected_session, market_timezone, lookup):
    """Return ``(frame, patched)`` with the expected session filled if it can be.

    ``lookup`` is called with no arguments, and only once the frame is known to
    lack a usable bar for ``expected_session``; it returns the exchange's bar
    for this symbol or ``None``.
    """
    if frame is None or frame.empty or not {"Close", "Volume"} <= set(frame.columns):
        return frame, False
    if not isinstance(frame.index, pd.DatetimeIndex):
        return frame, False
    index = frame.index
    local = index.tz_convert(market_timezone) if index.tz is not None else index
    dates = np.array([stamp.date() for stamp in local])

    close = pd.to_numeric(frame["Close"], errors="coerce")
    volume = pd.to_numeric(frame["Volume"], errors="coerce")
    adjusted = pd.to_numeric(frame.get("Adj Close", frame["Close"]), errors="coerce")
    usable = (close.notna() & volume.notna() & adjusted.notna()).to_numpy()

    on_session = dates == expected_session
    if (on_session & usable).any():
        return frame, False
    earlier = np.flatnonzero((dates < expected_session) & usable)
    if len(earlier) == 0:
        return frame, False

    bar = lookup()
    if bar is None:
        return frame, False
    bar_close = _number(bar.get("Close"))
    bar_prev_close = _number(bar.get("Prev_Close"))
    bar_volume = _number(bar.get("Volume"))
    if not bar_close or not bar_prev_close or not bar_volume:
        return frame, False
    if bar_close <= 0 or bar_prev_close <= 0 or bar_volume <= 0:
        return frame, False

    last = earlier[-1]
    last_close = float(close.iloc[last])
    if last_close <= 0:
        return frame, False
    if abs(last_close / bar_prev_close - 1.0) > PREV_CLOSE_TOLERANCE:
        return frame, False
    if abs(bar_close / bar_prev_close - 1.0) > MAX_SESSION_MOVE:
        return frame, False

    values = {field: _number(bar.get(field)) for field in _PRICE_FIELDS}
    values["Close"] = bar_close
    values["Volume"] = bar_volume
    if "Adj Close" in frame.columns:
        values["Adj Close"] = bar_close * float(adjusted.iloc[last]) / last_close

    patched = frame.copy()
    if on_session.any():
        label = index[np.flatnonzero(on_session)[-1]]
    else:
        label = pd.Timestamp(expected_session)
        if index.tz is not None:
            label = label.tz_localize(market_timezone).tz_convert(index.tz)
    for field, value in values.items():
        if field not in patched.columns or value is None:
            continue
        if not pd.api.types.is_float_dtype(patched[field]):
            patched[field] = pd.to_numeric(patched[field], errors="coerce").astype(float)
        patched.loc[label, field] = value
    return patched.sort_index(), True
