"""What management said against what it did, and guidance it stopped repeating.

Two readings of a call's stored extraction that no score uses yet:

* **Said vs did** -- the growth a call guided for a financial year (or half) set
  against the growth the filed quarterly results of that period then showed:
  ``kept``, ``missed`` or ``not_yet_due``. Only a company-wide revenue or profit
  growth figure for a period named as ``FY27``, ``H1 FY27`` or ``H2 FY27`` can
  be checked. Margin, order-book and capacity statements carry no figure the
  filings hold, and are not checked: silence is not a pass.
* **Dropped guidance** -- guidance the company gave on its previous call and did
  not restate (`compare_outlooks` item ``guidance`` / ``not_restated``).

Both are display evidence stored beside the call. The ranking does not read
them: whether either adds anything is measured first (see the PR note).
``filings`` are read as of ``as_of`` -- a filing counts only from the day it
was filed -- so the same function serves a point-in-time check.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from screener.numeric import round_half_up, safe_float

#: The env flag that switches both readings on in the Concalls feed.
ENV_FLAG = "OUTLOOK_PROMISE_TRACKING"
#: Percentage points a company may fall short of the guided figure and still have kept it.
TOLERANCE_POINTS = 2.0

KEPT, MISSED, NOT_YET_DUE = "kept", "missed", "not_yet_due"

_PERIOD = re.compile(
    r"(?<![A-Za-z0-9])(?:(H[12])\s*[-\s]?)?FY\s*'?(\d{4}|\d{2})(?!-?\d)(?:\s*[-\s]?(H[12])\b)?", re.IGNORECASE
)
# A nine-month or single-quarter figure is not a year's: never graded against one.
_PART_YEAR = re.compile(r"(?<![A-Za-z])(?:\d{1,2}M|Q[1-4])", re.IGNORECASE)
_LINE = {"revenue": "revenue", "profit": "net_profit"}


def flag_on(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def period_quarters(period: Any) -> list[date] | None:
    """Quarter ends of an Indian financial year, or of its half, named in ``period``.

    ``FY27`` is April 2026 to March 2027. Anything else -- a calendar year, "next
    year", ``FY26-27``, ``9M FY27``, a quarter -- is None: it is not guessed.
    """
    text = str(period or "")
    found = _PERIOD.search(text)
    if not found or _PART_YEAR.search(text):
        return None
    half = (found.group(1) or found.group(3) or "").upper()
    year = int(found.group(2))
    year += 2000 if year < 100 else 0
    ends = [date(year - 1, 6, 30), date(year - 1, 9, 30), date(year - 1, 12, 31), date(year, 3, 31)]
    return {"H1": ends[:2], "H2": ends[2:]}.get(half, ends)


def _year_ago(end: date) -> date:
    return date(end.year - 1, end.month, end.day)


def _filed(filings: Iterable[dict[str, Any]], as_of: date) -> dict[bool, dict[date, dict[str, Any]]]:
    """Filings visible on ``as_of``: basis -> quarter end -> its lines (latest filing wins)."""
    by_basis: dict[bool, dict[date, tuple[str, dict[str, Any]]]] = {True: {}, False: {}}
    for row in filings:
        try:
            end = date.fromisoformat(str(row["period_end"])[:10])
            filed = str(row.get("filed_at") or "")[:10]
            if not filed or date.fromisoformat(filed) > as_of:
                continue
        except (KeyError, ValueError):
            continue
        basis = by_basis[bool(row.get("is_consolidated"))]
        if end not in basis or filed >= basis[end][0]:
            basis[end] = (filed, row.get("lines") or {})
    return {basis: {end: lines for end, (_, lines) in rows.items()} for basis, rows in by_basis.items()}


def guidance_outcome(
    extraction: dict[str, Any] | None,
    filings: Iterable[dict[str, Any]],
    as_of: date,
) -> dict[str, Any] | None:
    """Whether the growth a call guided came true, or None where it cannot be checked.

    ``kept`` when the period's growth, on one basis (consolidated preferred),
    reached the guided figure less `TOLERANCE_POINTS`; ``missed`` when it did
    not; ``not_yet_due`` while a quarter of the period is not yet filed.
    """
    guidance = (extraction or {}).get("guidance") or {}
    guided = safe_float(guidance.get("growth_pct"))
    line = _LINE.get(guidance.get("growth_metric") or "revenue")
    quarters = period_quarters(guidance.get("period"))
    if (
        guided is None
        or guidance.get("direction") in (None, "none")
        or guidance.get("scope") == "segment"
        or line is None
        or quarters is None
    ):
        return None
    detail = {"metric": guidance.get("growth_metric") or "revenue", "period": guidance["period"], "guided_pct": guided}
    visible = _filed(filings, as_of)
    for consolidated in (True, False):
        rows = visible[consolidated]
        if all(end in rows for end in quarters):
            if not all(_year_ago(end) in rows for end in quarters):
                continue
            now = [safe_float(rows[end].get(line)) for end in quarters]
            then = [safe_float(rows[_year_ago(end)].get(line)) for end in quarters]
            if None in now or None in then or sum(then) <= 0:  # type: ignore[arg-type]
                return None
            actual = 100.0 * (sum(now) / sum(then) - 1.0)  # type: ignore[arg-type]
            kept = actual >= guided - TOLERANCE_POINTS
            return detail | {"outcome": KEPT if kept else MISSED, "actual_pct": round_half_up(actual, 1)}
    if as_of < quarters[-1] + timedelta(days=1) or not any(quarters[-1] in rows for rows in visible.values()):
        return detail | {"outcome": NOT_YET_DUE}
    return None


def guidance_dropped(changes: Iterable[dict[str, Any]] | None) -> bool:
    """Whether the call left out guidance the company gave on its previous one."""
    return any(
        change.get("item") == "guidance" and change.get("change") == "not_restated"
        for change in changes or []
        if isinstance(change, dict)
    )


def promise_record(outcomes: Iterable[dict[str, Any] | None]) -> dict[str, int]:
    """A company's checked guidance so far: how many were kept and how many missed.

    A period guided on several calls is one promise, counted once. Pass the
    outcomes oldest call first: where the figure changed, the latest guidance
    is the one counted.
    """
    once: dict[tuple[Any, ...], str] = {}
    for item in outcomes:
        if item:
            once[(item["metric"], tuple(period_quarters(item["period"]) or ()))] = item["outcome"]
    checked = list(once.values())
    return {KEPT: checked.count(KEPT), MISSED: checked.count(MISSED)}
