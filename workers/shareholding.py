"""Store NSE's shareholding patterns and bulk/block deals for the stock page.

The stock page's Shareholding tab reads two tables this job writes
(``storage/shareholding_schema.sql``) and fetches nothing itself:

* ``shareholding_patterns`` -- each quarter's filing, parsed once by
  ``screener.shareholding.parse_pattern``. A filing is fetched when nothing
  is stored for its (symbol, quarter), when the exchange lists a different
  record (a revision), or when the stored row was parsed by an older
  ``PARSER_VERSION``.
* ``bulk_block_deals`` -- every deal the exchange lists over the lookback.
  Upserting a deal already stored changes nothing, so a short run re-reads the
  last few sessions rather than tracking what it has seen.

A run reads the last ``--lookback-days``; ``--full`` (or an empty patterns
table) reads back to ``FULL_LOOKBACK_DAYS``, which is how the tables are first
built. Display evidence only: nothing scores it.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from screener import shareholding
from screener.markets import resolve as resolve_market
from screener.quarterly_results import REQUEST_HEADERS, DocumentFetcher

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 7
# Back to the September 2022 format, the first to split institutions into
# domestic and foreign; an older filing has no FII or DII to show.
FULL_LOOKBACK_DAYS = 1480
# The index serves a whole year in one call (2024: 8,960 filings, the same
# as twelve monthly calls), and a full sweep that asked month by month -- 49
# calls in a burst -- was followed by the archive refusing the runner. The
# deals export refuses more than a year, so it is read by quarter.
INDEX_WINDOW_DAYS = 365
DEALS_WINDOW_DAYS = 90
BATCH_SIZE = 60
# The archive's CDN answers "Access Denied" to a hosted runner fetching at
# ~12 documents a second (18 Oct 2026). The `nse` package the rest of the
# repo uses throttles every request to 3 a second; documents are fetched one
# at a time at that rate.
REQUESTS_PER_SECOND = 3


class PacedFetcher:
    """Documents one at a time, no faster than ``rate`` a second."""

    def __init__(self, rate: float = REQUESTS_PER_SECOND, *, fetcher=None,
                 clock=time.monotonic, sleep=time.sleep):
        self.interval = 1.0 / rate
        self.fetcher = fetcher or DocumentFetcher(workers=1)
        self.clock = clock
        self.sleep = sleep
        self._next = 0.0

    def fetch_many(self, urls: list[str]) -> list[str | None]:
        texts = []
        for url in urls:
            wait = self._next - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._next = self.clock() + self.interval
            texts.append(self.fetcher.fetch_one(url))
        return texts


def _windows(start: date, end: date, days: int):
    while start <= end:
        stop = min(end, start + timedelta(days=days - 1))
        yield start, stop
        start = stop + timedelta(days=1)


def _answer(url: str) -> str:
    """What the archive says to one request, for the log when it refuses a batch."""
    import requests

    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
    except requests.RequestException as exc:
        return type(exc).__name__
    return f"HTTP {response.status_code}: {response.text.lstrip()[:60]!r}"


def due_patterns(
    filings: list[dict[str, Any]], stored: dict[tuple[str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    """Filings not stored as they now stand, newest first (as given)."""
    due = []
    for row in filings:
        have = stored.get((row["symbol"], row["period_end"].isoformat()))
        if (
            have is None
            or str(have.get("record_id")) != row["record_id"]
            or int(have.get("parser_version") or 0) < shareholding.PARSER_VERSION
        ):
            due.append(row)
    return due


def pattern_row(filing: dict[str, Any], parsed: dict[str, Any], *, timezone: str,
                parsed_at: str) -> dict[str, Any]:
    return {
        "symbol": filing["symbol"],
        "period_end": filing["period_end"].isoformat(),
        "record_id": filing["record_id"],
        "filed_at": filing["filed_at"].replace(tzinfo=ZoneInfo(timezone)).isoformat(
            timespec="seconds"
        ),
        "document_url": filing["document_url"],
        "company": filing["company"],
        **{key: parsed[key] for key in ("promoter", "fii", "dii", "public", "holders", "shares")},
        "shareholders": None if parsed["shareholders"] is None else int(parsed["shareholders"]),
        "parser_version": shareholding.PARSER_VERSION,
        "parsed_at": parsed_at,
    }


def store_patterns(
    repo, *, stored: dict[tuple[str, str], dict[str, Any]], start: date, end: date,
    timezone: str, index_loader: Callable[[date, date], list[dict]], fetcher,
    time_budget_seconds: float | None, clock, dry_run: bool,
) -> dict[str, int]:
    counts = {"due": 0, "stored": 0, "failed": 0, "deferred": 0}
    records = []
    for window_start, window_end in _windows(start, end, INDEX_WINDOW_DAYS):
        records += index_loader(window_start, window_end)
    due = due_patterns(shareholding.quarter_filings(records), stored)
    counts["due"] = len(due)
    logger.info("Shareholding patterns: %d filing(s) indexed, %d to fetch", len(records), len(due))

    started = clock()
    for position in range(0, len(due), BATCH_SIZE):
        if time_budget_seconds is not None and clock() - started >= time_budget_seconds:
            counts["deferred"] = len(due) - position
            logger.info("Time budget spent; %d pattern(s) left for the next run", counts["deferred"])
            break
        batch = due[position:position + BATCH_SIZE]
        texts = fetcher.fetch_many([row["document_url"] for row in batch])
        if all(text is None for text in texts):
            # The archive refuses some hosted runners' addresses outright
            # (18 Oct 2026: 35,111 of 35,114 refused on one runner, none on the
            # next). Asking for the rest from here only spends the budget.
            counts["failed"] += len(batch)
            counts["deferred"] = len(due) - position - len(batch)
            logger.warning(
                "The archive refused a whole batch (%s); stopping with %d pattern(s) left",
                _answer(batch[0]["document_url"]), counts["deferred"],
            )
            break
        parsed_at = datetime.now(UTC).isoformat(timespec="seconds")
        rows = []
        for filing, text in zip(batch, texts, strict=True):
            try:
                parsed = None if text is None else shareholding.parse_pattern(text)
            except Exception as exc:  # one malformed document is not the run
                logger.warning("Unreadable pattern %s: %s", filing["document_url"], exc)
                parsed = None
            if parsed is None:
                counts["failed"] += 1
                continue
            rows.append(pattern_row(filing, parsed, timezone=timezone, parsed_at=parsed_at))
        if rows and not dry_run:
            repo.upsert_shareholding_patterns(rows)
        counts["stored"] += len(rows)
    if counts["failed"]:
        logger.warning("%d pattern(s) could not be read; asked for again next run", counts["failed"])
    return counts


def store_deals(
    repo, *, start: date, end: date,
    deals_loader: Callable[[str, date, date], list[dict]], dry_run: bool,
) -> int:
    rows: dict[tuple, dict[str, Any]] = {}
    for kind in shareholding.DEAL_KINDS:
        for window_start, window_end in _windows(start, end, DEALS_WINDOW_DAYS):
            for row in deals_loader(kind, window_start, window_end):
                # The same trade printed twice would make one upsert touch a
                # row twice, which Postgres refuses.
                key = tuple(row[k] for k in (
                    "kind", "deal_date", "symbol", "client_name", "side", "quantity", "price"
                ))
                rows[key] = row
    if rows and not dry_run:
        repo.upsert_bulk_block_deals(list(rows.values()))
    logger.info("Bulk and block deals: %d stored", len(rows))
    return len(rows)


def run(
    repo,
    *,
    index_loader: Callable[[date, date], list[dict]] | None = None,
    deals_loader: Callable[[str, date, date], list[dict]] | None = None,
    fetcher=None,
    today: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    full: bool = False,
    time_budget_seconds: float | None = None,
    clock=time.monotonic,
    dry_run: bool = False,
) -> dict[str, int]:
    profile = resolve_market(repo.market)
    if profile.code != "NSE":
        logger.info("%s discloses no shareholding pattern; nothing to store", profile.code)
        return {}
    today = today or datetime.now(ZoneInfo(profile.timezone)).date()
    stored = repo.shareholding_state()
    full = full or not stored
    start = today - timedelta(days=FULL_LOOKBACK_DAYS if full else lookback_days)

    counts = store_patterns(
        repo,
        stored=stored,
        start=start,
        end=today,
        timezone=profile.timezone,
        index_loader=index_loader or shareholding.fetch_index_records,
        fetcher=fetcher or PacedFetcher(),
        time_budget_seconds=time_budget_seconds,
        clock=clock,
        dry_run=dry_run,
    )
    counts["deals"] = store_deals(
        repo,
        start=start,
        end=today,
        deals_loader=deals_loader or shareholding.fetch_deals,
        dry_run=dry_run,
    )
    logger.info(
        "Shareholding done: %s%s", counts, " (dry run, nothing written)" if dry_run else ""
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="read this many days back (default: %(default)s)",
    )
    parser.add_argument("--full", action="store_true", help="read back to the 2022 format")
    parser.add_argument(
        "--time-budget-minutes",
        type=float,
        default=None,
        help="stop fetching patterns once this much time is spent",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(
        DashboardRepository.from_environment(args.market),
        lookback_days=args.lookback_days,
        full=args.full,
        time_budget_seconds=(
            args.time_budget_minutes * 60 if args.time_budget_minutes else None
        ),
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
