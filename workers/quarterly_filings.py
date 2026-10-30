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
  which therefore never announce a result the page cannot show;
* the trailing-year lines of ``valuation_basis`` (`refresh_valuation_basis`),
  so the dashboard's P/E moves minutes after a company files rather than at
  the next evening run.

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
read the same document. One that is a half year's statement, not a quarter's,
is read from the quarter's latest earlier filing instead, where there is one
(`earlier_quarter_statement`).

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

from screener import quarterly_results, valuation_basis
from screener.markets import resolve as resolve_market
from screener.numeric import safe_float
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
# The screener's QUARTERLY_RESULTS_MAX_AGE_DAYS default: the newest quarter a
# trailing year may end on, the evening run's rule.
TRAILING_MAX_AGE_DAYS = 200


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


def _text(value: Any) -> str | None:
    """A stored text field: None for anything missing, NaN included."""
    return value if isinstance(value, str) and value else None


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
        "viewer_url": _text(row.get("Viewer_URL")),
        "company": _text(row.get("Company")),
        "lines": lines,
        "parser_version": quarterly_results.PARSER_VERSION,
        "parsed_at": parsed_at,
    }


def earlier_quarter_statement(
    filings: list[dict[str, Any]], fetcher
) -> tuple[dict[str, Any], str | None] | None:
    """The newest of a quarter's earlier filings that is a quarter's statement.

    A half-year statement filed as a revision of the quarter's filing (J&KBANK,
    Sep 2026) does not restate the quarter: its figures are still the ones the
    revised filing gave. Returns that filing and its text, the filing and None
    where a document could not be fetched (asked for again next run), or None
    where no earlier filing is a quarter's.
    """
    for candidate in filings:
        text = fetcher.fetch_many([candidate["XBRL_URL"]])[0]
        if text is None or quarterly_results.covers_a_quarter(text):
            return candidate, text
    return None


