"""Compact encoding for per-symbol daily price series.

One row per symbol rather than one row per symbol-day. The access pattern is
"draw one stock's chart", which reads a whole series and never filters inside
it, so a row-per-day table would cost ~250-400 MB and an index scan to answer a
question a single row answers. Cross-sectional questions are already served by
`screener_history`.

Three arrays per symbol, each delta-encoded then written as compact JSON:

* ``session_deltas`` -- gaps in the shared trading calendar. A symbol that
  traded every session encodes as ``[start, 1, 1, 1, ...]``, which compresses to
  almost nothing, and a thin stock's real gaps survive instead of being
  forward-filled into a flat line that never happened.
* ``closes`` -- adjusted close in paise, so the values are integers and the
  deltas are small.
* ``volumes`` -- shares traded.

Delta encoding is what makes JSON competitive with binary here: a price series
is smooth, so successive differences are one or two digits where absolute values
are six. Measured on a representative 2116-point series, close plus volume is
~22 KB raw and ~10 KB over HTTP gzip, against ~16 KB raw for float32 binary --
and JSON needs no endianness contract between Python and the browser.

Paise are exact: `round(close * 100)` on a two-decimal quote loses nothing, and
integer deltas cannot accumulate the float drift that a running sum of decimals
would.
"""

from __future__ import annotations

import json
from datetime import date, datetime

PAISE = 100


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()


def encode_deltas(values) -> str:
    """Delta-encode integers and serialise them as compact JSON.

    The first element is absolute; every later element is its difference from
    the one before. An empty series encodes as ``"[]"`` rather than raising, so
    a symbol with no observations is still representable.
    """
    numbers = [int(value) for value in values]
    if not numbers:
        return "[]"
    out = [numbers[0]]
    previous = numbers[0]
    for number in numbers[1:]:
        out.append(number - previous)
        previous = number
    return json.dumps(out, separators=(",", ":"))


def decode_deltas(text) -> list[int]:
    """Inverse of :func:`encode_deltas`."""
    if not text:
        return []
    numbers = json.loads(text)
    if not numbers:
        return []
    out = [int(numbers[0])]
    for delta in numbers[1:]:
        out.append(out[-1] + int(delta))
    return out


def build_series(sessions, observations):
    """Encode one symbol's series against the shared calendar.

    ``sessions`` is the ascending calendar. ``observations`` maps a session date
    to ``(adjusted_close, volume)``. Sessions the symbol did not trade are
    simply absent -- they are recorded as a gap in ``session_deltas``, never
    invented.

    Returns ``None`` when nothing usable is left, so a caller can skip a symbol
    instead of publishing an empty chart.
    """
    index_of = {day: position for position, day in enumerate(sessions)}
    indices, closes, volumes = [], [], []
    for day in sorted(observations):
        position = index_of.get(_as_date(day))
        if position is None:
            # Traded on a date the calendar does not contain. Dropping it keeps
            # the three arrays index-aligned, which every consumer relies on.
            continue
        close, volume = observations[day]
        if close is None or close <= 0:
            continue
        indices.append(position)
        closes.append(round(float(close) * PAISE))
        volumes.append(int(volume) if volume and volume > 0 else 0)

    if len(indices) < 2:
        return None

    return {
        "session_deltas": encode_deltas(indices),
        "closes": encode_deltas(closes),
        "volumes": encode_deltas(volumes),
        "points": len(indices),
        "first_session": sessions[indices[0]].isoformat(),
        "last_session": sessions[indices[-1]].isoformat(),
    }


def decode_series(row, sessions):
    """Expand an encoded row back into ``[{date, close, volume}, ...]``.

    Exists so the Python side can assert a round trip against exactly what the
    browser will reconstruct; the dashboard has its own copy of this logic.
    """
    indices = decode_deltas(row["session_deltas"])
    closes = decode_deltas(row["closes"])
    volumes = decode_deltas(row["volumes"])
    if not (len(indices) == len(closes) == len(volumes)):
        raise ValueError(
            f"misaligned series: {len(indices)} sessions, {len(closes)} closes, "
            f"{len(volumes)} volumes"
        )
    return [
        {
            "date": sessions[position].isoformat(),
            "close": close / PAISE,
            "volume": volume,
        }
        for position, close, volume in zip(indices, closes, volumes)
    ]


def encode_calendar(sessions) -> str:
    """The shared session calendar, stored once rather than per symbol."""
    return json.dumps(
        [_as_date(day).isoformat() for day in sessions], separators=(",", ":")
    )


def decode_calendar(text):
    return [_as_date(value) for value in json.loads(text)]
