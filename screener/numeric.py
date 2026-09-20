"""Explicit numerical conventions shared by model stages."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd


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


def safe_float(val, default=None):
    """Coerce a possibly-missing vendor value to float, or return ``default``.

    Vendor rows arrive with ``None``, ``NaN``, empty strings and occasionally
    text in numeric fields, and a scorer must treat all of them as "not
    reported" rather than raise. Lives here rather than on the scorer so the
    scoring modules can share it without importing each other.
    """

    try:
        if val is None or pd.isna(val):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default
