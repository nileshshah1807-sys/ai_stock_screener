"""Reporting-cycle helpers for earnings-call evidence.

An earnings-call transcript is useful only in the reporting cycle it explains.
Raw age alone is insufficient: until the next result is due, the preceding
call is still the latest available management evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


CURRENT_CYCLE = "Current cycle"
PRIOR_CYCLE = "Prior cycle"
EXPIRED = "Expired"
INVALID_DATE = "Invalid date"


@dataclass(frozen=True)
class TranscriptEvidence:
    status: str
    age_days: int | None
    period_end: date | None
    expected_period_end: date | None

    @property
    def scoring_eligible(self) -> bool:
        return self.status == CURRENT_CYCLE


def reporting_period_end_for_call(call_date: date) -> date:
    """Infer the result period discussed by a call from its announcement date.

    Calls are normally held after a period ends. A call exactly on a quarter
    end is assigned to the preceding period to avoid claiming knowledge of a
    quarter that had not yet closed.
    """

    candidates = [
        quarter_end
        for year in range(call_date.year - 2, call_date.year + 1)
        for quarter_end in _quarter_ends(year)
        if quarter_end < call_date
    ]
    return max(candidates)


def disclosure_deadline(period_end: date) -> date:
    """Return the normal SEBI result deadline for the reporting period.

    Regulation 33 allows 45 days for the first three quarters and 60 days for
    the final/annual quarter. This is a screening policy, not a compliance
    opinion for issuers with special circumstances.
    """

    days = 60 if (period_end.month, period_end.day) == (3, 31) else 45
    return period_end + timedelta(days=days)


def _holiday_dates(values) -> frozenset[date]:
    if values is None:
        return frozenset()
    if isinstance(values, str):
        values = values.split(",")
    holidays = set()
    for value in values:
        parsed = _parse_date(value)
        if parsed is not None:
            holidays.add(parsed)
    return frozenset(holidays)


def transcript_availability_deadline(
    period_end: date, market_holidays=()
) -> date:
    """Add NSE's five trading-working-day transcript window."""

    deadline = disclosure_deadline(period_end)
    holidays = _holiday_dates(market_holidays)
    working_days = 0
    while working_days < 5:
        deadline += timedelta(days=1)
        if deadline.weekday() < 5 and deadline not in holidays:
            working_days += 1
    return deadline


def latest_expected_reporting_period(as_of: date, market_holidays=()) -> date:
    """Latest period whose results and transcript window have normally passed."""

    candidates = [
        quarter_end
        for year in range(as_of.year - 3, as_of.year + 1)
        for quarter_end in _quarter_ends(year)
        if transcript_availability_deadline(quarter_end, market_holidays) <= as_of
    ]
    if not candidates:
        raise ValueError("could not determine an expected reporting period")
    return max(candidates)


def next_reporting_period_end(period_end: date) -> date:
    """Return the quarter end immediately following ``period_end``."""

    candidates = [
        quarter_end
        for year in range(period_end.year, period_end.year + 2)
        for quarter_end in _quarter_ends(year)
        if quarter_end > period_end
    ]
    return min(candidates)


def cycle_transition_confidence(
    period_end: date | None,
    as_of: date,
    taper_days: int = 20,
    market_holidays=(),
) -> tuple[float, date | None, int | None]:
    """Taper evidence before the next statutory cycle transition.

    Without this taper, every call for the preceding quarter goes from full
    eligibility to zero on one calendar day. Calls already assigned to the
    newer quarter naturally have a later transition and retain full weight.
    """

    if period_end is None:
        return 0.0, None, None
    transition = transcript_availability_deadline(
        next_reporting_period_end(period_end), market_holidays
    )
    days = (transition - as_of).days
    window = max(1, int(taper_days))
    confidence = max(0.0, min(1.0, days / window))
    return confidence, transition, days


def classify_transcript_evidence(
    call_date: str | date | None,
    as_of: date | None = None,
    max_age_days: int = 180,
    market_holidays=(),
) -> TranscriptEvidence:
    today = as_of or date.today()
    parsed = _parse_date(call_date)
    if parsed is None:
        return TranscriptEvidence(
            INVALID_DATE,
            None,
            None,
            latest_expected_reporting_period(today, market_holidays),
        )

    age_days = (today - parsed).days
    period_end = reporting_period_end_for_call(parsed)
    expected_period_end = latest_expected_reporting_period(today, market_holidays)
    if age_days < 0:
        return TranscriptEvidence(INVALID_DATE, age_days, period_end, expected_period_end)
    if age_days > max(0, int(max_age_days)):
        return TranscriptEvidence(EXPIRED, age_days, period_end, expected_period_end)
    if period_end < expected_period_end:
        return TranscriptEvidence(PRIOR_CYCLE, age_days, period_end, expected_period_end)
    return TranscriptEvidence(CURRENT_CYCLE, age_days, period_end, expected_period_end)


def _quarter_ends(year: int) -> tuple[date, date, date, date]:
    return date(year, 3, 31), date(year, 6, 30), date(year, 9, 30), date(year, 12, 31)


def _parse_date(value: str | date | None) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
