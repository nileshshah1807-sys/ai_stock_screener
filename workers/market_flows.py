"""Daily FII/DII cash flows and participant-wise F&O open interest (NSE).

Two public NSE files, read once a session:

* ``fiidiiTradeReact``: the day's provisional cash-market buy, sell and net
  value of FIIs/FPIs and DIIs, in rupees crore. Today only; NSE keeps no
  archive of it, so it cannot be backfilled.
* ``fao_participant_oi_DDMMYYYY.csv``: open interest in equity derivatives by
  participant (Client, DII, FII, Pro), long and short per instrument, in
  contracts. NSE's archive serves about a year; a day it did not trade is a 404.

Rows go to ``fii_dii_flows`` and ``participant_oi``, keyed (market,
session_date, category), and to ``live/NSE/<name>.json`` on R2. A session
already stored is not written again, so the step can ride a workflow that runs
every 15 minutes. Display evidence only: nothing in ``screener/`` reads it.
Tables: ``storage/market_flows_schema.sql``.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from screener.markets import resolve as resolve_market
from screener.numeric import safe_float
from screener.quarterly_results import REQUEST_HEADERS

logger = logging.getLogger(__name__)

FLOWS_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
OI_URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{day:%d%m%Y}.csv"
FLOW_CATEGORIES = {"FII/FPI": "FII", "FII": "FII", "DII": "DII"}
OI_CATEGORIES = ("Client", "DII", "FII", "Pro")
OI_COLUMNS = {
    "Future Index Long": "future_index_long",
    "Future Index Short": "future_index_short",
    "Future Stock Long": "future_stock_long",
    "Future Stock Short": "future_stock_short",
    "Option Index Call Long": "option_index_call_long",
    "Option Index Put Long": "option_index_put_long",
    "Option Index Call Short": "option_index_call_short",
    "Option Index Put Short": "option_index_put_short",
    "Option Stock Call Long": "option_stock_call_long",
    "Option Stock Put Long": "option_stock_put_long",
    "Option Stock Call Short": "option_stock_call_short",
    "Option Stock Put Short": "option_stock_put_short",
    "Total Long Contracts": "total_long",
    "Total Short Contracts": "total_short",
}
LOOKBACK_DAYS = 7  # catches up a missed evening or a long weekend
BACKFILL_DAYS = 370
PAUSE_SECONDS = 0.5  # between archive files, so a backfill does not hammer NSE


def parse_flows(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per category from the cash-market payload; other categories are skipped."""
    rows = []
    for item in payload or []:
        category = FLOW_CATEGORIES.get(str(item.get("category", "")).replace("*", "").strip())
        if category is None:
            continue
        rows.append({
            "session_date": datetime.strptime(item["date"].strip(), "%d-%b-%Y").date().isoformat(),
            "category": category,
            "buy_value": safe_float(item.get("buyValue")),
            "sell_value": safe_float(item.get("sellValue")),
            "net_value": safe_float(item.get("netValue")),
        })
    return rows


def parse_oi(text: str, day: date) -> list[dict[str, Any]]:
    """One row per participant from the archive CSV (its TOTAL row is left out)."""
    rows, header = [], None
    for record in csv.reader(io.StringIO(text)):
        cells = [cell.strip() for cell in record]
        if cells and cells[0] == "Client Type":
            if set(OI_COLUMNS) - set(cells):
                raise ValueError(f"participant OI file for {day} has columns this parser does not read")
            header = cells
        elif header and cells and cells[0] in OI_CATEGORIES:
            values = dict(zip(header, cells))
            rows.append({
                "session_date": day.isoformat(),
                "category": cells[0],
                **{column: int(float(values[name])) for name, column in OI_COLUMNS.items()},
            })
    if header is None:
        raise ValueError(f"participant OI file for {day} has no header")
    return rows


def _session():
    import requests

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def fetch_flows(*, session=None, timeout: int = 30) -> list[dict[str, Any]]:
    response = (session or _session()).get(FLOWS_URL, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_oi(day: date, *, session=None, timeout: int = 30) -> str | None:
    """The day's participant OI CSV, or None when NSE has none (no session, not yet out)."""
    response = (session or _session()).get(OI_URL.format(day=day), timeout=timeout)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content.decode("utf-8-sig", "replace")


def due_days(latest: str | None, today: date, *, backfill: bool) -> list[date]:
    """Weekdays after the latest stored session, up to today, within the window."""
    start = today - timedelta(days=BACKFILL_DAYS if backfill else LOOKBACK_DAYS)
    if latest and not backfill:
        start = max(start, date.fromisoformat(latest))
    days = (start + timedelta(days=n) for n in range(1, (today - start).days + 1))
    return [day for day in days if day.weekday() < 5]


def run(
    repo,
    *,
    today: date | None = None,
    backfill: bool = False,
    flows_loader: Callable[[], list[dict[str, Any]]] = fetch_flows,
    oi_loader: Callable[[date], str | None] = fetch_oi,
    sleep: Callable[[float], None] = time.sleep,
    dry_run: bool = False,
) -> dict[str, int]:
    profile = resolve_market(repo.market)
    if profile.code != "NSE":
        logger.info("%s publishes no FII/DII flows; nothing to store", profile.code)
        return {}
    today = today or datetime.now(ZoneInfo(profile.timezone)).date()

    latest = repo.latest_flow_session("fii_dii_flows")
    try:
        payload = flows_loader()
    except Exception as exc:  # noqa: BLE001 -- display evidence; the next run asks again
        logger.warning("FII/DII flows not read: %s", exc)
        payload = []
    flows = [row for row in parse_flows(payload) if latest is None or row["session_date"] > latest]

    oi: list[dict[str, Any]] = []
    for n, day in enumerate(due_days(repo.latest_flow_session("participant_oi"), today, backfill=backfill)):
        if n:
            sleep(PAUSE_SECONDS)
        try:
            text = oi_loader(day)
        except Exception as exc:  # noqa: BLE001 -- stored so far is kept; the next run resumes here
            logger.warning("Participant OI for %s not read, stopping: %s", day, exc)
            break
        if text is not None:
            oi += parse_oi(text, day)

    if not dry_run:
        if flows:
            repo.upsert_market_flows("fii_dii_flows", flows)
        if oi:
            repo.upsert_market_flows("participant_oi", oi)
    counts = {"flows": len(flows), "oi": len(oi), "oi_sessions": len({row["session_date"] for row in oi})}
    logger.info("Market flows: %s%s", counts, " (dry run, nothing written)" if dry_run else "")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--backfill", action="store_true",
                        help=f"read the participant OI archive {BACKFILL_DAYS} days back (flows have no archive)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), backfill=args.backfill, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
