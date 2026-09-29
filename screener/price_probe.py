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

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Below this many usable answers the sample is too small to condemn a run.
MIN_PROBE_SYMBOLS = 5
MAX_PROBE_SYMBOLS = 20


def _last_usable_bar_date(frame, market_timezone):
    """Exchange-local date of the last row with close, adj close and volume."""
    if frame is None or frame.empty:
        return None
    columns = ["Close", "Adj Close", "Volume"]
    if not set(columns) <= set(frame.columns):
        return None
    usable = frame.dropna(subset=columns)
    if usable.empty:
        return None
    last = pd.Timestamp(usable.index[-1])
    if last.tzinfo is not None:
        last = last.tz_convert(market_timezone)
    return last.date()


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
        if _last_usable_bar_date(frame, market_timezone) == expected_session:
            aligned += 1
    return aligned, answered


def probe_expected_session(
    vendor_symbols,
    expected_session,
    market_timezone,
    min_alignment,
    *,
    downloader=None,
):
    """Raise ``RuntimeError`` if the vendor plainly lacks the expected session.

    Returns ``(aligned, answered)`` -- or ``None`` when the probe was
    inconclusive -- so the caller can log it.
    """
    symbols = list(vendor_symbols)[:MAX_PROBE_SYMBOLS]
    if len(symbols) < MIN_PROBE_SYMBOLS:
        logger.info("Price-bar probe skipped: only %d probe symbols", len(symbols))
        return None

    download = downloader or yf.download
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

    share = aligned / answered
    if share < min_alignment:
        raise RuntimeError(
            f"Price-bar probe: only {aligned}/{answered} ({share:.0%}) bellwether "
            f"symbols have a usable bar for the expected completed session "
            f"{expected_session} (minimum {min_alignment:.0%}). The vendor has "
            "probably not finalised the session yet; stopping before the full "
            "download. No scores, reports or dashboard rows were produced; the "
            "next scheduled slot will retry."
        )

    logger.info(
        "Price-bar probe passed: %d/%d bellwethers on %s (%.0f%%)",
        aligned,
        answered,
        expected_session,
        share * 100,
    )
    return aligned, answered
