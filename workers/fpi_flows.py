"""Where foreign money went: NSDL's fortnightly sector-wise FPI flows, and the
largest foreign deals in single stocks. NSE only, on Cloudflare only.

NSDL publishes a static report each fortnight (15th and month end) with each
sector's FPI net equity investment and holdings, in rupees crore. Its list of
reports is the selection page's dropdown. Sector names follow NSE's
classification from the January 2023 reports on; earlier ones use another
list, so the history starts there (`FIRST_PERIOD_END`).

The R2 object ``live/NSE/fpi-flows.json`` is the store: one row per
fortnight. Each run reads it, adds the fortnights it lacks and rewrites it, so
no table is needed and a report is fetched once. An unreadable object is left
alone.

The deals half is the exchange's bulk and block deals already stored by
workers/shareholding.py, kept to clients whose names mark them as foreign
(`is_foreign_investor`) and netted per client and stock over `DEAL_DAYS`.
A name rule, not a registry: a fund trading under an Indian-sounding vehicle
is missed. Display evidence only: nothing in ``screener/`` reads either.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import Any

from screener.markets import resolve as resolve_market
from screener.numeric import round_half_up, safe_float
from screener.quarterly_results import REQUEST_HEADERS

logger = logging.getLogger(__name__)

SITE = "https://www.fpi.nsdl.co.in/web"
SELECTION_URL = f"{SITE}/Reports/FPI_Fortnightly_Selection.aspx"
FIRST_PERIOD_END = date(2023, 1, 15)
DEAL_DAYS = 30
TOP_DEALS = 5
REQUEST_PAUSE_SECONDS = 0.5

# A jurisdiction in the name is foreign whatever else it says ("... Mauritius Private Limited").
_OFFSHORE = re.compile(
    r"\b(MAURITIUS|SINGAPORE|CAYMAN|LUXEMBOURG|IRELAND|NETHERLANDS|HONG KONG|DELAWARE)\b|\(DE\)", re.I)
_FOREIGN = re.compile(
    r"(\bPTE\b|\bLLC\b|\bPLC\b|\bSE\b|\bS\.?A\.?$|\bSICAV\b|\bODI\b|\bFPI\b|\bINC\.?$|\bL\.?P\.?$|\bAG\b"
    r"|\bB\.V\.?|\bN\.V\.?|\bGMBH\b"
    r"|GOLDMAN SACHS|MORGAN STANLEY|SOCIETE GENERALE|BNP PARIBAS|MERRILL LYNCH|J\.? ?P\.? ?MORGAN|NOMURA"
    r"|\bUBS\b|\bCLSA\b|\bHSBC\b|CITIGROUP|BOFA|BARCLAYS|VANGUARD|ISHARES|BLACKROCK|FIDELITY|NORGES BANK"
    r"|ABU DHABI|GOVERNMENT OF SINGAPORE|MONETARY AUTHORITY|EMERGING MARKETS)", re.I)
_DOMESTIC = re.compile(r"(PRIVATE LIMITED|\bPVT\b|\bLLP\b|MUTUAL FUND|\bHUF\b)", re.I)


def is_foreign_investor(name: str) -> bool:
    """Whether a deal's client name reads as a foreign portfolio investor."""
    name = " ".join(str(name or "").split())
    if _OFFSHORE.search(name):
        return True
    return bool(_FOREIGN.search(name)) and not _DOMESTIC.search(name)


def report_links(selection_html: str) -> list[tuple[date, str]]:
    """Each report's period end and URL, from the selection page's dropdown."""
    links = []
    for value, label in re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>', selection_html):
        try:
            period_end = datetime.strptime(" ".join(label.split()).title(), "%b %d, %Y").date()
        except ValueError:
            continue
        links.append((period_end, f"{SITE}/{value.removeprefix('~/')}"))
    return links


def _spread(row) -> list[str]:
    """A header row's labels, one per column, a merged cell repeated over its span."""
    labels = []
    for cell in row:
        labels += [" ".join(cell.text_content().split())] * int(cell.get("colspan") or 1)
    return labels


def _period(label: str) -> tuple[date, date]:
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2}),\s*(\d{4})", label)
    if not match:
        raise ValueError(f"no period in {label!r}")
    month, first, last, year = match.groups()
    for fmt in ("%B", "%b"):
        try:
            number = datetime.strptime(month, fmt).month
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"no month in {label!r}")
    return date(int(year), number, int(first)), date(int(year), number, int(last))


def _crore(text: str) -> float | None:
    return safe_float(text.replace(",", ""))


