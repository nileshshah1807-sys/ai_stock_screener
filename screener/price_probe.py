"""Cheap pre-flight check that the vendor has finalised the expected session.

The full technical download takes about eleven minutes for the US universe and
the alignment guard in ``app.py`` only runs after it. When Yahoo has not yet
filled in the session's bars, every one of those minutes is wasted -- the run
fails with the same verdict a 20-symbol request would have reached.

The probe asks for a handful of liquid bellwethers (the market's
``safety_net_symbols``) and applies the same test the guard applies: the last
row with a usable close, adjusted close and volume must be the expected
completed session. It only ever *stops* a run on clear evidence. A probe that
cannot get an answer -- vendor error, too few symbols -- says nothing and the
full download proceeds, so it can make a failing run fail sooner but never
turn a healthy run into a failed one.
"""

import logging
import time

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Below this many usable answers the sample is too small to condemn a run.
MIN_PROBE_SYMBOLS = 5
MAX_PROBE_SYMBOLS = 20


def _last_usable_bar_date(frame, market_timezone, not_after=None):
    """Exchange-local date of the last row with close, adj close and volume.

    Rows dated after ``not_after`` are ignored. The expected session is the
    latest one that should be *complete*, so anything later is the live session
    -- Yahoo serves a partial bar for it all day -- and ``_select_completed_
    price_bars`` drops it from the real download too. Counting it here read a
    healthy vendor as one session ahead of the expectation and failed the run
    of 29 Sept 2026, dispatched mid-session, on 0/20 bellwethers.
    """
    if frame is None or frame.empty:
        return None
    columns = ["Close", "Adj Close", "Volume"]
    if not set(columns) <= set(frame.columns):
        return None
    usable = frame.dropna(subset=columns)
    if usable.empty:
        return None
    index = pd.DatetimeIndex(usable.index)
    if index.tz is not None:
        index = index.tz_convert(market_timezone)
    dates = [stamp.date() for stamp in index]
    if not_after is not None:
        dates = [d for d in dates if d <= not_after]
    return max(dates) if dates else None


def count_aligned(data, vendor_symbols, expected_session, market_timezone):
    """Return ``(aligned, answered)`` for a multi-symbol Yahoo daily frame.

    A symbol Yahoo returned no rows for at all is not counted as answered: an
    absent ticker is not evidence about the session.
    """
    aligned = 0
    answered = 0
    multi = isinstance(data.columns, pd.MultiIndex)
    present = set(data.columns.get_level_values(0)) if multi else set()
    for symbol in vendor_symbols:
        if multi:
            if symbol not in present:
                continue
            frame = data[symbol]
        elif len(vendor_symbols) == 1:
            frame = data
        else:
            continue
        if frame is None or frame.dropna(how="all").empty:
            continue
        answered += 1
        if (
            _last_usable_bar_date(frame, market_timezone, not_after=expected_session)
            == expected_session
        ):
            aligned += 1
    return aligned, answered


def _probe_once(download, symbols, expected_session, market_timezone):
    """One vendor request: ``(aligned, answered)``, or ``None`` if inconclusive."""
    try:
        data = download(
            " ".join(symbols),
            period="5d",
            group_by="ticker",
            progress=False,
            threads=True,
            auto_adjust=False,
        )
        aligned, answered = count_aligned(
            data, symbols, expected_session, market_timezone
        )
    except Exception as exc:  # the probe must never be the reason a run dies
        logger.warning("Price-bar probe inconclusive (%s); continuing", exc)
        return None

    if answered < MIN_PROBE_SYMBOLS:
        logger.warning(
            "Price-bar probe inconclusive: %d of %d symbols answered; continuing",
            answered,
            len(symbols),
        )
        return None
    return aligned, answered


def probe_expected_session(
    vendor_symbols,
    expected_session,
    market_timezone,
    min_alignment,
    *,
    downloader=None,
    wait_seconds=0,
    retry_interval_seconds=900,
    sleep=time.sleep,
    clock=time.monotonic,
):
    """Raise ``RuntimeError`` if the vendor plainly lacks the expected session.

    With ``wait_seconds`` the probe re-asks every ``retry_interval_seconds``
    until the session is there or the wait is spent, and only then raises.
    Yahoo finalises a US session anywhere from minutes to several hours after
    the close, and GitHub drops scheduled runs often enough that failing and
    leaving the retry to a later cron slot left the dashboard days stale (the
    US sessions of 28 and 29 Sept 2026 were each attempted once). Waiting
    inside the job needs only one slot to fire.

    Returns ``(aligned, answered)`` -- or ``None`` when the probe was
    inconclusive -- so the caller can log it.
    """
    symbols = list(vendor_symbols)[:MAX_PROBE_SYMBOLS]
    if len(symbols) < MIN_PROBE_SYMBOLS:
        logger.info("Price-bar probe skipped: only %d probe symbols", len(symbols))
        return None

    download = downloader or yf.download
    deadline = clock() + max(0.0, float(wait_seconds))
    while True:
        result = _probe_once(download, symbols, expected_session, market_timezone)
        if result is None:
            return None
        aligned, answered = result
        share = aligned / answered
        if share >= min_alignment:
            break
        remaining = deadline - clock()
        if remaining <= 0:
            raise RuntimeError(
                f"Price-bar probe: only {aligned}/{answered} ({share:.0%}) "
                f"bellwether symbols have a usable bar for the expected completed "
                f"session {expected_session} (minimum {min_alignment:.0%}). The "
                "vendor has probably not finalised the session yet; stopping "
                "before the full download. No scores, reports or dashboard rows "
                "were produced; the next scheduled slot will retry."
            )
        pause = min(float(retry_interval_seconds), remaining)
        logger.info(
            "Price-bar probe: %d/%d bellwethers on %s so far; the vendor has not "
            "finalised the session. Re-checking in %.0f min (%.0f min of waiting left).",
            aligned,
            answered,
            expected_session,
            pause / 60,
            remaining / 60,
        )
        sleep(pause)

    logger.info(
        "Price-bar probe passed: %d/%d bellwethers on %s (%.0f%%)",
        aligned,
        answered,
        expected_session,
        share * 100,
    )
    return aligned, answered
