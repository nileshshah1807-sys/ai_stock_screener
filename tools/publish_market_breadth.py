"""Build and publish the Market page's breadth history and headline indices.

    python -m tools.publish_market_breadth --dry-run
    python -m tools.publish_market_breadth
    python -m tools.publish_market_breadth --market US

Closes come from the same sources as the stock-page chart: the adjusted NSE
archive for NSE, yfinance for the US. The universe and its sector/industry
classification come from the latest published snapshot, so the page covers the
stocks the screener rates today. See `workers/market_breadth.py` for every
definition.

Everything here is read from the vendor or the archive and written once; the
only Supabase read is the latest snapshot's classification. Reading the
published price series back instead would cost ~50 MB of egress a day.

Apply `storage/market_breadth_schema.sql` once before the first real run.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.publish_price_series import DEFAULT_ROOT, load_env_file  # noqa: E402

logger = logging.getLogger("publish_market_breadth")

DEFAULT_START = "2018-01-01"

# NSE's own end-of-day file for every index it computes, one file per session.
# A missing day is a 404: a holiday, or a session NSE has not published yet.
NSE_INDEX_CLOSE_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{day:%d%m%Y}.csv"
NSE_INDEX_LOOKBACK_DAYS = 10
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch_nse_index_closes(labels, days, *, get=None):
    """``{label: {date: close}}`` read from NSE's daily index files.

    ``labels`` are NSE index names, which are the dashboard labels. A day that
    is not a weekday, is not published, or fails to download is skipped: the
    caller still has Yahoo's history and the freshness retry.
    """
    import csv
    import io
    from datetime import datetime

    if get is None:
        import requests

        def get(url):
            return requests.get(url, headers=NSE_HEADERS, timeout=30)

    out = {label: {} for label in labels}
    for day in days:
        if day.weekday() >= 5:
            continue
        url = NSE_INDEX_CLOSE_URL.format(day=day)
        try:
            response = get(url)
        except Exception as error:  # noqa: BLE001 - one day must not end the run
            logger.warning("NSE index file for %s failed: %s", day, error)
            continue
        if response.status_code != 200:
            logger.info("NSE index file for %s not available (HTTP %s)", day, response.status_code)
            continue
        for row in csv.DictReader(io.StringIO(response.text)):
            label = (row.get("Index Name") or "").strip()
            if label not in out:
                continue
            try:
                stamp = datetime.strptime((row.get("Index Date") or "").strip(), "%d-%m-%Y").date()
                close = float(row["Closing Index Value"])
            except (KeyError, ValueError):
                continue
            # The file must be the session that was asked for.
            if close > 0 and stamp == day:
                out[label][stamp] = close
    return out


def overlay_nse_closes(points, headline_indices, cap, *, get=None):
    """Overwrite the recent closes in ``points`` with NSE's own published values.

    Yahoo supplies the long history; NSE is the source of record and is what is
    fresh, so its values win for the last ``NSE_INDEX_LOOKBACK_DAYS`` days. An
    index Yahoo returned nothing for is left alone -- overlaying ten days onto
    an empty series would publish a ten-day chart in place of the whole history.
    """
    from datetime import timedelta

    wanted = {
        label: ticker for ticker, label in headline_indices if points.get(ticker)
    }
    if not wanted:
        return points
    days = [cap - timedelta(days=n) for n in range(NSE_INDEX_LOOKBACK_DAYS, -1, -1)]
    for label, closes in fetch_nse_index_closes(wanted, days, get=get).items():
        points[wanted[label]].update(closes)
    return points


def completed_session_cap(profile, now=None):
    """Latest date whose daily bar can be final: today after the cutoff, else yesterday.

    Yahoo serves the live session as a partial daily bar while the market is
    open. Without this cap a run during trading hours publishes an intraday
    level as that day's close.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(profile.timezone)
    local = (now or datetime.now(zone)).astimezone(zone)
    hour, minute = (int(part) for part in profile.bar_complete_after.split(":")[:2])
    if (local.hour, local.minute) >= (hour, minute):
        return local.date()
    return local.date() - timedelta(days=1)


def stale_indices(indices, tickers, last_session):
    """Tickers with no history, or whose newest close is before ``last_session``."""
    return [
        ticker
        for ticker in tickers
        if not indices.get(ticker) or max(indices[ticker]) < last_session
    ]


def fetch_fresh_indices(tickers, last_session, *, fetch, retries=3, wait=300.0, sleep=time.sleep):
    """Fetch index closes, re-fetching any that end before ``last_session``.

    Returns ``(indices, stale)``. The stock breadth reaches ``last_session``
    from its own source, so an index that stops earlier is the vendor being late
    (it was on 28 Sept 2026: the NSE indices ended on the 25th while the run
    reported success). A retry that comes back empty never replaces history
    already in hand.
    """
    indices = fetch(tickers)
    stale = stale_indices(indices, tickers, last_session)
    for attempt in range(1, retries + 1):
        if not stale:
            break
        logger.warning(
            "Indices behind %s: %s; retry %d/%d in %.0fs",
            last_session, ", ".join(stale), attempt, retries, wait,
        )
        sleep(wait)
        for ticker, points in fetch(stale).items():
            if points:
                indices[ticker] = points
        stale = stale_indices(indices, tickers, last_session)
    return indices, stale


