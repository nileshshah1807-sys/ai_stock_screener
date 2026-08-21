"""Build per-symbol price series from the point-in-time archive and publish them.

The archive under `backtest/` is the only price source in this project that is
corporate-action adjusted, covers delisted securities, and is the *same* series
the model scored on. A chart drawn from anywhere else can disagree with the
screener beside it around a split or a bonus issue, which for a tool whose
entire claim is auditability is a defect rather than a cosmetic difference.

Symbols, not security IDs. The archive keys on `Security_ID` because a symbol is
reused and renamed over a decade, but the dashboard and every reader address a
stock by its current ticker. Each security is therefore published under the last
symbol it traded under, and a symbol later reused by a different company resolves
to whichever security used it most recently -- stated here because it is a real
ambiguity, not an oversight.
"""

from __future__ import annotations

import logging
from datetime import date

from .price_series import build_series, encode_calendar

logger = logging.getLogger(__name__)

# Below this a chart is a couple of dots. Publishing it wastes a row and renders
# something misleading.
MIN_POINTS = 30


def collect_observations(store, sessions, master, adjustment_table):
    """Walk the archive once, returning per-security observations and symbols.

    One pass over the day-files rather than one pass per security: the archive
    is ~2,100 gzipped files, and re-reading them per symbol would be thousands
    of times more I/O for the same result.
    """
    from backtest.corporate_actions import adjust_panel

    observations: dict[str, dict[date, tuple[float, int]]] = {}
    latest_symbol: dict[str, tuple[date, str]] = {}

    for day in sessions:
        frame = store.load_day(day)
        if frame is None or frame.empty:
            continue
        frame = frame.copy()
        frame["Security_ID"] = [
            master.security_id_for_isin(isin) or str(isin)
            for isin in frame["ISIN"].astype(str)
        ]
        if adjustment_table is not None:
            frame = adjust_panel(frame, adjustment_table, key_column="Security_ID")

        closes = frame.get("Adj_Close", frame.get("Close"))
        volumes = frame.get("Volume")
        symbols = frame.get("Symbol")
        for position, key in enumerate(frame["Security_ID"].astype(str)):
            close = closes.iloc[position] if closes is not None else None
            if close is None or close != close or close <= 0:  # NaN-safe
                continue
            volume = 0
            if volumes is not None:
                raw = volumes.iloc[position]
                volume = int(raw) if raw == raw and raw > 0 else 0
            observations.setdefault(key, {})[day] = (float(close), volume)
            if symbols is not None:
                symbol = str(symbols.iloc[position]).strip().upper()
                if symbol and latest_symbol.get(key, (date.min, ""))[0] < day:
                    latest_symbol[key] = (day, symbol)

    return observations, {key: value[1] for key, value in latest_symbol.items()}


def build_rows(sessions, observations, symbols, *, min_points=MIN_POINTS):
    """Encode one row per symbol, newest security winning a reused ticker."""
    by_symbol: dict[str, dict] = {}
    skipped_short = 0

    for security_id, points in observations.items():
        symbol = symbols.get(security_id)
        if not symbol:
            continue
        row = build_series(sessions, points)
        if row is None or row["points"] < min_points:
            skipped_short += 1
            continue
        existing = by_symbol.get(symbol)
        # A ticker reused by a different company: keep whichever traded under it
        # most recently, which is the one a reader typing that ticker means.
        if existing is None or existing["last_session"] < row["last_session"]:
            by_symbol[symbol] = {**row, "symbol": symbol}

    if skipped_short:
        logger.info(
            "Skipped %d securities with fewer than %d observations",
            skipped_short,
            min_points,
        )
    return sorted(by_symbol.values(), key=lambda row: row["symbol"])


def calendar_row(sessions):
    return {
        "sessions": encode_calendar(sessions),
        "session_count": len(sessions),
        "first_session": sessions[0].isoformat(),
        "last_session": sessions[-1].isoformat(),
    }


def publish(repository, sessions, rows, *, dry_run=False):
    """Write the calendar and every series row.

    The calendar goes first. A series indexes into it, so publishing series
    against a calendar the reader does not yet have would draw every point at
    the wrong date for as long as the gap lasted.
    """
    payload_bytes = sum(
        len(row["session_deltas"]) + len(row["closes"]) + len(row["volumes"])
        for row in rows
    )
    logger.info(
        "Prepared %d symbols, %d sessions, %.1f MB encoded (pre-compression)",
        len(rows),
        len(sessions),
        payload_bytes / 1e6,
    )
    if dry_run:
        logger.info("Dry run: nothing written")
        return 0

    repository.upsert_price_calendar(calendar_row(sessions))
    written = repository.upsert_price_series(rows)
    logger.info("Published %d price series", written)
    return written
