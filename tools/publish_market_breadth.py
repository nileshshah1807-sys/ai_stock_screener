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


def fetch_index_points(tickers, *, start=DEFAULT_START, end=None, downloader=None):
    """``{ticker: {date: close}}`` for each index; a failed ticker maps to {}."""
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
            if value > 0
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
    indices = fetch_index_points(tickers, start=args.start, end=args.end)

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
        return 0
    written = repository.replace_market_breadth(rows)
    logger.info("Published %d market breadth rows", written)
    # After the rows, so a list never names a session the charts do not show yet.
    market_row = next((row for row in rows if row["scope"] == "market"), None)
    if market_row:
        listed = repository.replace_breadth_members(members, market_row["last_session"])
        logger.info("Published %d list memberships for %s", listed, market_row["last_session"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
