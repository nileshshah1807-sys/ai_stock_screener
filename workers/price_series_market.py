"""Vendor-sourced price observations for markets with no point-in-time archive.

``price_series_publisher`` builds the NSE chart from the bhavcopy archive under
``backtest/``, which is corporate-action adjusted, covers delisted securities
and is the same series the model scored on. No equivalent archive exists for
the US, and building one would mean reproducing the security master, the
corporate-action ledger and the day-file store against a different exchange --
for a reading aid rather than for the product.

So the US chart is sourced from yfinance, which is already this project's
price vendor. That is a weaker provenance story than the NSE archive, and the
trade is stated rather than hidden:

* **Adjustment.** Yahoo's ``Close`` is adjusted for splits but not dividends,
  which is exactly the basis the NSE archive publishes -- ``adjust_panel``
  applies ratio actions only, and the comment in ``tools.publish_price_series``
  notes dividends do not rescale this chart. ``Adj Close`` would additionally
  back out dividends and put the chart on a different basis from
  ``screener_history.current_price``, which the stock page appends as the
  chart's tail. Verified against NVDA's 2024 ten-for-one split: ``Close``
  carries no cliff across it.
* **Delisted securities.** The archive has them; Yahoo largely does not. A
  stock that leaves the universe keeps whatever series was last published and
  simply stops extending, rather than acquiring a fabricated one.
* **Restatement.** Yahoo back-adjusts silently, so a split restates a symbol's
  whole history with no event to key a targeted rebuild off. The US rebuild is
  therefore always a full one; at ~2,190 sessions across ~1,500 symbols that
  costs a few minutes, where the NSE archive's ``--since`` path exists because
  re-reading 2,100 day-files does not.

The encoding, row building, shrink guard and publish path are all shared with
the NSE producer. Only the source of observations differs.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime

import pandas as pd
import yfinance as yf

from screener.markets import bare_symbol, ticker_for

logger = logging.getLogger(__name__)

# Matches the NSE archive's own start, so the two markets' charts cover
# comparable windows.
DEFAULT_START = "2018-01-01"

# The screener downloads in thirties; measured at ~2.7s for thirty symbols over
# eight years, so the whole S&P 1500 is a few minutes. Kept the same so both
# paths present the same shape of load to the vendor.
BATCH_SIZE = 30
BATCH_PAUSE_SECONDS = 1.0


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def trading_calendar(profile, start=DEFAULT_START, end=None) -> list[date]:
    """Sessions for a market, taken from its benchmark index.

    The index trades on exactly the days the exchange is open, so its history
    is the session calendar -- including every holiday, without needing one
    hardcoded. Deriving the calendar from the union of the universe's own
    observations would instead inherit any single symbol's bad print as a
    session nobody else traded.
    """
    symbol = profile.benchmark_symbol
    frame = yf.download(
        symbol, start=start, end=end, auto_adjust=False, progress=False, threads=False
    )
    if frame is None or frame.empty:
        raise RuntimeError(
            f"Benchmark {symbol} returned no history; cannot build a {profile.code} "
            "session calendar"
        )
    sessions = sorted({_as_date(stamp) for stamp in frame.index})
    logger.info(
        "%s calendar from %s: %d sessions, %s -> %s",
        profile.code,
        symbol,
        len(sessions),
        sessions[0],
        sessions[-1],
    )
    return sessions


def _frame_for(data, ticker):
    """Pull one ticker's frame out of a grouped yfinance download."""
    if data is None or getattr(data, "empty", True):
        return None
    if isinstance(data.columns, pd.MultiIndex):
        if ticker not in data.columns.get_level_values(0):
            return None
        return data[ticker]
    return data


def collect_observations(
    symbols,
    profile,
    *,
    start=DEFAULT_START,
    end=None,
    batch_size=BATCH_SIZE,
    pause_seconds=BATCH_PAUSE_SECONDS,
    downloader=None,
):
    """Return ``{symbol: {date: (close, volume)}}`` for a market's universe.

    Keyed by symbol rather than by a security id: Yahoo has no stable identifier
    behind the ticker, so the reuse a security master would resolve is simply
    not visible here. ``build_rows`` takes an identity symbol map for this path.

    ``downloader`` is injectable so the tests never reach the network.
    """
    fetch = downloader or (
        lambda tickers: yf.download(
            " ".join(tickers),
            start=start,
            end=end,
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    )

    wanted = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    observations: dict[str, dict[date, tuple[float, int]]] = {}
    missing: list[str] = []

    total_batches = max(1, (len(wanted) - 1) // batch_size + 1)
    for index in range(0, len(wanted), batch_size):
        batch = wanted[index : index + batch_size]
        number = index // batch_size + 1
        if number > 1 and pause_seconds:
            time.sleep(pause_seconds)
        if number == 1 or number % 10 == 0:
            logger.info(
                "Price history batch %d/%d (%d symbols collected)",
                number,
                total_batches,
                len(observations),
            )

        tickers = [ticker_for(symbol, profile) for symbol in batch]
        try:
            data = fetch(tickers)
        except Exception as exc:  # noqa: BLE001 - one bad batch must not end the run
            logger.warning("Price history batch %d failed: %s", number, exc)
            missing.extend(batch)
            continue

        for ticker in tickers:
            symbol = bare_symbol(ticker, profile)
            frame = _frame_for(data, ticker)
            if frame is None or frame.empty or "Close" not in frame.columns:
                missing.append(symbol)
                continue

            # Yahoo's Close is split-adjusted and dividend-unadjusted, which is
            # the basis this chart publishes. See the module docstring.
            closes = pd.to_numeric(frame["Close"], errors="coerce")
            volumes = pd.to_numeric(frame.get("Volume"), errors="coerce")

            points: dict[date, tuple[float, int]] = {}
            for stamp, close in closes.items():
                if close is None or close != close or close <= 0:  # NaN-safe
                    continue
                volume = 0
                if volumes is not None:
                    raw = volumes.get(stamp)
                    if raw is not None and raw == raw and raw > 0:
                        volume = int(raw)
                points[_as_date(stamp)] = (float(close), volume)

            if points:
                observations[symbol] = points
            else:
                missing.append(symbol)

    if missing:
        logger.info(
            "No usable price history for %d symbol(s): %s",
            len(missing),
            ", ".join(sorted(missing)[:10]) + (" ..." if len(missing) > 10 else ""),
        )
    logger.info("Collected price history for %d/%d symbols", len(observations), len(wanted))
    return observations


def identity_symbols(observations) -> dict[str, str]:
    """Symbol map for ``build_rows`` when observations are already per-symbol."""
    return {symbol: symbol for symbol in observations}
