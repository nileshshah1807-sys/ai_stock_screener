"""IPOs on NSE's mainboard and SME board (NSE Emerge), on Cloudflare only.

One row per issue in the D1 table ``ipos`` (status, price band, lot, issue
size, the issue price once fixed, listing day's open and close) and one row per
category and day in ``ipo_subscriptions`` while an issue is open, plus the
final figures the day after it closes. Both tables are in
``storage/d1/ipos.sql``; the workflow routes them with ``TABLE_BACKEND_D1``.
``live/NSE/ipos.json`` on R2 carries the issues of the window with their
subscription by day. Return since listing is the live price over the issue
price, worked out where the price is (the dashboard), as live ratios are.

Sources, all NSE's own pages: ``ipo-current-issue``, ``all-upcoming-issues``,
``public-past-issues`` (back to 2012), ``ipo-detail`` per issue (lot,
category subscription; refetched only while open or incomplete), and the
listing day's bhavcopy for its open and close. No grey-market premium.
BSE SME issues need ``workers/bse_source.py`` (the repo never fetches from BSE)
and are not stored yet. Display evidence: nothing in ``screener/`` reads it.
"""

from __future__ import annotations

import argparse
import logging
import re
import tempfile
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from screener.numeric import safe_float
from screener.quarterly_results import REQUEST_HEADERS

logger = logging.getLogger(__name__)

BASE = "https://www.nseindia.com/api/"
LISTS = {"current": "ipo-current-issue", "upcoming": "all-upcoming-issues?category=ipo", "past": "public-past-issues"}
BOARDS = {"Equity": "mainboard", "EQ": "mainboard", "SME": "sme"}
DETAIL_SERIES = {"mainboard": "EQ", "sme": "SME"}
LISTING_SERIES = frozenset({"EQ", "BE", "SM", "ST", "SZ"})
# Top-level categories of NSE's category table, by its serial number.
CATEGORIES = {"1": "qib", "2": "nii", "2.1": "nii_big", "2.2": "nii_small", "3": "retail", "4": "employee", None: "total"}
WINDOW_DAYS = 45
BACKFILL_DAYS = 365
LISTING_RETRY_DAYS = 7
PAUSE_SECONDS = 0.3  # between issue pages, so a backfill does not hammer NSE


def _date(text: str | None) -> str | None:
    text = (text or "").strip()
    for layout in ("%d-%b-%Y", "%Y-%m-%d"):  # %b matches NOV and Nov alike
        try:
            return datetime.strptime(text, layout).date().isoformat()
        except ValueError:
            continue
    return None


def _prices(text: str | None) -> tuple[float | None, float | None]:
    numbers = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")]
    return (numbers[0], numbers[-1]) if numbers else (None, None)


def _int(value: Any) -> int | None:
    number = safe_float(value)
    return int(number) if number is not None else None


def listed_issue(item: dict[str, Any], status: str) -> dict[str, Any] | None:
    """One issue from a list page as an ``ipos`` row; debt, REITs and InvITs are left out."""
    board = BOARDS.get(str(item.get("series") or item.get("securityType") or "").strip())
    if board is None or not item.get("symbol"):
        return None
    low, high = _prices(item.get("issuePrice") if status != "listed" else item.get("priceRange"))
    return {
        "symbol": item["symbol"].strip(),
        "board": board,
        "company": (item.get("companyName") or "").strip() or None,
        "status": status,
        "issue_start": _date(item.get("issueStartDate") or item.get("ipoStartDate")),
        "issue_end": _date(item.get("issueEndDate") or item.get("ipoEndDate")),
        "price_low": low,
        "price_high": high,
        "issue_price": safe_float(item.get("issuePrice")) if status == "listed" else None,
        "issue_size_shares": _int(item.get("issueSize")),
        "listing_date": _date(item.get("listingDate")),
    }


def parse_detail(detail: dict[str, Any]) -> tuple[dict[str, Any], str | None, list[dict[str, Any]]]:
    """(the fields the list pages lack, the day the figures are as of, the category rows)."""
    info = {row.get("title"): row.get("value") for row in (detail.get("issueInfo") or {}).get("dataList") or []}
    lot = next((info[key] for key in ("Bid Lot", "Lot Size", "Minimum Order Quantity") if info.get(key)), None)
    found = re.search(r"[\d,]+", lot or "")
    graph = detail.get("demandGraph") or {}
    table = detail.get("activeCat") or {}
    stamp = re.search(r"\d{2}-[A-Za-z]{3}-\d{4}", table.get("updateTime") or "")
    rows = []
    for row in table.get("dataList") or []:
        category = CATEGORIES.get(row.get("srNo"), "")
        if not category or row.get("category") == "Category":
            continue
        rows.append({
            "category": category,
            "shares_offered": _int(row.get("noOfShareOffered")),
            "shares_bid": _int(row.get("noOfSharesBid")),
            "times": safe_float(row.get("noOfTotalMeant")),
        })
    fields = {
        "lot_size": int(found.group().replace(",", "")) if found else None,
        "issue_size_shares": _int(graph.get("totalIssueSize")),
        "subscription_times": safe_float(graph.get("noOfTimesIssueSubscribed")),
    }
    return fields, _date(stamp.group()) if stamp else None, rows


