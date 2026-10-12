"""Record what happened to a company, for the dashboard's notification bell.

Display evidence only, like the statements this runs after: nothing here is
read by a score, a rating or a rank.

Every event is derived from data another job already collects, so this worker
fetches almost nothing and can be re-run at any time. An event is identified by
``(market, kind, symbol, event_key)`` and written once; seeing the same thing
on the next run writes nothing, and the first sighting keeps its timestamp.

Two kinds so far:

``results``
    Where the market has an index of results filings (NSE), one event per
    company and quarter, timed at the filing's broadcast. A revision is not an
    event: it restates a quarter, it does not announce one.

    Where it has none (US), the event is the stored statements gaining a later
    quarter, which is when the vendor published it. That needs to know what
    was there before, so the first time a company is seen its current quarter
    is recorded as a hidden *baseline* rather than announced -- otherwise the
    first run would announce a result for every company in the universe.

``transcript``
    An earnings-call transcript stored by the transcript worker in the last
    few days.

Adding a kind is one function that returns rows and one line in ``run``.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from screener import quarterly_results
from screener.markets import resolve as resolve_market

logger = logging.getLogger(__name__)

KIND_RESULTS = "results"
KIND_TRANSCRIPT = "transcript"

# How far back a run looks for things to record. Longer than the gap between
# runs by a wide margin, so a few failed runs lose nothing.
RECENT_DAYS = 7
RETENTION_DAYS = 180
# A filing for a quarter that ended longer ago than this is a late or repeated
# submission, not this season's result.
MAX_QUARTER_AGE_DAYS = 200


def _event(
    symbol: str,
    kind: str,
    key: str,
    occurred_at: datetime | str,
    detail: dict[str, Any],
    companies: dict[str, str | None],
    *,
    baseline: bool = False,
) -> dict[str, Any]:
    if isinstance(occurred_at, datetime):
        occurred_at = occurred_at.astimezone(UTC).isoformat(timespec="seconds")
    return {
        "symbol": symbol,
        "company": companies.get(symbol),
        "kind": kind,
        "event_key": key,
        "occurred_at": occurred_at,
        "detail": detail,
        "baseline": baseline,
    }


def filed_results_events(
    records: Iterable[dict[str, Any]],
    universe: set[str],
    companies: dict[str, str | None],
    *,
    since: datetime,
    timezone: str,
) -> list[dict[str, Any]]:
    """One event per company and quarter first filed at or after ``since``."""
    local = ZoneInfo(timezone)
    events = []
    for (symbol, period), filed in sorted(
        quarterly_results.first_filings(records).items(), key=lambda item: item[1]
    ):
        # The exchange stamps filings in its own local time.
        filed_at = filed.replace(tzinfo=local)
        if symbol not in universe or filed_at < since:
            continue
        if (filed_at.date() - period).days > MAX_QUARTER_AGE_DAYS:
            continue
        events.append(
            _event(
                symbol,
                KIND_RESULTS,
                period.isoformat(),
                filed_at,
                {"period": period.isoformat(), "source": "filing"},
                companies,
            )
        )
    return events


def statement_results_events(
    state: dict[str, dict[str, Any]],
    recorded: dict[str, str],
    companies: dict[str, str | None],
) -> list[dict[str, Any]]:
    """An event where the stored statements gained a quarter since last recorded."""
    events = []
    for symbol, row in sorted(state.items()):
        quarter = str(row.get("latest_quarter") or "")[:10]
        fetched_at = row.get("fetched_at")
        if not quarter or not fetched_at:
            continue
        previous = recorded.get(symbol)
        if previous is not None and quarter <= previous:
            continue
        events.append(
            _event(
                symbol,
                KIND_RESULTS,
                quarter,
                str(fetched_at),
                {"period": quarter, "source": "vendor"},
                companies,
                # First sighting: there is nothing to compare it with, so it
                # is recorded for next time and not announced.
                baseline=previous is None,
            )
        )
    return events


def transcript_events(
    rows: Iterable[dict[str, Any]], companies: dict[str, str | None]
) -> list[dict[str, Any]]:
    events = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        created_at = row.get("created_at")
        if not symbol or not created_at:
            continue
        call_date = str(row.get("call_date") or "")[:10] or None
        quarter = str(row.get("quarter") or "").strip() or None
        events.append(
            _event(
                symbol,
                KIND_TRANSCRIPT,
                call_date or quarter or str(created_at)[:10],
                str(created_at),
                {"call_date": call_date, "quarter": quarter},
                companies,
            )
        )
    return events


def _universe(repo, companies: dict[str, str | None]) -> set[str]:
    """Every symbol with a stock page: rated names and unrated new listings."""
    symbols = set(companies)
    try:
        symbols.update(repo.new_listing_symbols())
    except Exception as exc:  # table not deployed yet: rated names only
        logger.warning("New listings unavailable (%s); rated names only", exc)
    return symbols


def _local_date(moment: datetime, timezone: str) -> date:
    return moment.astimezone(ZoneInfo(timezone)).date()


def run(
    repo,
    *,
    now: datetime | None = None,
    index_records_loader=None,
    dry_run: bool = False,
) -> dict[str, int]:
    profile = resolve_market(repo.market)
    now = now or datetime.now(UTC)
    since = now - timedelta(days=RECENT_DAYS)
    counts = {"results": 0, "transcript": 0, "baseline": 0, "written": 0}

    try:
        recorded = repo.recorded_event_keys(KIND_RESULTS)
    except Exception as exc:
        logger.warning(
            "%s events not recorded: market_events is unreadable (%s). Apply "
            "storage/notifications_schema.sql.",
            profile.code,
            exc,
        )
        return counts

    companies = repo.snapshot_companies()
    events: list[dict[str, Any]] = []

    if profile.quarterly_results_provider:
        loader = index_records_loader or quarterly_results.fetch_index_records
        try:
            records = loader(
                _local_date(since, profile.timezone), _local_date(now, profile.timezone)
            )
        except Exception as exc:  # the other kinds are still worth recording
            logger.warning("Results filing index unavailable (%s)", exc)
            records = []
        events += filed_results_events(
            records,
            _universe(repo, companies),
            companies,
            since=since,
            timezone=profile.timezone,
        )
    else:
        events += statement_results_events(
            repo.financial_statement_state(), recorded, companies
        )

    try:
        events += transcript_events(
            repo.recent_transcripts(since.isoformat(timespec="seconds")), companies
        )
    except Exception as exc:
        logger.warning("Transcripts unavailable (%s)", exc)

    for event in events:
        counts["baseline" if event["baseline"] else event["kind"]] += 1
    if events and not dry_run:
        counts["written"] = repo.insert_market_events(events)
        repo.prune_market_events(
            (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
        )
    logger.info(
        "%s events: %s%s",
        profile.code, counts, " (dry run, nothing written)" if dry_run else "",
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default=None, help="NSE or US (default: $MARKET)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
