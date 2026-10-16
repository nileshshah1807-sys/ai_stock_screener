"""Intraday quotes for the dashboard, refreshed every five minutes.

Display only. Nothing here is scored: rank, rating and every technical feature
stay on the last completed session's adjusted close, as the screener writes
them. This worker writes the price the market is trading at now, so the grid,
the stock page and the Market page's movers can show it beside that model.

The Live quotes workflow runs it. cron-job.org dispatches the workflow every
five minutes on weekdays; outside the session (``MarketProfile.session_open``
to ``session_close``, with a few minutes' margin) the worker returns at once,
and on an exchange holiday it fetches, finds no quote from today, and writes
nothing.

One request per 500 symbols to Yahoo's quote endpoint -- the whole NSE
universe in about six seconds (measured October 2026) -- through yfinance's
own session, which carries the cookie and crumb the endpoint requires. Each
quote is one row per (market, symbol) in ``live_quotes``, overwritten in place.

The day's change is Yahoo's price over its previous close. Where an action
changes the unit between the two -- a split on its ex-date, before the vendor
restates the previous close -- that ratio is the unit change, not a move. On a
market whose opening auction is capped (``MarketProfile.max_open_gap``, NSE
20%) a ratio past the cap cannot have traded, so the change is stored as
unknown and the price alone is shown: the same rule
``backtest.corporate_actions.open_gap_factor`` applies to daily bars.

Once a day the worker also re-reads the constituents of each index in
``MarketProfile.live_indices`` into ``index_members``, which is what the
Market page ranks the day's movers within.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from screener import index_members
from screener.markets import MarketProfile, ticker_for
from screener.markets import resolve as resolve_market
from screener.numeric import round_half_up, safe_float

logger = logging.getLogger(__name__)

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
#: Symbols per quote request. 500 keeps the URL near 7 KB; the endpoint
#: answered every batch of the full universe at this size.
QUOTE_BATCH = 500

#: Minutes either side of the session in which the worker still runs: the
#: pre-open settles the opening price, and the last run after the close
#: records the final trades.
SESSION_MARGIN_MINUTES = 10

#: Constituents are re-read when the stored lists are older than this.
MEMBERS_MAX_AGE = timedelta(hours=20)

#: A quote no run has refreshed for this long belongs to a symbol that has
#: left both the universe and every index.
PRUNE_AFTER = timedelta(days=7)

#: Below this share of requested symbols quoted, the run reports failure, so
#: a vendor outage shows in the Actions history rather than as stale prices.
MIN_COVERAGE = 0.5

KIND_STOCK = "stock"
KIND_INDEX = "index"

QuoteFetcher = Callable[[list[str]], dict[str, dict[str, Any]]]
MembersFetcher = Callable[[str], list[tuple[str, str | None]]]


def _clock(value: str) -> int:
    """Minutes past midnight for an ``HH:MM`` string."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def in_session(now: datetime, profile: MarketProfile) -> bool:
    """Whether ``now`` (aware) falls on a weekday within the session's margin.

    Holidays are not known here; a holiday run is caught after the fetch, when
    no quote is from today.
    """
    local = now.astimezone(ZoneInfo(profile.timezone))
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    start = _clock(profile.session_open) - SESSION_MARGIN_MINUTES
    end = _clock(profile.session_close) + SESSION_MARGIN_MINUTES
    return start <= minutes <= end


