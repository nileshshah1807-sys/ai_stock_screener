"""Daily FII/DII cash-market flows (NSE), on Cloudflare only.

NSE's ``fiidiiTradeReact`` serves the day's provisional cash-market buy, sell
and net value of FIIs/FPIs and DIIs, in rupees crore. Today only: NSE keeps no
archive of it, so history starts the day this step was switched on.

Rows go to the D1 table ``fii_dii_flows`` (``storage/d1/market_flows.sql``;
the workflow routes it with ``TABLE_BACKEND_D1``), keyed (market,
session_date, category), and to ``live/NSE/fii-dii-flows.json`` on R2, rebuilt
from the table whenever it is behind it. A session already stored is not
written again, so the step can ride a workflow that runs every 15 minutes.
Display evidence only: nothing in ``screener/`` reads it.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from screener.markets import resolve as resolve_market
from screener.numeric import safe_float
from screener.quarterly_results import REQUEST_HEADERS

logger = logging.getLogger(__name__)

FLOWS_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
FLOW_CATEGORIES = {"FII/FPI": "FII", "FII": "FII", "DII": "DII"}


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


def _session():
    import requests

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def fetch_flows(*, session=None, timeout: int = 30) -> list[dict[str, Any]]:
    response = (session or _session()).get(FLOWS_URL, timeout=timeout)
    response.raise_for_status()
    return response.json()


def run(
    repo,
    *,
    flows_loader: Callable[[], list[dict[str, Any]]] = fetch_flows,
    dry_run: bool = False,
) -> dict[str, int]:
    if resolve_market(repo.market).code != "NSE":
        logger.info("%s publishes no FII/DII flows; nothing to store", repo.market)
        return {}
    latest = repo.latest_flow_session()
    try:
        flows = parse_flows(flows_loader())
    except Exception as exc:  # noqa: BLE001 -- a refusal or a changed page; display evidence, the next run asks again
        logger.warning("FII/DII flows not read: %s", exc)
        flows = []
    flows = [row for row in flows if latest is None or row["session_date"] > latest]
    if not dry_run:
        if flows:
            repo.upsert_fii_dii_flows(flows)
        # Rebuilt from the table whenever the object is behind it, so a missed R2 write heals next run.
        repo.sync_fii_dii_object()
    logger.info("FII/DII flows: %d new%s", len(flows), " (dry run, nothing written)" if dry_run else "")
    return {"flows": len(flows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
