"""Transaction costs, slippage and liquidity capacity.

`p0.md` §5 is blunt about why this exists: a ranking model can be statistically
correct and operationally unusable. A gross excess return of a few percent a year
disappears entirely under 40% monthly turnover, and the only way to know which
case you are in is to charge the strategy for its own trading.

Three separate things are modelled, and they are kept separate because they scale
differently:

* **Explicit fees** -- brokerage, STT, exchange charges, SEBI fees, GST, stamp
  duty, DP charges. Known, and a fixed fraction of value (except DP, which is
  per-scrip and therefore hits small positions hardest).
* **Slippage** -- half the bid-ask spread, paid on entry and exit regardless of
  order size.
* **Market impact** -- what the order itself does to the price, which grows with
  participation in the day's volume. This is the term that decides capacity.

Charges are **effective-dated**. `p0.md` warns against hard-coding today's rates
across a whole history, and Indian charges did move materially inside the test
window: STT on delivery, NSE transaction charges and stamp duty all changed. A
schedule with effective dates keeps a 2022 trade charged at 2022 rates.

Every rate here is a documented assumption, not a measurement. The run report
must show gross and net side by side so the reader can see how much of the result
the cost model is responsible for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BUY = "buy"
SELL = "sell"


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


@dataclass(frozen=True)
class ChargeSchedule:
    """Charges in force from ``effective_from`` until the next schedule starts.

    Rates are fractions of traded value, not percentages or basis points, so the
    arithmetic downstream needs no scaling constants.
    """

    effective_from: date
    brokerage_rate: float = 0.0
    stt_buy_rate: float = 0.001
    stt_sell_rate: float = 0.001
    exchange_txn_rate: float = 0.0000297
    sebi_rate: float = 0.000001
    stamp_duty_buy_rate: float = 0.00015
    gst_rate: float = 0.18
    dp_charge_per_sell: float = 15.93
    label: str = ""


# Delivery-segment equity charges for the backtest window.
#
# Brokerage defaults to zero: the discount brokers that dominate Indian retail
# delivery charge nothing for it, and assuming a percentage brokerage would
# overstate cost for the most likely execution venue. Override for a full-service
# assumption and report which was used.
#
# Stamp duty applies on the buy leg only. DP charges are per-scrip on the sell
# leg, which is why they are modelled as a flat amount rather than a rate -- they
# make small positions disproportionately expensive, and that is a real capacity
# constraint rather than a rounding detail.
DEFAULT_SCHEDULES = (
    ChargeSchedule(
        effective_from=date(2020, 1, 1),
        exchange_txn_rate=0.0000325,
        label="pre-2023 NSE transaction charge",
    ),
    ChargeSchedule(
        effective_from=date(2023, 11, 1),
        exchange_txn_rate=0.0000322,
        label="NSE charge revision Nov-2023",
    ),
    ChargeSchedule(
        effective_from=date(2024, 10, 1),
        exchange_txn_rate=0.0000297,
        label="NSE charge revision Oct-2024",
    ),
)


class CostModel:
    """Explicit fees plus slippage and market impact for one order."""

    def __init__(
        self,
        schedules=DEFAULT_SCHEDULES,
        *,
        half_spread_rate=0.0010,
        impact_coefficient=0.10,
        max_participation_rate=0.10,
    ):
        if not schedules:
            raise ValueError("at least one ChargeSchedule is required")
        self.schedules = tuple(
            sorted(schedules, key=lambda schedule: schedule.effective_from)
        )
        self.half_spread_rate = float(half_spread_rate)
        self.impact_coefficient = float(impact_coefficient)
        self.max_participation_rate = float(max_participation_rate)

    def schedule_for(self, as_of):
        """The schedule in force on ``as_of``.

        Dates before the first schedule use the earliest one rather than failing;
        the alternative is a silent zero-cost trade, which is worse.
        """
        as_of = _as_date(as_of)
        chosen = self.schedules[0]
        for schedule in self.schedules:
            if schedule.effective_from <= as_of:
                chosen = schedule
            else:
                break
        return chosen

    def explicit_fees(self, value, side, as_of):
        """Statutory and broker charges on one leg, in rupees."""
        value = abs(float(value))
        if value <= 0:
            return 0.0
        schedule = self.schedule_for(as_of)
        side = str(side).lower()

        brokerage = value * schedule.brokerage_rate
        exchange = value * schedule.exchange_txn_rate
        sebi = value * schedule.sebi_rate
        # GST applies to the service charges, not to STT or stamp duty.
        gst = (brokerage + exchange + sebi) * schedule.gst_rate

        if side == BUY:
            stt = value * schedule.stt_buy_rate
            stamp = value * schedule.stamp_duty_buy_rate
            dp = 0.0
        else:
            stt = value * schedule.stt_sell_rate
            stamp = 0.0
            dp = schedule.dp_charge_per_sell

        return brokerage + exchange + sebi + gst + stt + stamp + dp

    def participation_rate(self, value, median_daily_turnover):
        """Order value as a fraction of the median day's traded value."""
        turnover = float(median_daily_turnover or 0.0)
        if turnover <= 0:
            return None
        return abs(float(value)) / turnover

    def impact_cost(self, value, median_daily_turnover):
        """Market impact in rupees, from a square-root participation model.

        ``impact_rate = coefficient * sqrt(participation)``. The square root is the
        conventional shape: impact grows with size but sub-linearly, so doubling an
        order does not double the damage per rupee.

        Returns None when turnover is unknown -- an unmeasurable impact must not be
        silently charged as zero, because zero is the most favourable possible
        assumption for exactly the illiquid names where impact matters most.
        """
        participation = self.participation_rate(value, median_daily_turnover)
        if participation is None:
            return None
        return abs(float(value)) * self.impact_coefficient * np.sqrt(participation)

    def slippage_cost(self, value):
        """Half-spread cost, paid on every leg regardless of size."""
        return abs(float(value)) * self.half_spread_rate

    def total_cost(self, value, side, as_of, median_daily_turnover=None):
        """Full one-leg cost breakdown in rupees.

        ``impact`` is None when turnover is unknown, and ``total`` is then also
        None: an unpriceable order must surface rather than appear cheap.
        """
        fees = self.explicit_fees(value, side, as_of)
        slippage = self.slippage_cost(value)
        impact = self.impact_cost(value, median_daily_turnover)
        total = None if impact is None else fees + slippage + impact
        return {
            "value": abs(float(value)),
            "side": str(side).lower(),
            "explicit_fees": round(fees, 4),
            "slippage": round(slippage, 4),
            "impact": None if impact is None else round(impact, 4),
            "total": None if total is None else round(total, 4),
            "cost_rate": (
                None
                if total is None or value == 0
                else round(total / abs(float(value)), 8)
            ),
            "schedule": self.schedule_for(as_of).label,
        }

    def build_days(self, value, median_daily_turnover):
        """Sessions needed to build a position within the participation limit."""
        turnover = float(median_daily_turnover or 0.0)
        if turnover <= 0 or self.max_participation_rate <= 0:
            return None
        daily_capacity = turnover * self.max_participation_rate
        if daily_capacity <= 0:
            return None
        return float(abs(float(value)) / daily_capacity)

    def violates_capacity(self, value, median_daily_turnover):
        """Whether a single-session fill would exceed the participation limit."""
        participation = self.participation_rate(value, median_daily_turnover)
        if participation is None:
            return True
        return participation > self.max_participation_rate