def derived_quarters(repo, half_years: list[tuple[dict[str, Any], str]]) -> list[dict[str, Any]]:
    """Stored half-year documents, each as the quarter it ends with.

    MTARTECH, Sep 2026, filed only the half year; the feed view hides a row
    with no revenue or profit, so the company had no result. The quarter is
    the half year less the first quarter, where that is stored on the same
    basis. A company that never filed the quarter (an SME reporting half
    yearly) keeps its row with no lines.
    """
    if not half_years:
        return []
    stored = repo.quarterly_filings({row["symbol"] for row, _ in half_years})
    out = []
    for row, text in half_years:
        earlier = {
            date.fromisoformat(str(f["period_end"])[:10]): f["lines"]
            for f in stored.get(row["symbol"], [])
            if bool(f["is_consolidated"]) == row["is_consolidated"]
        }
        lines = quarterly_results.quarter_from_cumulative(
            quarterly_results.parse_filing(text, row["taxonomy"], cumulative=True),
            quarterly_results.statement_days(text),
            date.fromisoformat(row["period_end"]),
            earlier,
        )
        if lines:
            out.append({**row, "lines": lines})
    return out


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
    counts = {"due": 0, "stored": 0, "failed": 0, "deferred": 0, "redrawn": 0, "basis": 0, "derived": 0}
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
    earlier: dict[tuple[str, str, bool], list[dict[str, Any]]] = {}
    for row in quarterly_results.normalise_index(records, latest_only=False).to_dict("records"):
        key = (row["Symbol"], row["Period_End"].isoformat(), bool(row["Is_Consolidated"]))
        earlier.setdefault(key, []).insert(0, row)  # newest first
    first = quarterly_results.first_filings(records)
    due = due_filings(index, stored)
    counts["due"] = len(due)
    logger.info(
        "%s results filings: %d in the index over %d day(s), %d stored, %d to fetch",
        profile.code, len(index), lookback_days, len(stored), len(due),
    )

    fetcher = fetcher or quarterly_results.DocumentFetcher(workers=FETCH_WORKERS)
    touched: list[str] = []
    half_years: list[tuple[dict[str, Any], str]] = []
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
            key = (row["Symbol"], row["Period_End"].isoformat(), bool(row["Is_Consolidated"]))
            source = row
            if text is not None and not quarterly_results.covers_a_quarter(text):
                found = earlier_quarter_statement(
                    [f for f in earlier.get(key, []) if f["Seq_Id"] != row["Seq_Id"]], fetcher
                )
                if found is not None:
                    source, text = found
            if text is None:
                counts["failed"] += 1
                continue
            rows.append(
                filing_row(
                    # Stored under the latest filing's id, so it is not due
                    # again until the exchange files something newer.
                    {**source, "Seq_Id": row["Seq_Id"]},
                    quarterly_results.parse_filing(text, source["Taxonomy"]),
                    broadcast=first.get((row["Symbol"], row["Period_End"])),
                    stored_broadcast=(stored.get(key) or {}).get("broadcast_at"),
                    timezone=profile.timezone,
                    parsed_at=parsed_at,
                )
            )
            if not quarterly_results.covers_a_quarter(text):
                half_years.append((rows[-1], text))
        if rows and not dry_run:
            repo.upsert_quarterly_filings(rows)
        counts["stored"] += len(rows)
        touched += [row["symbol"] for row in rows]

    # After the loop, so the quarters a half year is read against are stored
    # whatever order the batches ran in.
    derived = [] if dry_run else derived_quarters(repo, half_years)
    if derived:
        repo.upsert_quarterly_filings(derived)
        counts["derived"] = len(derived)

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
    if not index.empty and not dry_run:
        try:
            counts["basis"] = refresh_valuation_basis(
                repo, index["Symbol"], today, profile.timezone
            )
        except Exception as exc:  # stored filings stand; the evening run writes the basis
            logger.warning(
                "Valuation basis not refreshed (apply storage/valuation_basis_schema.sql "
                "if the table is missing): %s",
                exc,
            )
    logger.info(
        "%s results filings done: %s%s",
        profile.code, counts, " (dry run, nothing written)" if dry_run else "",
    )
    return counts


def refresh_valuation_basis(repo, symbols: Iterable[str], today: date, timezone: str) -> int:
    """Replace the trailing-year lines of each symbol's valuation basis.

    The arithmetic is the evening run's (`valuation_basis.trailing_year`). A
    stored basis that runs to a later quarter -- the vendor's, where its
    filings are behind -- is left alone, and a line the filings cannot
    support is not written, so the stored figure stands. Every run covers the
    whole lookback window, which also restores a year the evening publisher
    wrote from filings read before a company filed.
    """
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return 0
    rows = [
        {**row, **(row.get("lines") or {})}
        for filings in repo.quarterly_filings(symbols).values()
        for row in filings
    ]
    facts = quarterly_results.facts_frame(rows, timezone)
    trailing = valuation_basis.trailing_year(
        facts, symbols, today=today, max_age_days=TRAILING_MAX_AGE_DAYS
    )
    held = repo.valuation_basis_periods(trailing["Symbol"])
    updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    # PostgREST takes one set of keys per request, so rows are grouped by the
    # lines they carry.
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for record in trailing.to_dict("records"):
        period = record["TTM_Period_End"]
        if (held.get(record["Symbol"]) or "") > period:
            continue
        row = {
            "symbol": record["Symbol"],
            "period_end": period,
            "statement_basis": record["TTM_Basis"],
            "source": valuation_basis.FILINGS_SOURCE,
            "updated_at": updated_at,
        }
        for column, line in (
            ("net_profit_ttm", "TTM_Net_Profit"),
            ("ebitda_ttm", "TTM_EBITDA"),
            ("revenue_ttm", "TTM_Revenue"),
        ):
            value = safe_float(record[line])
            if value is not None:
                row[column] = value
        groups.setdefault(tuple(sorted(row)), []).append(row)
    return sum(repo.upsert_valuation_basis(group) for group in groups.values())


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
