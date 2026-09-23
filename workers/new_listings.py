"""Publish recently listed NSE stocks the screener has not rated yet.

A new mainboard listing is absent from the scored universe until it has
``MIN_PRICE_SESSIONS_REQUIRED`` (60) sessions of history and clears the
execution liquidity floor (``MIN_AVG_TURNOVER_INR`` / ``MIN_MEDIAN_TURNOVER_20D_INR``,
Rs 50 lakh a day). Both rules are right for scoring -- a three-week-old stock
has no 50-day average and no six-month momentum, and absent evidence must not
score as zero -- but they made new listings invisible, which read as "the
screener missed this IPO".

This worker makes the wait visible. It never scores anything: it writes one row
per recent listing that is NOT in the latest published run, with price facts and
the specific reason it is not rated yet, to the ``new_listings`` table. It
replaces that set on every run, so a listing drops out the day the model starts
rating it.

Recent means listed within ``--window-days`` (default 365) per NSE's own
EQUITY_L master. That file also re-dates companies that move to the mainboard
from SME or another exchange, so these are "recently listed on NSE", not
strictly IPOs. Series BZ (trade-for-trade, non-compliant) is excluded, as are
rights entitlements (``-RE`` symbols), which are temporary instruments rather
than companies. SME (NSE Emerge) is out of scope, as it is for the screener.

Sessions are counted from the price source, not from the listing date. They
can differ a lot: a company re-dated onto the NSE mainboard in April may have
Yahoo history only from August, and it is the vendor's count the screener's
60-session rule actually sees.

The thresholds are read from the same environment variables, with the same
defaults, that the screener uses, so "why is this not rated" cannot drift from
what the run actually enforces.
"""

from __future__ import annotations

import argparse
import io
import logging
import math
import os
import time
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from screener.markets import resolve as resolve_market
from screener.markets import ticker_for
from screener.numeric import round_half_up, safe_float

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 365
INCLUDED_SERIES = {"EQ", "BE"}
TURNOVER_WINDOW = 20
DOWNLOAD_BATCH = 30

STATUS_INSUFFICIENT_HISTORY = "insufficient_history"
STATUS_BELOW_LIQUIDITY_FLOOR = "below_liquidity_floor"
STATUS_NO_PRICE_DATA = "no_price_data"
STATUS_PENDING_RUN = "pending_run"


def _env_number(name: str, default: float) -> float:
    value = safe_float(os.getenv(name))
    return default if value is None else value


def thresholds() -> dict[str, float]:
    """The screener's own admission rules, from the same env vars and defaults."""
    return {
        "sessions": int(_env_number("MIN_PRICE_SESSIONS_REQUIRED", 60)),
        "mean_turnover": _env_number("MIN_AVG_TURNOVER_INR", 50_00_000.0),
        "median_turnover": _env_number("MIN_MEDIAN_TURNOVER_20D_INR", 50_00_000.0),
    }


def recent_listings(master: pd.DataFrame, as_of: date, window_days: int) -> pd.DataFrame:
    """Mainboard listings dated within the window, from NSE's EQUITY_L master."""
    frame = master.copy()
    frame.columns = [str(c).strip() for c in frame.columns]
    frame["symbol"] = frame["SYMBOL"].astype(str).str.strip().str.upper()
    frame["series"] = frame["SERIES"].astype(str).str.strip().str.upper()
    frame["listed_on"] = pd.to_datetime(
        frame["DATE OF LISTING"].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce"
    ).dt.date
    frame["company"] = frame.get("NAME OF COMPANY", pd.Series(dtype=str)).astype(str).str.strip()
    frame["isin"] = frame.get("ISIN NUMBER", pd.Series(dtype=str)).astype(str).str.strip()
    earliest = pd.Timestamp(as_of) - pd.Timedelta(days=window_days)
    keep = (
        frame["listed_on"].notna()
        & frame["series"].isin(INCLUDED_SERIES)
        & ~frame["symbol"].str.endswith("-RE")
        & (pd.to_datetime(frame["listed_on"]) > earliest)
        & (pd.to_datetime(frame["listed_on"]) <= pd.Timestamp(as_of))
    )
    return frame.loc[keep, ["symbol", "company", "isin", "series", "listed_on"]].reset_index(drop=True)


