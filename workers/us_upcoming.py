"""US upcoming results dates, from Alpha Vantage's earnings calendar, into ``upcoming_events``.

One request a day returns every US company's next report date as CSV
(``EARNINGS_CALENDAR&horizon=3month``). Only stocks in the US universe are stored,
and only the date and the timing (before or after the market); no estimate is kept.
NSE's rows are the Quarterly filings workflow's (``workers.upcoming_events``) and are
never touched: a US repository is scoped to ``market = 'US'``.

Alpha Vantage free key: personal, non-commercial use only (ToS s.2a); if the dashboard
gains other viewers, this source must be dropped or licensed.

A missing key, a refusal (the API answers 200 with a JSON note) or an empty calendar
warns and writes nothing, so the step stays green and stored dates stand.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import os
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from workers.upcoming_events import merge

logger = logging.getLogger(__name__)

URL = "https://www.alphavantage.co/query"
KEY_ENV = "ALPHAVANTAGE_API_KEY"
TIMEOUT_SECONDS = 60
# The 3-month calendar holds ~3,500 rows (1 Nov 2026); a short one is partial, and merge would clear every missing stock.
MIN_CALENDAR_ROWS = 1000
# Alpha Vantage's timing field, where the calendar carries one.
TIMING = {"pre-market": "Before market open", "post-market": "After market close"}


def parse_calendar(text: str, universe: Iterable[str], *, today: date) -> dict[str, dict[str, Any]]:
    """Each universe stock's next report date (today or later), from the calendar CSV.

    A refusal is JSON, not CSV, so it has no ``symbol`` column and yields nothing.
    """
    names = {str(s).upper().replace(".", "-"): str(s) for s in universe}
    found: dict[str, dict[str, Any]] = {}
    for record in csv.DictReader(io.StringIO(text)):
        symbol = names.get(str(record.get("symbol") or "").strip().upper().replace(".", "-"))
        try:
            day = date.fromisoformat(str(record.get("reportDate") or "").strip())
        except ValueError:
            continue
        if symbol is None or day < today or (symbol in found and found[symbol]["next_result_date"] <= day.isoformat()):
            continue
        timing = str(record.get("timeOfTheDay") or "").strip().lower()
        found[symbol] = {"next_result_date": day.isoformat(), "result_purpose": TIMING.get(timing)}
    return found


def fetch_calendar(key: str) -> str:
    import requests

    response = requests.get(URL, params={"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": key}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def run(repo, *, now: datetime | None = None, dry_run: bool = False, fetch=fetch_calendar) -> dict[str, int]:
    counts = {"calendar": 0, "rows": 0, "written": 0}
    if repo.market != "US":
        logger.warning("US upcoming results are written for the US only (market %s)", repo.market)
        return counts
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        logger.warning("US upcoming results skipped: %s is not set", KEY_ENV)
        return counts
    now = now or datetime.now(UTC)
    try:
        companies = repo.snapshot_companies()
        stored = repo.upcoming_events()
        text = fetch(key)
        rows_in_calendar = sum(1 for _ in csv.DictReader(io.StringIO(text)))
        found = parse_calendar(text, companies, today=now.date())
    except Exception as exc:  # noqa: BLE001 -- display evidence: a failure must not fail the workflow
        # An HTTP error's message carries the request URL, which holds the key.
        logger.warning("US upcoming results not stored: %s", str(exc).replace(key, "***"))
        return counts
    counts["calendar"] = len(found)
    if rows_in_calendar < MIN_CALENDAR_ROWS or not found:
        logger.warning("US upcoming results: the calendar has %s rows (a refusal, a limit or a partial file); stored dates stand", rows_in_calendar)
        return counts
    for symbol, row in found.items():
        row["company"] = companies.get(symbol)
    rows = merge(stored, found, {}, today=now.date(), checked_at=now)
    counts["rows"] = len(rows)
    if rows and not dry_run:
        counts["written"] = repo.upsert_upcoming_events(rows)
    logger.info("US upcoming results: %s%s", counts, " (dry run, nothing written)" if dry_run else "")
    return counts


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="US", help="US (NSE's dates come from workers.upcoming_events)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
