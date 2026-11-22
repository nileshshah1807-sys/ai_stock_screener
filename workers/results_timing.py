"""How far each stock is from its results, as snapshot columns.

- ``days_since_result``: days from the latest quarter's first announcement
  (``quarterly_filings.broadcast_at``, in the market's own time; for a US row,
  when we first saw the quarter) to the run date.
- ``days_to_result``: days from the run date to the announced results date
  (``upcoming_events.next_result_date``); a date already passed is no date.

Display evidence for filters: nothing in ``screener/`` reads it, and a source
that cannot be read leaves its column null rather than failing the publish.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

COLUMNS = ("days_since_result", "days_to_result")

# A company files every quarter; a result older than this is not its latest any more.
MAX_RESULT_AGE_DAYS = 200


def _local_day(value: Any, zone: ZoneInfo) -> date | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(zone).date() if moment.tzinfo else moment.date()


def days_since(broadcasts: list[dict[str, Any]], run_date: date, zone: ZoneInfo) -> dict[str, int]:
    """``{symbol: days since its latest announced quarter}``; an announcement after the run date is ignored."""
    latest: dict[str, date] = {}
    for row in broadcasts:
        day = _local_day(row.get("broadcast_at"), zone)
        symbol = row.get("symbol")
        if symbol and day is not None and day <= run_date and day > latest.get(symbol, date.min):
            latest[symbol] = day
    return {symbol: (run_date - day).days for symbol, day in latest.items()}


def days_to(upcoming: dict[str, dict[str, Any]], run_date: date) -> dict[str, int]:
    """``{symbol: days until its announced results date}``, that date not yet passed."""
    out = {}
    for symbol, row in upcoming.items():
        try:
            day = date.fromisoformat(str(row.get("next_result_date"))[:10])
        except ValueError:
            continue
        if day >= run_date:
            out[symbol] = (day - run_date).days
    return out


def snapshot_fields(repository: Any, run_date: str, timezone: str) -> dict[str, dict[str, int]]:
    """Each symbol's results-timing columns; the publisher writes them."""
    day, zone = date.fromisoformat(run_date), ZoneInfo(timezone)
    out: dict[str, dict[str, int]] = {}
    try:
        since = (day - timedelta(days=MAX_RESULT_AGE_DAYS)).isoformat()
        for symbol, days in days_since(repository.result_broadcasts_since(since), day, zone).items():
            out.setdefault(symbol, {})["days_since_result"] = days
    except Exception as exc:  # noqa: BLE001 -- display evidence: the run publishes without it
        logger.warning("Filed results unreadable, days since results left empty: %s", exc)
    try:
        for symbol, days in days_to(repository.upcoming_events(), day).items():
            out.setdefault(symbol, {})["days_to_result"] = days
    except Exception as exc:  # noqa: BLE001 -- display evidence: the run publishes without it
        logger.warning("Upcoming events unreadable, days to results left empty: %s", exc)
    return out