def _money(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round_half_up(value, 0)


def summarize_prices(prices: pd.DataFrame | None) -> dict[str, Any]:
    """Price facts for a listing from its daily bars (Close and Volume)."""
    empty = {
        "sessions": 0,
        "first_session": None,
        "first_close": None,
        "last_session": None,
        "last_close": None,
        "change_since_first_pct": None,
        "avg_turnover_20d": None,
        "median_turnover_20d": None,
    }
    if prices is None or prices.empty or "Close" not in prices or "Volume" not in prices:
        return empty
    close = pd.to_numeric(prices["Close"], errors="coerce")
    volume = pd.to_numeric(prices["Volume"], errors="coerce")
    usable = close.notna() & volume.notna() & (close > 0)
    close, volume = close[usable], volume[usable]
    if close.empty:
        return empty
    turnover = (close * volume).tail(TURNOVER_WINDOW)
    first, last = float(close.iloc[0]), float(close.iloc[-1])
    return {
        "sessions": int(len(close)),
        "first_session": pd.Timestamp(close.index[0]).date().isoformat(),
        "first_close": round_half_up(first, 2),
        "last_session": pd.Timestamp(close.index[-1]).date().isoformat(),
        "last_close": round_half_up(last, 2),
        # One session has no "since": the change would always read 0.0%.
        "change_since_first_pct": (
            round_half_up((last / first - 1) * 100, 2) if len(close) >= 2 else None
        ),
        "avg_turnover_20d": _money(float(turnover.mean())),
        "median_turnover_20d": _money(float(turnover.median())),
    }


def classify(summary: dict[str, Any], limits: dict[str, float]) -> str:
    """Why a listing is not rated, in the order the screener applies its rules."""
    if not summary["sessions"]:
        return STATUS_NO_PRICE_DATA
    if summary["sessions"] < limits["sessions"]:
        return STATUS_INSUFFICIENT_HISTORY
    mean = summary["avg_turnover_20d"]
    median = summary["median_turnover_20d"]
    if (
        mean is None
        or median is None
        or mean < limits["mean_turnover"]
        or median < limits["median_turnover"]
    ):
        return STATUS_BELOW_LIQUIDITY_FLOOR
    # Meets both minimums but was not in the latest run: either it crossed them
    # since that run, or another admission check (a zero-volume last session,
    # NSE's official liquidity category) held it out. Either way it is not a
    # rating the dashboard should imply.
    return STATUS_PENDING_RUN


def download_prices(tickers: list[str], download: Callable[..., pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Batched daily bars, keyed by vendor ticker. Missing tickers are omitted."""
    out: dict[str, pd.DataFrame] = {}
    for start in range(0, len(tickers), DOWNLOAD_BATCH):
        batch = tickers[start : start + DOWNLOAD_BATCH]
        if start:
            time.sleep(1)
        try:
            data = download(
                " ".join(batch), period="1y", group_by="ticker",
                progress=False, threads=True, auto_adjust=False,
            )
        except Exception as exc:  # one failed batch must not sink the run
            logger.warning("Price batch failed (%s): %s", ", ".join(batch[:3]), exc)
            continue
        if data is None or data.empty:
            continue
        for ticker in batch:
            if isinstance(data.columns, pd.MultiIndex):
                if ticker in data.columns.get_level_values(0):
                    out[ticker] = data[ticker]
            elif len(batch) == 1:
                out[ticker] = data
    return out


def run(
    repo,
    *,
    fetch_master: Callable[[], pd.DataFrame],
    download: Callable[..., pd.DataFrame],
    profile_lookup: Callable[[str], dict[str, Any]],
    as_of: date | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    dry_run: bool = False,
) -> dict[str, int]:
    profile = resolve_market(repo.market)
    as_of = as_of or datetime.now(UTC).date()
    limits = thresholds()

    listings = recent_listings(fetch_master(), as_of, window_days)
    if listings.empty:
        # NSE lists new companies every week; an empty year means the master
        # was unreadable, and publishing that would wipe the table.
        logger.warning("No listings parsed from the master file; leaving new_listings untouched")
        return {"listings": 0, "published": 0}
    rated = set(repo.latest_snapshot_symbols())
    candidates = listings[~listings["symbol"].isin(rated)]
    logger.info(
        "%s: %d listed in the last %d days, %d already rated, %d not yet rated",
        profile.code, len(listings), window_days, len(listings) - len(candidates), len(candidates),
    )

    tickers = {row.symbol: ticker_for(row.symbol, profile) for row in candidates.itertuples()}
    prices = download_prices(list(tickers.values()), download)

    rows = []
    counts: dict[str, int] = {}
    for listing in candidates.itertuples():
        summary = summarize_prices(prices.get(tickers[listing.symbol]))
        status = classify(summary, limits)
        counts[status] = counts.get(status, 0) + 1
        # Issuer profile: market cap and the website the dashboard turns into a
        # logo, from the same lookup the rated universe uses. Skipped for a
        # listing with no bars -- the vendor has nothing on it yet either.
        facts = profile_lookup(tickers[listing.symbol]) if summary["sessions"] else {}
        cap = facts.get("market_cap")
        rows.append({
            "symbol": listing.symbol,
            "company": listing.company or None,
            "isin": listing.isin or None,
            "series": listing.series,
            "listed_on": listing.listed_on.isoformat(),
            "status": status,
            "sessions_required": limits["sessions"],
            "turnover_floor": _money(limits["mean_turnover"]),
            "market_cap": _money(cap) if cap is not None else None,
            "logo_domain": facts.get("logo_domain"),
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **summary,
        })

    logger.info("%s new listings by status: %s", profile.code, counts)
    if not dry_run:
        repo.replace_new_listings(rows)
    return {"listings": len(listings), "published": len(rows), **counts}


def _yahoo_profile(ticker: str) -> dict[str, Any]:
    """Market cap and logo domain from Yahoo's quote profile.

    ``Ticker.info`` rather than ``fast_info``: the fast path derives market cap
    from a shares count Yahoo often lacks for a listing this new, so it came
    back empty for most of them, and only the full profile carries the issuer
    website. The website goes through the same normaliser the rated universe's
    logo backfill uses, so both resolve to identical domains.
    """
    import yfinance as yf

    from workers.logo_domain_backfill import normalize_domain

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:  # vendor raises for thin or brand-new listings
        return {}
    cap = safe_float(info.get("marketCap"))
    return {
        "market_cap": cap if cap and cap > 0 else None,
        "logo_domain": normalize_domain(info.get("website")),
    }


def _fetch_nse_master() -> pd.DataFrame:
    from screener.universe import NSE_EQUITY_L_URL, _get

    response = _get(NSE_EQUITY_L_URL)
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE", help="only NSE carries listing dates")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if resolve_market(args.market).code != "NSE":
        logger.info("New-listing tracking is NSE-only; nothing to do for %s", args.market)
        return 0

    import yfinance as yf

    from storage.dashboard_repository import DashboardRepository

    repo = DashboardRepository.from_environment("NSE")
    run(
        repo,
        fetch_master=_fetch_nse_master,
        download=yf.download,
        profile_lookup=_yahoo_profile,
        window_days=args.window_days,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
