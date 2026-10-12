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


def collect_raw_observations(store, sessions, master):
    """Walk the archive once, returning per-security raw bars and symbols.

    One pass over the day-files rather than one pass per security: the archive
    is ~2,100 gzipped files, and re-reading them per symbol would be thousands
    of times more I/O for the same result.

    Each bar is ``(close, volume, open, prev_close)``, unadjusted. The open and
    the exchange's own previous close are what ``reconcile_with_prices`` reads
    a change of basis from.
    """
    bars: dict[str, dict[date, tuple]] = {}
    latest_symbol: dict[str, tuple[date, str]] = {}

    for day in sessions:
        frame = store.load_day(day)
        if frame is None or frame.empty:
            continue
        isins = frame["ISIN"].astype(str).str.upper().tolist()
        closes = frame["Close"].tolist() if "Close" in frame.columns else None
        opens = frame["Open"].tolist() if "Open" in frame.columns else None
        volumes = frame["Volume"].tolist() if "Volume" in frame.columns else None
        symbols = frame["Symbol"].tolist() if "Symbol" in frame.columns else None
        previous = (
            frame["Prev_Close"].tolist() if "Prev_Close" in frame.columns else None
        )
        for position, isin in enumerate(isins):
            close = closes[position] if closes is not None else None
            if close is None or close != close or close <= 0:  # NaN-safe
                continue
            key = master.security_id_for_isin(isin) or isin
            volume = 0
            if volumes is not None:
                raw = volumes[position]
                volume = int(raw) if raw == raw and raw > 0 else 0
            opened = opens[position] if opens is not None else None
            if opened is None or opened != opened or opened <= 0:
                opened = None
            prior = previous[position] if previous is not None else None
            if prior is None or prior != prior or prior <= 0:
                prior = None
            bars.setdefault(key, {})[day] = (float(close), volume, opened, prior)
            if symbols is not None:
                symbol = str(symbols[position]).strip().upper()
                if symbol and latest_symbol.get(key, (date.min, ""))[0] < day:
                    latest_symbol[key] = (day, symbol)

    return bars, {key: value[1] for key, value in latest_symbol.items()}


def adjust_observations(bars, adjustment_table):
    """Back-adjusted ``{security: {day: (close, volume)}}`` from raw bars."""
    observations = {}
    for key, by_day in bars.items():
        if adjustment_table is None:
            observations[key] = {day: bar[:2] for day, bar in by_day.items()}
            continue
        observations[key] = {
            day: (bar[0] / adjustment_table.price_factor(key, day), bar[1])
            for day, bar in by_day.items()
        }
    return observations


def collect_observations(store, sessions, master, adjustment_table):
    """Adjusted observations and symbols, straight from the ledger's factors."""
    bars, symbols = collect_raw_observations(store, sessions, master)
    return adjust_observations(bars, adjustment_table), symbols


# A security can stay suspended for some sessions around an ex-date; the action
# is read off its first bar on or after the ex-date, against its last before.
EX_DATE_SESSION_SEARCH = 15
# Past this many sessions without a bar the two closes are not one overnight
# apart in any useful sense, and the ledger is left to stand.
MAX_SESSIONS_BETWEEN_BARS = 30


