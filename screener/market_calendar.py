"""Exchange holidays and special sessions, as rows for ``market_calendar``.

NSE's trading-holiday list names every weekday the exchange is shut and why.
It carries no hours, and it lists a special session on a Sunday (Diwali Laxmi
Pujan, "Muhurat trading") as a holiday with an asterisk; there is no feed of
special-session hours, so those are the checked-in ``SPECIAL_SESSIONS`` below,
to be extended from the exchange's circular each year. NYSE/Nasdaq holidays
are a static list. Display and scheduling only: nothing scores on it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

NSE_HOLIDAYS_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
_NSE_HOME = "https://www.nseindia.com/"
# NSE's API refuses requests that name no browser and carry no home-page cookie.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": _NSE_HOME,
}

# (day, reason, open, close) in exchange-local time. Source: NSE circular
# 149/2026 (Muhurat trading, Sunday 8 Nov 2026, 14:20-15:30 IST trading window).
SPECIAL_SESSIONS: dict[str, tuple[tuple[date, str, str, str], ...]] = {
    "NSE": ((date(2026, 11, 8), "Muhurat trading", "14:20", "15:30"),),
    "US": (),
}

# NYSE full-day closures (Nasdaq matches). Early 13:00 closes are not listed.
US_HOLIDAYS: tuple[tuple[date, str], ...] = (
    (date(2026, 1, 1), "New Year's Day"),
    (date(2026, 1, 19), "Martin Luther King Jr. Day"),
    (date(2026, 2, 16), "Washington's Birthday"),
    (date(2026, 4, 3), "Good Friday"),
    (date(2026, 5, 25), "Memorial Day"),
    (date(2026, 6, 19), "Juneteenth"),
    (date(2026, 7, 3), "Independence Day (observed)"),
    (date(2026, 9, 7), "Labor Day"),
    (date(2026, 11, 26), "Thanksgiving Day"),
    (date(2026, 12, 25), "Christmas Day"),
    (date(2027, 1, 1), "New Year's Day"),
    (date(2027, 1, 18), "Martin Luther King Jr. Day"),
    (date(2027, 2, 15), "Washington's Birthday"),
    (date(2027, 3, 26), "Good Friday"),
    (date(2027, 5, 31), "Memorial Day"),
    (date(2027, 6, 18), "Juneteenth (observed)"),
    (date(2027, 7, 5), "Independence Day (observed)"),
    (date(2027, 9, 6), "Labor Day"),
    (date(2027, 11, 25), "Thanksgiving Day"),
    (date(2027, 12, 24), "Christmas Day (observed)"),
)


def fetch_nse_holidays() -> dict[str, Any] | None:
    """NSE's trading-holiday payload, or None when it cannot be had."""
    try:
        session = requests.Session()
        session.get(_NSE_HOME, headers=_HEADERS, timeout=20)
        response = session.get(NSE_HOLIDAYS_URL, headers=_HEADERS, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning("NSE holiday list unavailable (%s)", exc)
        return None


def parse_nse_holidays(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Weekday equity-market holidays from NSE's ``CM`` list; weekends are not rows."""
    rows = []
    for entry in (payload or {}).get("CM") or []:
        try:
            day = datetime.strptime(entry["tradingDate"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        if day.weekday() < 5:
            reason = str(entry.get("description") or "Exchange holiday").rstrip("*").strip()
            rows.append(_row(day, "holiday", reason))
    return rows


def _row(day: date, kind: str, reason: str, opens: str | None = None, closes: str | None = None) -> dict[str, Any]:
    return {"day": day.isoformat(), "kind": kind, "reason": reason, "session_open": opens, "session_close": closes}


def calendar_rows(market: str, nse_payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every holiday and special session known for ``market``; a special session wins its day."""
    holidays = parse_nse_holidays(nse_payload) if market == "NSE" else [_row(d, "holiday", why) for d, why in US_HOLIDAYS]
    special = [_row(d, "special_session", why, opens, closes) for d, why, opens, closes in SPECIAL_SESSIONS.get(market, ())]
    taken = {row["day"] for row in special}
    return sorted([*special, *(row for row in holidays if row["day"] not in taken)], key=lambda row: row["day"])


def entry_for(rows: list[dict[str, Any]], day: date) -> dict[str, Any] | None:
    """The calendar row for ``day`` (exchange-local), if it has one."""
    return next((row for row in rows if row["day"] == day.isoformat()), None)
