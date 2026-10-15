"""Store every quarterly results filing the exchange publishes, parsed once.

Where the market has an index of results filings (NSE), this is the one job
that reads it and the documents it links to. Each filing is fetched once,
parsed into the quarter's income statement (`screener.quarterly_results.
parse_filing`) and stored in ``quarterly_filings``. Everything else reads that
table and fetches nothing:

* the stock page's quarterly results (`workers.financial_statements`), which
  this job redraws for every company it stored a filing for, so a result is
  on the page within one run of being filed;
* the screener's latest-quarter growth (`screener.quarterly_results`);
* the notification bell's "results filed" events (`workers.market_events`),
  which therefore never announce a result the page cannot show.

A run is cheap when nothing is new: one page of the index for the last few
days, compared with what is stored, and no document fetched. The Quarterly
filings workflow runs it every quarter of an hour (dispatched by cron-job.org,
not GitHub's schedule), so a result filed this evening reaches the table, the
page and the bell this evening.

What counts as new, per (symbol, quarter, basis):

* nothing stored yet;
* a different filing id -- a revision, which replaces the original;
* a row parsed by an older ``PARSER_VERSION``, so a parser fix reaches every
  stored quarter, not only what is filed after it.

A document that cannot be fetched is not stored and is asked for again on the
next run. One that parses to nothing is stored as it is: asking again would
read the same document.

The index is read for the last ``--lookback-days`` (revisions appear in it on
the day they are made); a run that finds the table empty, or is given
``--full``, reads the whole window the exchange serves, which is how the
table is first built and how a filing missed by every short run is still
picked up by the daily full sweep.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from screener import quarterly_results
from screener.markets import resolve as resolve_market
from workers.financial_statements import recompose_quarters

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 7
# How far back the exchange's index is read on a full sweep. It begins in
# April 2025, so a longer window finds nothing more.
FULL_LOOKBACK_DAYS = 600
# Documents fetched between writes: a run stopped by its time budget keeps
# everything it parsed before the stop.
BATCH_SIZE = 60
FETCH_WORKERS = 6


def due_filings(
    index: pd.DataFrame, stored: dict[tuple[str, str, bool], dict[str, Any]]
) -> list[dict[str, Any]]:
    """Index rows whose filing is not stored as it now stands, newest first."""
    if index is None or index.empty:
        return []
    readable = index[index["Taxonomy"].isin(quarterly_results.SUPPORTED_TAXONOMIES)]
    due = []
    for row in readable.to_dict("records"):
        key = (row["Symbol"], row["Period_End"].isoformat(), bool(row["Is_Consolidated"]))
        have = stored.get(key)
        if (
            have is None
            or str(have.get("seq_id")) != str(row["Seq_Id"])
            or int(have.get("parser_version") or 0) < quarterly_results.PARSER_VERSION
        ):
            due.append(row)
    # Tonight's results before last year's revisions: a run stopped by its
    # budget has stored what the page and the screener most need.
    due.sort(key=lambda row: row["Filed_At"], reverse=True)
    return due


def _stamp(moment: datetime | None, timezone: str) -> str | None:
    """An exchange-local time as an ISO timestamp with its offset."""
    if moment is None:
        return None
    return moment.replace(tzinfo=ZoneInfo(timezone)).isoformat(timespec="seconds")


def filing_row(
    row: dict[str, Any],
    lines: dict[str, Any],
    *,
    broadcast: datetime | None,
    stored_broadcast: str | None,
    timezone: str,
    parsed_at: str,
) -> dict[str, Any]:
    return {
        "symbol": row["Symbol"],
        "period_end": row["Period_End"].isoformat(),
        "is_consolidated": bool(row["Is_Consolidated"]),
        "seq_id": str(row["Seq_Id"]),
        "filed_at": _stamp(row["Filed_At"], timezone),
        # A short window may hold only a revision; the first broadcast it
        # does not show is the one already stored.
        "broadcast_at": _stamp(broadcast, timezone) or stored_broadcast,
        "taxonomy": row["Taxonomy"],
        "document_url": row["XBRL_URL"],
        "lines": lines,
        "parser_version": quarterly_results.PARSER_VERSION,
        "parsed_at": parsed_at,
    }


def _batches(rows: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def run(
    repo,
    *,
    index_records_loader: Callable[[date, date], list[dict[str, Any]]] | None = None,
    fetcher=None,
    today: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    full: bool = False,
    time_budget_seconds: float | None = None,
    clock=time.monotonic,
    dry_run: bool = False,
) -> dict[str, int]:
    profile = resolve_market(repo.market)
    counts = {"due": 0, "stored": 0, "failed": 0, "deferred": 0, "redrawn": 0}
    if not profile.quarterly_results_provider:
        logger.info("%s has no results filing index; nothing to store", profile.code)
        return counts

    today = today or datetime.now(ZoneInfo(profile.timezone)).date()
    stored = repo.quarterly_filing_state()
    if full or not stored:
        lookback_days = FULL_LOOKBACK_DAYS
    loader = index_records_loader or quarterly_results.fetch_index_records
    records = loader(today - timedelta(days=lookback_days), today)
    index = quarterly_results.normalise_index(records)
    first = quarterly_results.first_filings(records)
    due = due_filings(index, stored)
    counts["due"] = len(due)
    logger.info(
        "%s results filings: %d in the index over %d day(s), %d stored, %d to fetch",
        profile.code, len(index), lookback_days, len(stored), len(due),
    )

    fetcher = fetcher or quarterly_results.DocumentFetcher(workers=FETCH_WORKERS)
    touched: list[str] = []
    started = clock()
    for position, batch in enumerate(_batches(due, BATCH_SIZE)):
        if time_budget_seconds is not None and clock() - started >= time_budget_seconds:
            counts["deferred"] = len(due) - position * BATCH_SIZE
            logger.info(
                "Time budget spent; %d filing(s) left for the next run", counts["deferred"]
            )
            break
        texts = fetcher.fetch_many([row["XBRL_URL"] for row in batch])
        parsed_at = datetime.now(UTC).isoformat(timespec="seconds")
        rows = []
        for row, text in zip(batch, texts, strict=True):
            if text is None:
                counts["failed"] += 1
                continue
            key = (row["Symbol"], row["Period_End"].isoformat(), bool(row["Is_Consolidated"]))
            rows.append(
                filing_row(
                    row,
                    quarterly_results.parse_filing(text),
                    broadcast=first.get((row["Symbol"], row["Period_End"])),
                    stored_broadcast=(stored.get(key) or {}).get("broadcast_at"),
                    timezone=profile.timezone,
                    parsed_at=parsed_at,
                )
            )
        if rows and not dry_run:
            repo.upsert_quarterly_filings(rows)
        counts["stored"] += len(rows)
        touched += [row["symbol"] for row in rows]

    if counts["failed"]:
        logger.warning(
            "%d results document(s) could not be fetched; asked for again next run",
            counts["failed"],
        )
    if touched and not dry_run:
        try:
            counts["redrawn"] = recompose_quarters(repo, touched)
        except Exception as exc:  # stored filings stand; the next run redraws
            logger.warning("Quarterly results not redrawn on the stock page: %s", exc)
    logger.info(
        "%s results filings done: %s%s",
        profile.code, counts, " (dry run, nothing written)" if dry_run else "",
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default=None, help="NSE or US (default: $MARKET)")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="read the index this many days back (default: %(default)s)",
    )
    parser.add_argument(
        "--full", action="store_true", help="read the whole index the exchange serves"
    )
    parser.add_argument(
        "--time-budget-minutes",
        type=float,
        default=None,
        help="stop fetching once this much time is spent (the rest waits for the next run)",
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