def fetch_index_points(
    tickers, *, start=DEFAULT_START, end=None, downloader=None, not_after=None
):
    """``{ticker: {date: close}}`` for each index; a failed ticker maps to {}.

    Bars dated after ``not_after`` are dropped: they are the live session's
    partial bar, not a close.
    """
    import pandas as pd

    if downloader is None:
        import yfinance as yf

        def downloader(ticker):
            return yf.download(
                ticker, start=start, end=end, auto_adjust=False, progress=False, threads=False
            )

    out = {}
    for ticker in tickers:
        try:
            frame = downloader(ticker)
        except Exception as error:  # noqa: BLE001 - one index must not end the run
            logger.warning("Index %s failed: %s", ticker, error)
            out[ticker] = {}
            continue
        if frame is None or frame.empty or "Close" not in frame:
            logger.warning("Index %s returned no history", ticker)
            out[ticker] = {}
            continue
        closes = frame["Close"]
        if isinstance(closes, pd.DataFrame):
            closes = closes.iloc[:, 0]
        closes = pd.to_numeric(closes, errors="coerce").dropna()
        out[ticker] = {
            pd.Timestamp(stamp).date(): float(value)
            for stamp, value in closes.items()
            if value > 0 and (not_after is None or pd.Timestamp(stamp).date() <= not_after)
        }
    return out


def symbol_observations(observations, symbols):
    """Re-key archive observations from security id to current symbol.

    A ticker reused by a different company resolves to whichever security
    traded under it most recently, as `price_series_publisher.build_rows` does,
    so breadth and the stock chart agree on who a symbol is.
    """
    by_symbol: dict[str, dict] = {}
    latest: dict[str, object] = {}
    for security_id, points in observations.items():
        symbol = symbols.get(security_id)
        if not symbol or not points:
            continue
        last = max(points)
        if symbol not in latest or latest[symbol] < last:
            latest[symbol] = last
            by_symbol[symbol] = points
    return by_symbol


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default=os.getenv("MARKET", "NSE"))
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help="NSE archive root (ignored for vendor-sourced markets)")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="build and report sizes without writing")
    parser.add_argument("--dump", default=None,
                        help="also write the rows and today's lists to this JSON file, for inspection")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    loaded = load_env_file()
    if loaded:
        logger.info("Loaded %s from .env", ", ".join(sorted(loaded)))

    from screener.markets import NSE
    from screener.markets import resolve as resolve_market
    from storage.dashboard_repository import DashboardRepository
    from workers.market_breadth import build_breadth

    profile = resolve_market(args.market)

    # Needed even on a dry run: the classification is the universe.
    try:
        repository = DashboardRepository.from_environment(profile.code)
    except ValueError as error:
        raise SystemExit(f"{error}\n\nSet SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.") from error

    classification = repository.latest_snapshot_classification()
    if not classification:
        raise SystemExit(f"No published {profile.code} run to take a universe from")
    logger.info("Universe: %d symbols from the latest %s run", len(classification), profile.code)

    started = time.monotonic()
    if profile.code == NSE:
        from tools.publish_price_series import load_archive

        sessions, raw, symbols, _ = load_archive(Path(args.root), start=args.start, end=args.end)
        observations = symbol_observations(raw, symbols)
    else:
        from workers.price_series_market import collect_observations, trading_calendar

        sessions = trading_calendar(profile, start=args.start, end=args.end)
        observations = collect_observations(
            sorted(classification), profile, start=args.start, end=args.end
        )
    logger.info("Price history for %d symbols in %.0fs", len(observations), time.monotonic() - started)

    tickers = [ticker for ticker, _ in profile.headline_indices]
    if profile.benchmark_symbol not in tickers:
        tickers.append(profile.benchmark_symbol)
    cap = completed_session_cap(profile)
    # The breadth charts end on the newest session the price source has; an
    # index that ends earlier is a vendor lag, retried below and then reported.
    last_session = min(sessions[-1], cap) if len(sessions) else None

    def fetch(names):
        points = fetch_index_points(names, start=args.start, end=args.end, not_after=cap)
        if profile.code == NSE:
            # NSE publishes its own index closes; Yahoo only supplies history.
            overlay_nse_closes(points, profile.headline_indices, cap)
        return points

    if last_session:
        indices, stale = fetch_fresh_indices(
            tickers,
            last_session,
            fetch=fetch,
            retries=int(os.getenv("INDEX_FRESHNESS_RETRIES", "3")),
            wait=float(os.getenv("INDEX_FRESHNESS_WAIT_SECONDS", "300")),
        )
    else:
        indices, stale = fetch(tickers), []
    if stale:
        logger.error(
            "Indices still behind %s after retries: %s. Publishing what exists; the run "
            "fails so the gap is visible.", last_session, ", ".join(stale),
        )

    started = time.monotonic()
    rows, members = build_breadth(
        observations,
        sessions,
        classification,
        benchmark_points=indices.get(profile.benchmark_symbol) or None,
        index_points=[(label, indices.get(ticker, {})) for ticker, label in profile.headline_indices],
    )
    size = sum(len(row["series"]) + len(row["sessions"]) for row in rows)
    logger.info(
        "Built %d rows (%.1f MB encoded) in %.0fs", len(rows), size / 1e6, time.monotonic() - started
    )

    if args.dump:
        import json

        Path(args.dump).write_text(json.dumps({"rows": rows, "members": members}), encoding="utf-8")
        logger.info("Wrote rows to %s", args.dump)
    if args.dry_run:
        logger.info("Dry run: nothing written")
        return 1 if stale else 0
    written = repository.replace_market_breadth(rows)
    logger.info("Published %d market breadth rows", written)
    # After the rows, so a list never names a session the charts do not show yet.
    market_row = next((row for row in rows if row["scope"] == "market"), None)
    if market_row:
        listed = repository.replace_breadth_members(members, market_row["last_session"])
        logger.info("Published %d list memberships for %s", listed, market_row["last_session"])
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
