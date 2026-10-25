"""Store the results and shareholding filings of companies listed on BSE alone.

NSE's filings reach none of them, so their quarters would otherwise come only
from the vendor, a quarter late. ``workers.bse_source`` fetches from BSE; this
module turns what it returns into the index records ``workers.quarterly_filings``
and ``workers.shareholding`` already read, and hands them to those workers. So
a BSE filing is stored, revised, parsed and shown exactly as an NSE one is --
the stock page, the Results page, the Shareholding tab, the bell and the
screener's growth need nothing new -- under the run's own symbol, ``SYMBOL.BO``.

Only companies the screener carries as BSE-only are kept: a company on both
exchanges is NSE's, and its NSE filing is already stored.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from screener.markets import BSE_SUFFIX, NSE, is_bse_only
from screener.markets import resolve as resolve_market
from workers import bse_source, quarterly_filings
from workers import shareholding as shareholding_worker

logger = logging.getLogger(__name__)

# NSE's index serves its dates in these shapes, and its parsers read them.
_DAY = "%d-%b-%Y"
_STAMP = "%d-%b-%Y %H:%M:%S"


class SourceFetcher:
    """The workers' document fetcher, over ``bse_source.fetch_document``."""

    def fetch_one(self, url: str) -> str | None:
        try:
            return bse_source.fetch_document(url)
        except NotImplementedError:
            raise
        except Exception as exc:  # one document is not the run; asked for again next run
            logger.warning("BSE document %s not fetched: %s", url, exc)
            return None

    def fetch_many(self, urls: list[str]) -> list[str | None]:
        return [self.fetch_one(url) for url in urls]


def results_record(filing: dict[str, Any]) -> dict[str, Any]:
    """A BSE results filing as an NSE integrated-filing index record."""
    return {
        "symbol": f"{str(filing['symbol']).strip().upper()}{BSE_SUFFIX}",
        "qe_Date": filing["period_end"].strftime(_DAY),
        "broadcast_Date": filing["filed_at"].strftime(_STAMP),
        "seq_Id": f"bse:{filing['filing_id']}",
        "consolidated": "Consolidated" if filing["consolidated"] else "Standalone",
        "xbrl": filing["xbrl_url"],
        "taxonomy": filing["taxonomy"],
        "cmName": filing.get("company"),
    }


def shareholding_record(filing: dict[str, Any]) -> dict[str, Any]:
    """A BSE shareholding filing as an NSE shareholding index record."""
    return {
        "symbol": f"{str(filing['symbol']).strip().upper()}{BSE_SUFFIX}",
        "date": filing["period_end"].strftime(_DAY),
        "broadcastDate": filing["filed_at"].strftime(_STAMP),
        "recordId": f"bse:{filing['filing_id']}",
        "xbrl": filing["xbrl_url"],
        "name": filing.get("company"),
    }


def _loader(fetch, convert, carried: set[str]):
    def load(start: date, end: date) -> list[dict[str, Any]]:
        records = [convert(filing) for filing in fetch(start, end)]
        return [record for record in records if record["symbol"] in carried]
    return load


def run(
    repo,
    *,
    today: date | None = None,
    lookback_days: int = quarterly_filings.DEFAULT_LOOKBACK_DAYS,
    full: bool = False,
    time_budget_seconds: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    profile = resolve_market(repo.market)
    if profile.code != NSE:
        logger.info("%s carries no BSE-only companies; nothing to store", profile.code)
        return {}
    carried = {symbol for symbol in repo.latest_snapshot_symbols() if is_bse_only(symbol)}
    if not carried:
        logger.info("The screener carries no BSE-only companies; nothing to store")
        return {}

    today = today or datetime.now(ZoneInfo(profile.timezone)).date()
    fetcher = SourceFetcher()
    counts: dict[str, Any] = {"companies": len(carried)}
    try:
        counts["results"] = quarterly_filings.run(
            repo,
            index_records_loader=_loader(bse_source.results_filings, results_record, carried),
            fetcher=fetcher,
            today=today,
            lookback_days=lookback_days,
            full=full,
            time_budget_seconds=time_budget_seconds,
            dry_run=dry_run,
        )
        start = today - timedelta(
            days=shareholding_worker.FULL_LOOKBACK_DAYS if full else lookback_days
        )
        counts["shareholding"] = shareholding_worker.store_patterns(
            repo,
            stored=repo.shareholding_state(),
            start=start,
            end=today,
            timezone=profile.timezone,
            index_loader=_loader(
                bse_source.shareholding_filings, shareholding_record, carried
            ),
            fetcher=fetcher,
            time_budget_seconds=time_budget_seconds,
            clock=time.monotonic,
            dry_run=dry_run,
        )
    except NotImplementedError as exc:
        logger.warning("BSE filings not stored: %s (see workers/bse_source.py)", exc)
        counts["status"] = "source_not_written"
    logger.info("BSE filings done: %s", counts)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--lookback-days", type=int, default=quarterly_filings.DEFAULT_LOOKBACK_DAYS
    )
    parser.add_argument("--full", action="store_true", help="read back as far as the NSE workers do")
    parser.add_argument("--time-budget-minutes", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(
        DashboardRepository.from_environment(NSE),
        lookback_days=args.lookback_days,
        full=args.full,
        time_budget_seconds=args.time_budget_minutes * 60 if args.time_budget_minutes else None,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