def yahoo_quotes(
    tickers: list[str],
    batch_size: int = QUOTE_BATCH,
    get: Callable[..., Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Quote dicts keyed by vendor ticker.

    A ticker the vendor does not know is simply absent; a batch that fails
    twice is logged and skipped, so one bad batch costs 500 symbols rather
    than the run.
    """
    if get is None:
        from yfinance.data import YfData

        get = YfData().get
    quotes: dict[str, dict[str, Any]] = {}
    for start in range(0, len(tickers), batch_size):
        chunk = tickers[start : start + batch_size]
        payload = None
        for attempt in range(2):
            try:
                response = get(QUOTE_URL, params={"symbols": ",".join(chunk)}, timeout=30)
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as exc:  # noqa: BLE001 -- any vendor failure skips one batch
                if attempt:
                    logger.warning("Quote batch at %d failed twice: %s", start, exc)
                else:
                    time.sleep(2)
        results = ((payload or {}).get("quoteResponse") or {}).get("result") or []
        for quote in results:
            symbol = quote.get("symbol")
            if symbol:
                quotes[str(symbol)] = quote
    return quotes


def _positive(value: Any) -> float | None:
    number = safe_float(value)
    return round_half_up(number, 4) if number is not None and number > 0 else None


def quote_row(
    symbol: str,
    quote: dict[str, Any],
    profile: MarketProfile,
    kind: str,
    fetched_at: str,
) -> dict[str, Any] | None:
    """One ``live_quotes`` row, or None when the quote has no usable price."""
    price = _positive(quote.get("regularMarketPrice"))
    traded = safe_float(quote.get("regularMarketTime"))
    if price is None or traded is None or traded <= 0:
        return None
    traded_at = datetime.fromtimestamp(traded, UTC)
    # The previous close is the price less Yahoo's own change for the day.
    # Its regularMarketPreviousClose field is stale on index quotes -- an
    # older session's close on every NSE index measured (October 2026), so
    # Nifty 50 read +2.2% on a +0.55% day -- while the change agrees with
    # the price; the field is only the fallback.
    change = safe_float(quote.get("regularMarketChange"))
    previous = _positive(
        price - change if change is not None else quote.get("regularMarketPreviousClose")
    )

    change_pct = None
    if previous is not None:
        ratio = price / previous
        cap = profile.max_open_gap
        if kind == KIND_STOCK and cap and not (1 / cap <= ratio <= cap):
            # A unit change, not a move; see the module docstring.
            logger.info("Change for %s withheld: %.4f of the previous close", symbol, ratio)
        else:
            change_pct = round_half_up((ratio - 1) * 100, 4)

    volume = safe_float(quote.get("regularMarketVolume"))
    return {
        "symbol": symbol,
        "kind": kind,
        "price": price,
        "previous_close": previous,
        "change_pct": change_pct,
        "day_high": _positive(quote.get("regularMarketDayHigh")),
        "day_low": _positive(quote.get("regularMarketDayLow")),
        "volume": int(volume) if volume is not None and volume >= 0 else None,
        "traded_at": traded_at.isoformat(timespec="seconds"),
        "session": traded_at.astimezone(ZoneInfo(profile.timezone)).date().isoformat(),
        "fetched_at": fetched_at,
    }


def member_rows(profile: MarketProfile, fetch: MembersFetcher) -> list[dict[str, Any]] | None:
    """Every tracked index's constituents, or None if any list failed.

    All or nothing: replacing the table with a partial set would delete the
    lists that failed to download.
    """
    rows: list[dict[str, Any]] = []
    for position, index in enumerate(profile.live_indices):
        try:
            members = fetch(index.members_source)
        except Exception as exc:  # noqa: BLE001 -- keep yesterday's lists instead
            logger.warning("Constituents of %s unavailable: %s", index.label, exc)
            return None
        if not members:
            logger.warning("Constituents of %s came back empty", index.label)
            return None
        rows.extend(
            {"index_name": index.label, "position": position, "symbol": symbol, "company": company}
            for symbol, company in members
        )
    return rows


def members_due(refreshed_at: str | None, now: datetime) -> bool:
    if not refreshed_at:
        return True
    try:
        stamp = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - stamp > MEMBERS_MAX_AGE


def run(
    repo,
    profile: MarketProfile,
    *,
    now: datetime,
    fetch_quotes: QuoteFetcher = yahoo_quotes,
    fetch_members: MembersFetcher = index_members.fetch,
    dry_run: bool = False,
    force: bool = False,
    refresh_members: bool = False,
) -> dict[str, Any]:
    """Refresh one market's quotes. Returns a summary for the log and tests."""
    if not force and not in_session(now, profile):
        logger.info("Outside the %s session; nothing to do", profile.code)
        return {"status": "outside_session"}

    fresh_members: list[dict[str, Any]] | None = None
    if profile.live_indices and (
        refresh_members or members_due(repo.index_members_refreshed_at(), now)
    ):
        fresh_members = member_rows(profile, fetch_members)
        if fresh_members and not dry_run:
            written = repo.replace_index_members(fresh_members)
            logger.info("Stored %d index constituents", written)

    symbols = set(repo.latest_snapshot_symbols()) | set(repo.index_member_symbols())
    symbols |= {row["symbol"] for row in fresh_members or []}
    stock_tickers = {ticker_for(symbol, profile): symbol for symbol in sorted(symbols)}
    index_tickers = {
        index.quote_symbol: index.label for index in profile.live_indices if index.quote_symbol
    }
    quotes = fetch_quotes([*stock_tickers, *index_tickers])

    fetched_at = now.astimezone(UTC).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for tickers, kind in ((stock_tickers, KIND_STOCK), (index_tickers, KIND_INDEX)):
        for ticker, symbol in tickers.items():
            quote = quotes.get(ticker)
            row = quote_row(symbol, quote, profile, kind, fetched_at) if quote else None
            if row:
                rows.append(row)

    stocks = [row for row in rows if row["kind"] == KIND_STOCK]
    today = now.astimezone(ZoneInfo(profile.timezone)).date().isoformat()
    newest = max((row["session"] for row in stocks), default=None)
    summary: dict[str, Any] = {
        "status": "written",
        "requested": len(stock_tickers),
        "quoted": len(stocks),
        "indices": len(rows) - len(stocks),
        "traded_today": sum(row["session"] == today for row in stocks),
        "change_withheld": sum(
            row["change_pct"] is None and row["previous_close"] is not None for row in stocks
        ),
        "session": newest,
    }
    if newest != today and not force:
        # A holiday, or a run in the margin before the first trade.
        summary["status"] = "no_session_today"
        logger.info("No %s quote is from %s; nothing written: %s", profile.code, today, summary)
        return summary

    if dry_run:
        summary["status"] = "dry_run"
    else:
        repo.upsert_live_quotes(rows)
        repo.prune_live_quotes((now - PRUNE_AFTER).astimezone(UTC).isoformat(timespec="seconds"))
    logger.info("Live quotes for %s: %s", profile.code, summary)
    if stock_tickers and len(stocks) < MIN_COVERAGE * len(stock_tickers):
        summary["status"] = "low_coverage"
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--dry-run", action="store_true", help="fetch without writing")
    parser.add_argument(
        "--force", action="store_true", help="run outside the session and on a holiday"
    )
    parser.add_argument(
        "--refresh-members", action="store_true", help="re-read index constituents now"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    profile = resolve_market(args.market)

    from storage.dashboard_repository import DashboardRepository

    summary = run(
        DashboardRepository.from_environment(profile.code),
        profile,
        now=datetime.now(UTC),
        dry_run=args.dry_run,
        force=args.force,
        refresh_members=args.refresh_members,
    )
    if summary["status"] == "low_coverage":
        logger.error("Fewer than %.0f%% of symbols were quoted", MIN_COVERAGE * 100)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