def reconcile_with_prices(bars, sessions, actions, adjustment_table, max_open_gap):
    """Check the chart's adjustment table against what each ex-date bar did.

    The ledger is the exchange's action feed, and a chart drawn straight from
    it is wrong in three ways the price panel can settle:

    * A demerger or a rights issue carries no ratio, so its ex-date price cut
      would be drawn as a crash the holders never took. It is priced from the
      security's own bars: last close before over first open after.
    * A split or bonus whose stated ratio the price did not follow -- the feed
      dated it wrongly, or left out a second action on the same day -- would
      draw a jump that never happened. Where the bars disagree with the ratio
      by more than the opening cap the bars win: the gap they show is applied
      if it is one, and nothing is applied if it is not.
    * The feed does not report every change in the unit (fund unit splits are
      not in it at all). An open beyond the opening cap that no ledger factor
      explains was not traded to, and is applied as found
      (``backtest.corporate_actions.open_gap_factor``).

    ``max_open_gap`` is the market's opening cap as a ratio
    (``MarketProfile.max_open_gap``): how far an ex-date gap may sit from the
    ledger's ratio and still confirm it, and how large an unexplained gap has
    to be to count as one.

    The gap is measured from the last close this archive holds, because the
    exchange restates the day-file's ``Prev_Close`` for some actions and not
    for others. The one exception is a ``Prev_Close`` within the opening cap of
    that close: then it is a real close, possibly of a special session the
    archive does not hold, and the gap is measured from it instead. A security
    with no bars near the ex-date keeps the ledger as it stands.

    Returns ``(symbol, session, outcome, factor)`` per change made or
    attempted, for the run log.
    """
    import math
    from bisect import bisect_left

    from backtest.corporate_actions import (
        ACTION_DEMERGER,
        ACTION_RIGHTS,
        RATIO_ACTIONS,
        _parse_ex_date,
        ex_date_price_factor,
        open_gap_factor,
    )

    report = []
    position = {day: index for index, day in enumerate(sessions)}
    tolerance = math.log(max_open_gap)

    # A ratio action the parser could not read is priced from the bars as well.
    priced_from_bars = {ACTION_DEMERGER, ACTION_RIGHTS} | set(RATIO_ACTIONS)
    events = {}
    if actions is not None and len(actions) and "Action_Type" in actions.columns:
        for record in actions.to_dict("records"):
            if record.get("Action_Type") not in priced_from_bars:
                continue
            ex_date = _parse_ex_date(record.get("Ex_Date"))
            if ex_date is None or not sessions[0] <= ex_date <= sessions[-1]:
                continue
            key = adjustment_table.key_for(
                record.get("ISIN"), record.get("Symbol"), ex_date
            )
            if key is not None:
                symbol = str(record.get("Symbol") or "").strip().upper()
                events.setdefault(key, {}).setdefault(ex_date, symbol)

    def close_before(days, by_day, index):
        """The close ``days[index]`` opened against, or ``None``."""
        if index <= 0:
            return None
        day, before = days[index], days[index - 1]
        if position[day] - position[before] > MAX_SESSIONS_BETWEEN_BARS:
            return None
        held, quoted = by_day[before][0], by_day[day][3]
        if quoted and max(held / quoted, quoted / held) <= max_open_gap:
            return quoted
        return held

    def gap_at(days, by_day, index):
        """The close before ``days[index]`` over its open, or ``None``."""
        reference, opened = close_before(days, by_day, index), by_day[days[index]][2]
        return reference / opened if reference and opened else None

    for key, by_day in bars.items():
        days = sorted(day for day in by_day if day in position)
        if len(days) < 2:
            for ex_date, symbol in events.get(key, {}).items():
                if adjustment_table.ratio_factor(key, ex_date) is None:
                    report.append((symbol, ex_date, "unpriced", None))
            continue
        settled = set()

        for ex_date, symbol in sorted(events.get(key, {}).items()):
            index = bisect_left(days, ex_date)
            stated = adjustment_table.ratio_factor(key, ex_date)
            near = (
                index < len(days)
                and position[days[index]] - bisect_left(sessions, ex_date)
                <= EX_DATE_SESSION_SEARCH
            )
            observed = gap_at(days, by_day, index) if near else None
            if observed is None:
                if stated is None:
                    report.append((symbol, ex_date, "unpriced", None))
                continue
            day = days[index]
            settled.add(day)
            if stated is None:
                factor = ex_date_price_factor(
                    close_before(days, by_day, index), by_day[day][2]
                )
                if factor is not None:
                    adjustment_table.add_derived_factor(key, day, factor)
                    report.append((symbol, day, "priced", factor))
            elif abs(math.log(observed / stated)) > tolerance:
                # The ratio is not what the price did. A gap of its own is
                # applied as found; none means the action did not land here.
                material = abs(math.log(observed)) > tolerance
                adjustment_table.replace_factor(
                    key, ex_date, observed if material else None, effective=day
                )
                if not material:
                    settled.discard(day)
                report.append(
                    (symbol, day, "repriced" if material else "dropped", observed)
                )

        for index in range(1, len(days)):
            day = days[index]
            if day in settled:
                continue
            factor = open_gap_factor(
                close_before(days, by_day, index),
                by_day[day][2],
                by_day[day][0],
                max_open_gap,
            )
            if factor is None or adjustment_table.ratio_factor(key, day) is not None:
                continue
            adjustment_table.add_derived_factor(key, day, factor)
            report.append((key, day, "open_gap", factor))

    for key, by_ex_date in events.items():
        if key in bars:
            continue
        # The action names a security the archive holds no bars for at all.
        for ex_date, symbol in by_ex_date.items():
            if adjustment_table.ratio_factor(key, ex_date) is None:
                report.append((symbol, ex_date, "unpriced", None))

    for outcome, level in (
        ("priced", logging.INFO),
        ("open_gap", logging.INFO),
        ("repriced", logging.WARNING),
        ("dropped", logging.WARNING),
        ("unpriced", logging.WARNING),
    ):
        entries = sorted(
            (entry for entry in report if entry[2] == outcome),
            key=lambda entry: (entry[1], entry[0]),
        )
        if entries:
            logger.log(
                level,
                "Ex-date reconciliation, %s: %d (%s)",
                outcome,
                len(entries),
                ", ".join(
                    f"{name} {day.isoformat()}" + (f" /{factor:.3f}" if factor else "")
                    for name, day, _, factor in entries
                ),
            )
    return report


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


class PublishRefused(RuntimeError):
    """Raised when publishing would replace good data with less of it."""


def check_not_shrinking(repository, sessions, rows, *, tolerance=0.9):
    """Refuse to publish a series materially smaller than the one live.

    The archive is resumable and cached, so a cold or evicted cache leaves it
    nearly empty rather than failing. Publishing from that state would overwrite
    2,116 sessions with whatever few were fetched, and every chart would quietly
    lose its history -- an upsert gives no hint that it happened.

    A modest shrink is legitimate (a symbol delisting, a trimmed window), so the
    guard trips only below ``tolerance`` of what is already published.
    """
    published = None
    try:
        published = repository.published_calendar_size()
    except Exception as error:  # noqa: BLE001 - never block on a diagnostic read
        logger.warning("Could not read the published calendar size: %s", error)
        return

    if not published:
        return
    if len(sessions) >= published * tolerance:
        return

    raise PublishRefused(
        f"Refusing to publish {len(sessions)} sessions over the {published} "
        f"already live. The archive is probably cold or partially restored; "
        f"run tools.backfill_backtest_archive until it is complete, or pass "
        f"--allow-shrink if the smaller window is intended."
    )


def publish(repository, sessions, rows, *, dry_run=False, allow_shrink=False):
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

    if not allow_shrink:
        check_not_shrinking(repository, sessions, rows)

    repository.upsert_price_calendar(calendar_row(sessions))
    written = repository.upsert_price_series(rows)
    logger.info("Published %d price series", written)
    return written