def parse_report(html: str) -> dict[str, Any]:
    """One report: the fortnight it covers and each sector's FPI equity net and holdings (rupees crore).

    Columns are found by their headers, not position: the layout gained debt,
    hybrid, fund and AIF columns over the years, and the equity column is the
    first of each rupee block in every one of them.
    """
    import lxml.html

    rows = lxml.html.fromstring(html).xpath("//tr")
    top = next(i for i, row in enumerate(rows) if "Net Investment" in row.text_content())
    groups, currencies, kinds = (_spread(rows[top + k]) for k in range(3))

    def equity_column(prefix: str) -> int:
        label = [g for g in groups if g.startswith(prefix)][-1]
        column = next(i for i, (g, c) in enumerate(zip(groups, currencies)) if g == label and "INR" in c)
        if kinds[column] != "Equity":
            raise ValueError(f"{prefix!r}: column {column} is {kinds[column]!r}, not Equity")
        return column

    net_column, held_column = equity_column("Net Investment"), equity_column("AUC as on")
    start, end = _period([g for g in groups if g.startswith("Net Investment")][-1])
    sectors, total = [], None
    for row in rows[top + 3:]:
        cells = [" ".join(cell.text_content().split()) for cell in row]
        if len(cells) <= max(net_column, held_column):
            continue
        entry = {"net": _crore(cells[net_column]), "held": _crore(cells[held_column])}
        if cells[1] == "Grand Total":
            total = entry
            break
        if cells[0].isdigit():
            sectors.append({"sector": cells[1], **entry})
    if total is None or not sectors:
        raise ValueError("no sector table")
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "sectors": sectors, "total": total}


def top_deals(deals: Iterable[dict[str, Any]], *, limit: int = TOP_DEALS) -> dict[str, list[dict[str, Any]]]:
    """Foreign clients' net deals per client and stock, the largest `limit` bought and sold.

    Netted, so a desk that bought and sold the same stock shows only what it kept.
    """
    held: dict[tuple[str, str], dict[str, Any]] = {}
    for deal in deals:
        if not is_foreign_investor(deal["client_name"]):
            continue
        sign = 1 if str(deal["side"]).upper() == "BUY" else -1
        quantity = int(deal["quantity"])
        when = str(deal["deal_date"])
        entry = held.setdefault((deal["client_name"], deal["symbol"]), {
            "client": " ".join(deal["client_name"].split()), "symbol": deal["symbol"],
            "net": 0.0, "shares": 0, "first": when, "last": when})
        entry["net"] += sign * quantity * float(deal["price"]) / 1e7
        entry["shares"] += sign * quantity
        entry["first"], entry["last"] = min(entry["first"], when), max(entry["last"], when)
    ranked = sorted(
        ({**e, "net": round_half_up(e["net"], 2)} for e in held.values() if e["shares"]),
        key=lambda e: -abs(e["net"]))
    return {
        "bought": [e for e in ranked if e["net"] > 0][:limit],
        "sold": [e for e in ranked if e["net"] < 0][:limit],
    }


def _session():
    import requests

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def fetch_text(url: str, *, session=None, timeout: int = 30) -> str:
    response = (session or _session()).get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def new_fortnights(
    held: Iterable[str], fetch: Callable[[str], str], *, pause: float = REQUEST_PAUSE_SECONDS,
) -> list[dict[str, Any]]:
    """Reports since FIRST_PERIOD_END the object lacks, parsed. A report that fails is left for the next run."""
    held = set(held)
    reports = []
    for period_end, url in report_links(fetch(SELECTION_URL)):
        if period_end < FIRST_PERIOD_END or period_end.isoformat() in held:
            continue
        try:
            reports.append(parse_report(fetch(url)))
        except Exception as exc:  # noqa: BLE001 -- one bad report must not stop the rest
            logger.warning("NSDL report %s not read: %s", url, exc)
        time.sleep(pause)
    return reports


def run(repo, *, fetch: Callable[[str], str] | None = None, today: date | None = None,
        dry_run: bool = False) -> dict[str, int]:
    if resolve_market(repo.market).code != "NSE":
        logger.info("%s has no FPI sector flows; nothing to store", repo.market)
        return {}
    try:
        body = repo.fpi_flows_object()
    except Exception as exc:  # noqa: BLE001 -- unreadable: leave it, never overwrite history with less
        logger.warning("FPI flows object unreadable, not rewritten: %s", exc)
        return {}
    fortnights = {row["period_end"]: row for row in (body or {}).get("rows", [])}
    if fetch is None:
        session = _session()
        fetch = lambda url: fetch_text(url, session=session)  # noqa: E731
    try:
        added = new_fortnights(fortnights, fetch)
    except Exception as exc:  # noqa: BLE001 -- NSDL refused or changed; deals still refresh
        logger.warning("NSDL fortnightly reports not read: %s", exc)
        added = []
    fortnights.update({row["period_end"]: row for row in added})

    since = ((today or date.today()) - timedelta(days=DEAL_DAYS)).isoformat()
    deals = top_deals(repo.bulk_block_deals_since(since))
    names = repo.company_names(sorted({d["symbol"] for side in deals.values() for d in side}))
    for side in deals.values():
        for deal in side:
            deal["company"] = names.get(deal["symbol"])

    if not dry_run:
        repo.put_fpi_flows_object([fortnights[key] for key in sorted(fortnights)], deals=deals, deals_since=since)
    count = sum(map(len, deals.values()))
    logger.info("FPI flows: %d new fortnights, %d held; %d foreign deals%s", len(added), len(fortnights), count,
                " (dry run, nothing written)" if dry_run else "")
    return {"fortnights": len(added), "deals": count}


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