def _session():
    import requests

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    session.get("https://www.nseindia.com/market-data/all-upcoming-issues-ipo", timeout=30)  # the API wants its cookies
    return session


class NseIpoSource:
    def __init__(self, session=None):
        self.session = session or _session()

    def _json(self, path: str):
        response = self.session.get(BASE + path, timeout=30)
        response.raise_for_status()
        return response.json()

    def lists(self) -> dict[str, list[dict[str, Any]]]:
        return {name: self._json(path) or [] for name, path in LISTS.items()}

    def detail(self, symbol: str, board: str) -> dict[str, Any]:
        time.sleep(PAUSE_SECONDS)
        return self._json(f"ipo-detail?symbol={symbol}&series={DETAIL_SERIES[board]}")

    def listing_bars(self, day: str) -> dict[str, dict[str, Any]]:
        from backtest.bhavcopy import BhavcopyStore

        with tempfile.TemporaryDirectory(prefix="ipo_bhavcopy_") as root:
            frame = BhavcopyStore(root, series=LISTING_SERIES).fetch_day(date.fromisoformat(day))
        if frame is None or frame.empty:
            return {}
        return {str(row["Symbol"]).upper(): row for row in frame.to_dict("records")}


def gather(lists: dict[str, list[dict[str, Any]]], *, today: date, window_days: int) -> dict[tuple, dict[str, Any]]:
    """Every issue of the window, keyed (symbol, board); a later page's status wins."""
    since = (today - timedelta(days=window_days)).isoformat()
    issues: dict[tuple, dict[str, Any]] = {}
    for page, status in (("past", "listed"), ("upcoming", "forthcoming"), ("current", "open")):
        for item in lists.get(page) or []:
            row = listed_issue(item, status)
            if row is None or (page == "past" and (row["listing_date"] or "") < since):
                continue
            if status == "open" and row["issue_end"] and row["issue_end"] < today.isoformat():
                row["status"] = "closed"
            issues[(row["symbol"], row["board"])] = {**issues.get((row["symbol"], row["board"]), {}),
                                                     **{k: v for k, v in row.items() if v is not None}}
    return issues


def run(repo, *, source=None, today: date | None = None, backfill: bool = False,
        dry_run: bool = False) -> dict[str, int]:
    if repo.market != "NSE":
        return {}
    today = today or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    try:
        source = source or NseIpoSource()
        issues = gather(source.lists(), today=today, window_days=BACKFILL_DAYS if backfill else WINDOW_DAYS)
    except Exception as exc:  # noqa: BLE001 -- display evidence; the next run asks again
        logger.warning("IPO lists not read: %s", exc)
        return {"issues": 0, "subscriptions": 0}
    stored = {(row["symbol"], row["board"]): row for row in repo.stored_ipos()}
    subscriptions: list[dict[str, Any]] = []
    for key, issue in issues.items():
        before = stored.get(key, {})
        complete = before.get("lot_size") is not None and before.get("status") == issue["status"] != "open"
        if issue["status"] == "forthcoming" or complete:
            continue
        try:
            fields, as_of, rows = parse_detail(source.detail(*key))
        except Exception as exc:  # noqa: BLE001 -- one issue's page; the rest go on
            logger.warning("IPO detail for %s not read: %s", key[0], exc)
            continue
        issue.update({k: v for k, v in fields.items() if v is not None})
        # by day while open, the final figures once closed, and once for an issue first seen listed
        if as_of and rows and (issue["status"] in ("open", "closed") or key not in stored):
            subscriptions += [{"symbol": key[0], "as_of": as_of, **row} for row in rows]

    for day in sorted({i["listing_date"] for i in issues.values() if i["status"] == "listed"
                       and i.get("listing_date") and i["listing_date"] <= today.isoformat()}):
        # asked on first sighting and for a week after listing, then given up (a name the file lacks)
        recent = day >= (today - timedelta(days=LISTING_RETRY_DAYS)).isoformat()
        waiting = [i for k, i in issues.items() if i.get("listing_date") == day
                   and stored.get(k, {}).get("listing_close") is None and (recent or k not in stored)]
        if not waiting:
            continue
        try:
            bars = source.listing_bars(day)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Listing-day bhavcopy %s not read: %s", day, exc)
            continue
        for issue in waiting:
            bar = bars.get(issue["symbol"].upper())
            if bar:
                issue["listing_open"], issue["listing_close"] = safe_float(bar.get("Open")), safe_float(bar.get("Close"))

    rows = [{**stored.get(key, {}), **issue} for key, issue in issues.items()]
    if not dry_run:
        repo.upsert_ipos(rows, subscriptions)
        repo.put_ipos_object(since=(today - timedelta(days=BACKFILL_DAYS)).isoformat())
    counts = {"issues": len(rows), "subscriptions": len(subscriptions)}
    logger.info("IPOs: %s%s", counts, " (dry run, nothing written)" if dry_run else "")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--backfill", action="store_true", help=f"issues listed in the last {BACKFILL_DAYS} days")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), backfill=args.backfill, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
