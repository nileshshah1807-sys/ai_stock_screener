"""Empirical NSE trading calendar, derived from bhavcopy availability.

A backtest needs to know exactly which dates were sessions, because "the next
trading day" is what an order actually fills on. Deriving that from a
hand-maintained holiday list means every wrong or missing entry becomes a
mispriced fill.

So the calendar is derived from the archive instead: a date is a session if and
only if the exchange published a cash-market bhavcopy for it. That is
authoritative and self-correcting.

One ambiguity has to be handled honestly. A weekday with no bhavcopy is either an
exchange holiday or a file that has not been published yet -- the exchange
returns the same "file is unavailable" for both. The distinction is resolved
positionally: once a *later* session has been confirmed, an earlier weekday
without a file can no longer be "not yet published", so it is a holiday. Until
then it stays ``UNKNOWN`` and is excluded from the calendar rather than guessed
at. This is why the ledger stores a tri-state and not a boolean.
"""

from __future__ import annotations

from datetime import date, datetime
import logging
from pathlib import Path

import pandas as pd

from .bhavcopy import candidate_sessions

logger = logging.getLogger(__name__)

SESSION = "session"
NO_SESSION = "no_session"
UNKNOWN = "unknown"

LEDGER_COLUMNS = ("Date", "Status", "Probes", "First_Probed_At", "Last_Probed_At")


class CalendarLedger:
    """Persistent record of what is known about each candidate date."""

    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now())
        self._rows = self._load()

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            frame = pd.read_csv(self.path)
        except Exception as exc:
            logger.warning("Calendar ledger unreadable, starting empty: %s", exc)
            return {}
        rows = {}
        for record in frame.to_dict("records"):
            try:
                day = date.fromisoformat(str(record["Date"]).strip()[:10])
            except (KeyError, ValueError):
                continue
            rows[day] = {
                "Status": str(record.get("Status") or UNKNOWN).strip() or UNKNOWN,
                "Probes": int(pd.to_numeric(record.get("Probes"), errors="coerce") or 0),
                "First_Probed_At": record.get("First_Probed_At") or "",
                "Last_Probed_At": record.get("Last_Probed_At") or "",
            }
        return rows

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(
            [
                {
                    "Date": day.isoformat(),
                    "Status": row["Status"],
                    "Probes": row["Probes"],
                    "First_Probed_At": row["First_Probed_At"],
                    "Last_Probed_At": row["Last_Probed_At"],
                }
                for day, row in sorted(self._rows.items())
            ],
            columns=list(LEDGER_COLUMNS),
        )
        frame.to_csv(self.path, index=False)
        return self.path

    def status(self, day):
        row = self._rows.get(day)
        return row["Status"] if row else UNKNOWN

    def probes(self, day):
        row = self._rows.get(day)
        return row["Probes"] if row else 0

    def record(self, day, status):
        stamp = pd.Timestamp(self._clock()).isoformat(timespec="seconds")
        row = self._rows.setdefault(
            day,
            {"Status": UNKNOWN, "Probes": 0, "First_Probed_At": stamp, "Last_Probed_At": stamp},
        )
        row["Status"] = status
        row["Probes"] += 1
        row["Last_Probed_At"] = stamp
        if not row["First_Probed_At"]:
            row["First_Probed_At"] = stamp
        return row

    def sessions(self):
        return sorted(day for day, row in self._rows.items() if row["Status"] == SESSION)

    def unresolved(self):
        return sorted(day for day, row in self._rows.items() if row["Status"] == UNKNOWN)

    def resolve_pending(self):
        """Promote ``UNKNOWN`` weekdays that a later session has settled.

        A missing file can only mean "not published yet" if nothing after it has
        been published. Once a later session exists, an earlier gap is a holiday.
        Returns the number of dates promoted.
        """
        sessions = self.sessions()
        if not sessions:
            return 0
        latest_session = sessions[-1]
        promoted = 0
        for day in self.unresolved():
            if day < latest_session and self._rows[day]["Probes"] > 0:
                self._rows[day]["Status"] = NO_SESSION
                promoted += 1
        return promoted


