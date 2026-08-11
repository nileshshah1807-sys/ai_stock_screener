"""Explicit numerical conventions shared by model stages."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import math


def round_half_up(value, places=2):
    """Round a finite scalar using decimal half-up semantics.

    Python scalars, NumPy scalars, and pandas operations otherwise take
    subtly different paths at exact half-cent boundaries. Converting through
    the scalar's decimal string makes exported score rounding version-stable
    and documents the convention used by the model.
    """

    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return number
    quantum = Decimal(1).scaleb(-int(places))
    return float(
        Decimal(str(number)).quantize(quantum, rounding=ROUND_HALF_UP)
    )


def round_series_half_up(series, places=2):
    """Apply :func:`round_half_up` to a pandas-compatible Series."""

    return series.map(lambda value: round_half_up(value, places))