def round_trip_cost_rate(model, value, entry_date, exit_date, median_daily_turnover):
    """Combined entry-plus-exit cost as a fraction of the position value.

    This is the number that gets subtracted from a gross forward return, so it
    charges both legs. Returns None when either leg is unpriceable.
    """
    entry = model.total_cost(value, BUY, entry_date, median_daily_turnover)
    exit_leg = model.total_cost(value, SELL, exit_date, median_daily_turnover)
    if entry["total"] is None or exit_leg["total"] is None:
        return None
    return (entry["total"] + exit_leg["total"]) / abs(float(value))


def apply_costs(frame, model, *, value_per_position, return_column, entry_column,
                exit_column, turnover_column="Median_Turnover_INR"):
    """Attach per-position cost and net-return columns to a fill frame.

    Gross and net are both retained. Reporting only net would hide how much of
    the result the cost assumptions drive, which `p0.md` §5 asks to be shown
    separately.
    """
    if frame is None or len(frame) == 0:
        return frame
    out = frame.copy()
    rates = []
    for record in out.to_dict("records"):
        entry_date = record.get(entry_column)
        exit_date = record.get(exit_column)
        turnover = record.get(turnover_column)
        if not entry_date or not exit_date:
            rates.append(None)
            continue
        rates.append(
            round_trip_cost_rate(
                model, value_per_position, entry_date, exit_date, turnover
            )
        )
    out["Cost_Rate"] = rates
    gross = pd.to_numeric(out[return_column], errors="coerce")
    cost_pct = pd.Series(rates, index=out.index, dtype="float64") * 100.0
    out["Net_Return_Pct"] = gross - cost_pct
    return out


def capacity_report(model, frame, portfolio_values, *,
                    turnover_column="Median_Turnover_INR", positions=20):
    """Per-portfolio-size capacity summary, per `p0.md` §5.

    Answers how much money the strategy can deploy before its own trading damages
    the result -- reported per size rather than as one number, because capacity is
    a property of the pair (strategy, size).
    """
    turnovers = pd.to_numeric(
        frame.get(turnover_column, pd.Series(dtype=float)), errors="coerce"
    ).dropna()
    rows = []
    for portfolio_value in portfolio_values:
        per_position = float(portfolio_value) / max(1, int(positions))
        if turnovers.empty:
            rows.append(
                {
                    "portfolio_value": float(portfolio_value),
                    "value_per_position": round(per_position, 2),
                    "names": 0,
                    "median_build_days": None,
                    "max_build_days": None,
                    "mean_impact_rate": None,
                    "capacity_violation_share": None,
                }
            )
            continue
        build = [model.build_days(per_position, turnover) for turnover in turnovers]
        build = [value for value in build if value is not None]
        impacts = [
            model.impact_cost(per_position, turnover) / per_position
            for turnover in turnovers
            if model.impact_cost(per_position, turnover) is not None
        ]
        violations = [
            model.violates_capacity(per_position, turnover) for turnover in turnovers
        ]
        rows.append(
            {
                "portfolio_value": float(portfolio_value),
                "value_per_position": round(per_position, 2),
                "names": int(len(turnovers)),
                "median_build_days": round(float(np.median(build)), 3) if build else None,
                "max_build_days": round(float(np.max(build)), 3) if build else None,
                "mean_impact_rate": round(float(np.mean(impacts)), 6) if impacts else None,
                "capacity_violation_share": round(
                    float(np.mean(violations)), 4
                ) if violations else None,
            }
        )
    return pd.DataFrame(rows)
