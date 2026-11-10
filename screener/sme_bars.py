"""Daily bars for NSE SME names that Yahoo does not carry, from the bhavcopy.

Yahoo prices about half of NSE's SME list. For the rest the exchange's own daily
file is the only source, so its SME series (SM, ST, SZ) are kept as one
history file: read on the first lookup, topped up with the sessions it lacks
(a cold start fetches the whole window once, later runs one day), and saved
back for the workflow's cache. Bars are unadjusted; the caller runs them through
``price_basis.restate_price_basis`` like any vendor series.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import timedelta
from pathlib import Path

import pandas as pd

from .market_data import is_expected_nse_session

logger = logging.getLogger(__name__)

SME_SERIES = frozenset({"SM", "ST", "SZ"})
_FIELDS = ("Open", "High", "Low", "Close", "Volume")
_COLUMNS = ("Date", "Symbol", *_FIELDS)


def _fetch_sme_day(session):
    """One session's SME rows, normalised by the backtest's bhavcopy parser."""
    from backtest.bhavcopy import BhavcopyStore

    with tempfile.TemporaryDirectory(prefix="sme_bhavcopy_") as root:
        return BhavcopyStore(root, series=SME_SERIES).fetch_day(session)


class SmeBarHistory:
    """SME daily bars by symbol, built lazily from the stored history."""

    def __init__(
        self,
        path,
        expected_session,
        market_timezone,
        *,
        market_holidays=(),
        history_days=740,
        max_fetch_per_run=600,
        max_consecutive_misses=10,
        fetch_day=None,
    ):
        self.path = Path(path)
        self.expected_session = expected_session
        self.market_timezone = market_timezone
        self.market_holidays = market_holidays
        self.history_days = history_days
        self.max_fetch_per_run = max_fetch_per_run
        self.max_consecutive_misses = max_consecutive_misses
        self._fetch_day = fetch_day or _fetch_sme_day
        self._by_symbol = None
        self._sessions = []

    def _stored(self):
        if not self.path.exists():
            return pd.DataFrame(columns=list(_COLUMNS))
        try:
            return pd.read_csv(self.path, compression="gzip", dtype={"Symbol": str})
        except Exception as exc:  # an unreadable file is rebuilt, not fatal
            logger.warning("SME bar history unreadable (%s); rebuilding", exc)
            return pd.DataFrame(columns=list(_COLUMNS))

    def _missing_sessions(self, have):
        start = self.expected_session - timedelta(days=self.history_days)
        days = [start + timedelta(days=n) for n in range((self.expected_session - start).days + 1)]
        return [
            day for day in days
            if is_expected_nse_session(day, self.market_holidays) and day.isoformat() not in have
        ]

    def _update(self):
        stored = self._stored()
        cutoff = (self.expected_session - timedelta(days=self.history_days)).isoformat()
        stored = stored.loc[stored["Date"] >= cutoff]
        have = set(stored["Date"])
        fetched = [stored]
        todo = self._missing_sessions(have)[-self.max_fetch_per_run:]
        misses = 0
        previous = None
        for day in reversed(todo):  # newest first: the recent bars matter most
            # ``todo`` holds only the sessions we lack, so a stored session between two
            # misses means they are holidays apart, not an exchange refusing us.
            if previous is not None and any(
                (day + timedelta(days=n)).isoformat() in have for n in range(1, (previous - day).days)
            ):
                misses = 0
            previous = day
            try:
                frame = self._fetch_day(day)
            except Exception as exc:  # a holiday the calendar lacks looks the same
                logger.debug("No SME bhavcopy for %s: %s", day, exc)
                misses += 1
                # One or two in a row is a holiday; more is NSE refusing us, and
                # each try can take the client's full timeout.
                if misses >= self.max_consecutive_misses:
                    logger.warning("SME bar history: %d fetches failed in a row; stopping", misses)
                    break
                continue
            misses = 0
            rows = frame.rename(columns={"Trade_Date": "Date"})[list(_COLUMNS)]
            fetched.append(rows)
        history = pd.concat(fetched, ignore_index=True)
        history = history.drop_duplicates(["Date", "Symbol"], keep="last").sort_values(["Symbol", "Date"])
        if len(history) != len(stored):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            history.to_csv(self.path, index=False, compression="gzip")
        logger.info("SME bar history: %d rows, %d session(s) fetched", len(history), len(todo))
        return history

    def _load(self):
        try:
            history = self._update()
        except Exception as exc:  # a fallback must never be why a run dies
            logger.warning("SME bar history unavailable: %s", exc)
            return {}
        self._sessions = sorted(history["Date"].unique())
        return dict(tuple(history.groupby("Symbol")))

    def bars(self, symbol):
        """Yahoo-shaped frame (tz-aware daily index, ``Adj Close`` = ``Close``) or ``None``."""
        if self._by_symbol is None:
            self._by_symbol = self._load()
        rows = self._by_symbol.get(str(symbol).strip().upper())
        if rows is None or rows.empty:
            return None
        # A session the name did not trade is still a session: carry the close
        # forward with no volume, as Yahoo does, so the bar stays aligned.
        rows = rows.set_index("Date")[list(_FIELDS)].astype(float)
        rows = rows.reindex([day for day in self._sessions if day >= rows.index[0]])
        close = rows["Close"].ffill()
        rows["Volume"] = rows["Volume"].fillna(0.0)
        for field in ("Open", "High", "Low", "Close"):
            rows[field] = rows[field].fillna(close)
        rows["Adj Close"] = rows["Close"]
        rows.index = pd.DatetimeIndex(pd.to_datetime(rows.index)).tz_localize(self.market_timezone)
        return rows[["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