class TradingCalendar:
    """Sessions confirmed by the archive, with next/previous session lookups."""

    def __init__(self, sessions):
        self.sessions = sorted({_as_date(day) for day in sessions})
        self._index = {day: position for position, day in enumerate(self.sessions)}

    def __len__(self):
        return len(self.sessions)

    def __contains__(self, day):
        return _as_date(day) in self._index

    def next_session(self, day, offset=1):
        """The ``offset``-th session strictly after ``day``, or None.

        This is the execution primitive: a signal on the close of *t* fills at
        ``next_session(t)``. Returning None rather than clamping is deliberate --
        a position that cannot be filled inside the data must be dropped, not
        silently filled at the last available price.
        """
        day = _as_date(day)
        if offset < 1:
            raise ValueError("offset must be >= 1")
        position = self._searchsorted_after(day)
        target = position + offset - 1
        if target >= len(self.sessions):
            return None
        return self.sessions[target]

    def previous_session(self, day, offset=1):
        """The ``offset``-th session strictly before ``day``, or None."""
        day = _as_date(day)
        if offset < 1:
            raise ValueError("offset must be >= 1")
        # Strictly before, so the search must exclude ``day`` itself even when
        # ``day`` is a session. ``session_on_or_before`` is the inclusive variant.
        position = self._searchsorted_at_or_after(day) - 1
        target = position - offset + 1
        if target < 0:
            return None
        return self.sessions[target]

    def session_on_or_before(self, day):
        day = _as_date(day)
        position = self._searchsorted_before(day)
        return self.sessions[position] if position >= 0 else None

    def sessions_between(self, start, end):
        start, end = _as_date(start), _as_date(end)
        return [day for day in self.sessions if start <= day <= end]

    def session_after_calendar_months(self, day, months):
        """First session at or after ``day`` plus ``months`` calendar months.

        Horizons are expressed in months rather than a fixed session count so a
        "3-month forward return" means the same span of market time regardless of
        how many holidays fell inside it.
        """
        day = _as_date(day)
        target = (pd.Timestamp(day) + pd.DateOffset(months=int(months))).date()
        for candidate in self.sessions:
            if candidate >= target:
                return candidate
        return None

    def _searchsorted_after(self, day):
        low, high = 0, len(self.sessions)
        while low < high:
            mid = (low + high) // 2
            if self.sessions[mid] <= day:
                low = mid + 1
            else:
                high = mid
        return low

    def _searchsorted_at_or_after(self, day):
        """Index of the first session >= ``day``."""
        low, high = 0, len(self.sessions)
        while low < high:
            mid = (low + high) // 2
            if self.sessions[mid] < day:
                low = mid + 1
            else:
                high = mid
        return low

    def _searchsorted_before(self, day):
        """Index of the last session <= ``day``, or -1 when none exists."""
        return self._searchsorted_after(day) - 1


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def build_calendar(
    store,
    start,
    end,
    *,
    ledger,
    market_holidays=(),
    max_fetches=None,
    on_progress=None,
):
    """Ingest bhavcopies across ``[start, end]`` and return a `TradingCalendar`.

    Resumable and bounded. ``max_fetches`` caps network work per invocation so a
    cold multi-year build can be spread over several runs instead of turning one
    run into a multi-hour job -- the same budgeting pattern the production
    statement cache uses.
    """
    candidates = candidate_sessions(start, end, market_holidays)
    fetched = failed = 0

    for day in candidates:
        if store.has_day(day):
            if ledger.status(day) != SESSION:
                ledger.record(day, SESSION)
            continue
        if ledger.status(day) == NO_SESSION:
            continue
        if max_fetches is not None and fetched >= max_fetches:
            break
        try:
            store.fetch_day(day)
            ledger.record(day, SESSION)
            fetched += 1
        except Exception as exc:
            # Cannot distinguish holiday from not-yet-published here; record the
            # probe and let resolve_pending() settle it positionally.
            ledger.record(day, UNKNOWN)
            failed += 1
            logger.debug("No bhavcopy for %s: %s", day, exc)
        if on_progress is not None:
            on_progress(day, fetched, failed)

    promoted = ledger.resolve_pending()
    ledger.save()
    logger.info(
        "Calendar build: %d sessions cached, %d fetched, %d unavailable, "
        "%d resolved as holidays, %d still unresolved",
        len(ledger.sessions()),
        fetched,
        failed,
        promoted,
        len(ledger.unresolved()),
    )
    return TradingCalendar(ledger.sessions())
