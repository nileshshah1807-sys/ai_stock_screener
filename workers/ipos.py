"""NSE IPOs: issues bidding now, coming up, awaiting listing and listed within a year.

All of it is NSE's public JSON, read with the session our other NSE workers use:

* ``ipo-current-issue`` and ``all-upcoming-issues?category=ipo``: issues bidding
  now or announced, mainboard and SME (Emerge), with the price band and the
  shares on offer in the book (anchor portion excluded).
* ``public-past-issues``: every issue NSE has listed; the last ``window_days``
  of equity and SME are kept.
* ``ipo-active-category?symbol=``: the combined NSE+BSE book by investor
  category, with the exchange's own time stamp. Asked while bidding and once
  more after the close; a listed issue still answers, so older issues fill in a
  ``book_budget`` at a time.
* ``ipo-detail?symbol=&series=``: lot size, face value, registrar, the offer document.

The listing day's open and close come from that day's bhavcopy.

Rows go to the D1 table ``ipo_issues`` (``storage/d1/ipo_issues.sql``, routed
with ``TABLE_BACKEND_D1``) and the whole set to ``live/NSE/ipos.json``, which
the dashboard's IPOs page reads. A field once read is never overwritten with
nothing: an SME's book reads zero shares offered once it closes, so the figure
read while it was open is the one kept.

GMP (``IPO_GMP_ENABLED``, off by default) is the grey-market premium as the
public tracker investorgain.com prints it. It is unofficial, no exchange
publishes it, and it is shown labelled as such. Nothing scores any of this.

BSE SME issues are not here: NSE does not list them.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from screener.markets import resolve as resolve_market
from screener.numeric import round_half_up, safe_float
from screener.quarterly_results import REQUEST_HEADERS

logger = logging.getLogger(__name__)

NSE_API = "https://www.nseindia.com/api"
GMP_URL = "https://www.investorgain.com/report/live-ipo-gmp/331/"
TRACKER = "https://www.investorgain.com"
IST = ZoneInfo("Asia/Kolkata")
BOARDS = {"Equity": "Mainboard", "SME": "SME"}
MAX_LISTING_LAG_DAYS = 30
DETAIL_SERIES = {"Mainboard": "EQ", "SME": "SME"}
LISTING_SERIES = ("EQ", "BE", "SM", "ST", "SZ")
BHAVCOPY_CACHE = Path("reports_advanced/bhavcopy")
#: Until NSE's closing day figures are final (T+1); after it the book is not asked again.
BOOK_SETTLES_DAYS = 1
#: An issue that closed but never listed (withdrawn, delayed) leaves the page after this.
UNLISTED_DAYS = 30
#: Bookkeeping the page does not need.
INTERNAL = ("detail_read", "book_final", "listing_checked")


def _date(text: Any) -> str | None:
    """ISO date from NSE's '20-Nov-2026', '04-NOV-2026' or '2026-11-20 00:00:00'."""
    text = str(text or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    try:
        return datetime.strptime(text.title(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _band(text: Any) -> tuple[float | None, float | None]:
    """(low, high) from 'Rs.259 to Rs.272' or a fixed price '402'."""
    numbers = [safe_float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", str(text or ""))]
    if not numbers:
        return None, None
    return numbers[0], numbers[-1]


def parse_issues(current: list, upcoming: list, past: list, today: date, window_days: int = 365) -> dict[str, dict]:
    """One base row per symbol from the three feeds; a bidding issue's row wins."""
    since = (today - timedelta(days=window_days)).isoformat()
    rows: dict[str, dict] = {}
    for item in past or []:
        board, listed = BOARDS.get(item.get("securityType")), _date(item.get("listingDate"))
        closed = _date(item.get("ipoEndDate"))
        if board is None or not listed or listed < since:
            continue
        low, high = _band(item.get("priceRange"))
        rows[item["symbol"]] = {
            # The feed names it companyName for SME issues and company for mainboard ones.
            "symbol": item["symbol"], "company": item.get("companyName") or item.get("company"), "board": board,
            "open_date": _date(item.get("ipoStartDate")), "close_date": closed,
            "listing_date": listed, "price_low": low, "price_high": high,
            "issue_price": safe_float(item.get("issuePrice")) or (high if low == high else None),
        }
    for item in [*(upcoming or []), *(current or [])]:
        board = BOARDS.get(item.get("series"))
        if board is None or not item.get("symbol"):
            continue
        low, high = _band(item.get("issuePrice"))
        rows[item["symbol"]] = {
            "symbol": item["symbol"], "company": item.get("companyName"), "board": board,
            "open_date": _date(item.get("issueStartDate")), "close_date": _date(item.get("issueEndDate")),
            "price_low": low, "price_high": high, "book_shares": safe_float(item.get("issueSize")),
        }
    return rows


def _category(label: str) -> str:
    for key, short in (("Qualified Institutional", "QIB"), ("Two Lakh", "sNII"), ("Ten Lakh", "bNII"),
                       ("Non Institutional", "NII"), ("Retail", "Retail"), ("Employee", "Employee"),
                       ("Shareholder", "Shareholder"), ("Policy", "Policyholder"), ("Market Maker", "Market maker")):
        if key.lower() in label.lower():
            return short
    return label.strip()


def parse_book(payload: dict) -> dict[str, Any]:
    """The book by top-level category, its total and time stamp; {} when nothing is usable.

    A ratio needs shares offered: a category NSE reports with none offered has no ratio
    (absent, not zero), and a book with none anywhere -- an SME after its close -- is unusable.
    """
    categories, total = [], None
    for item in (payload or {}).get("dataList", []):
        offered, bid = safe_float(item.get("noOfShareOffered")), safe_float(item.get("noOfSharesBid"))
        if item.get("category") == "Total":
            total = bid / offered if offered and bid is not None else None
        elif re.fullmatch(r"\d+(\.\d+)?", str(item.get("srNo") or "")):
            categories.append({
                "category": _category(item.get("category", "")), "offered": offered, "bid": bid,
                "times": round_half_up(bid / offered, 2) if offered and bid is not None else None,
            })
    if total is None and not any(c["times"] is not None for c in categories):
        return {}
    stamp = re.search(r"(\d{2}-\w{3}-\d{4}) (\d{2}:\d{2}:\d{2})", str(payload.get("updateTime") or ""))
    return {
        "subscription": categories,
        "subscription_total": round_half_up(total, 2) if total is not None else None,
        "subscription_as_of": f"{_date(stamp.group(1))}T{stamp.group(2)}+05:30" if stamp else None,
    }


def parse_detail(payload: dict) -> dict[str, Any]:
    info = {item.get("title"): str(item.get("value") or "").strip('" ')
            for item in (payload or {}).get("issueInfo", {}).get("dataList", []) if item.get("title")}
    lot = re.search(r"\d[\d,]*", info.get("Bid Lot") or info.get("Lot Size") or "")
    rhp = info.get("Red Herring Prospectus") or info.get("Prospectus") or ""
    return {
        "lot_size": int(lot.group(0).replace(",", "")) if lot else None,
        "face_value": _band(info.get("Face Value"))[0],
        "registrar": info.get("Name of the Registrar") or None,
        "rhp_url": rhp if rhp.startswith("http") else None,
    }


def _name_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(limited|ltd|ipo)\b", "", str(name or "").lower()))


def _flight_text(page: str | None) -> str:
    """The text of a Next page's flight payload: its ``self.__next_f.push([1, "..."])`` chunks, joined."""
    return "".join(json.loads(f'"{chunk}"') for chunk in
                   re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', page or ""))


def parse_gmp(page: str) -> list[dict[str, Any]]:
    """The tracker's rows: name, open date, GMP now and at its peak, percent and time stamp.

    The table sits in Next's flight payload (``self.__next_f.push([1, "..."])``) as
    ``initialTableResponse.reportTableData``; each chunk is a JSON string literal.
    """
    text = _flight_text(page)
    start = re.search(r'"reportTableData":\s*', text)
    if start is None:
        return []
    table, end = json.JSONDecoder().raw_decode(text, start.end())
    now = re.search(r'"currentTime":\s*"(\d{4})-(\d{2})', text[end:])
    out = []
    for row in table:
        gmp_text = html.unescape(re.sub(r"<[^>]+>", " ", str(row.get("GMP", ""))))
        gmp = re.search(r"₹\s*(-?\d[\d,]*(?:\.\d+)?)", gmp_text)
        stamp = re.search(r"(\d{1,2})-(\w{3}) (\d{1,2}):(\d{2})", re.sub(r"<[^>]+>", "", str(row.get("Updated-On", ""))))
        as_of = None
        if stamp and now:
            year = int(now.group(1))
            day = datetime.strptime(f"{stamp.group(1)}-{stamp.group(2)}-{year}", "%d-%b-%Y")
            if day.month > int(now.group(2)):  # a December stamp read in January
                day = day.replace(year=year - 1)
            as_of = f"{day.date().isoformat()}T{int(stamp.group(3)):02d}:{stamp.group(4)}:00+05:30"
        out.append({
            "name": row.get("~ipo_name"), "open_date": row.get("~Srt_Open"),
            "gmp": safe_float(gmp.group(1).replace(",", "")) if gmp else None,
            "gmp_pct": safe_float(row.get("~gmp_percent_calc")),
            "gmp_peak": safe_float(row.get("~max_gmp1")), "gmp_as_of": as_of,
            "page": row.get("~urlrewrite_folder_name"),
        })
    return out


def _tracked(row: dict, tracker: dict[str, dict]) -> dict | None:
    """The tracker's row for one issue, matched by name and open date."""
    found = tracker.get(_name_key(row.get("company")))
    if found and found.get("open_date") and row.get("open_date") and found["open_date"] != row["open_date"]:
        return None
    return found


def gmp_fields(row: dict, tracker: dict[str, dict]) -> dict[str, Any]:
    """The tracker's figures for one issue; {} when unmatched or blank."""
    found = _tracked(row, tracker)
    if not found or found["gmp"] is None:
        return {}
    return {key: found[key] for key in ("gmp", "gmp_pct", "gmp_peak", "gmp_as_of")}


def _cell(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def parse_financials(page: str | None) -> dict[str, Any] | None:
    """The restated financials an issue's tracker page prints from its RHP; None when it has none.

    ``{"basis", "unit", "periods": [ISO dates], "rows": [{"label", "values"}]}``: the
    values as printed, in ``unit`` (crore or lakh); a blank cell is None, not zero.
    """
    text = _flight_text(page)
    start = text.find("fin-table-wrap")
    end = text.find("</table>", start)
    if start < 0 or end < 0:
        return None
    block = text[start:end]
    basis = re.search(r"Financials\s*\(([^)]+)\)", block)
    unit = re.search(r"Amount in\s*(?:&#8377;|₹)?\s*(Crore|Lakh)", block, re.I)
    periods, rows = [], []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S):
        cells = [_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if not cells or not cells[0]:
            continue
        if cells[0].lower().startswith("period"):
            periods = [_period(c) for c in cells[1:] if c]
        elif periods:
            values = [safe_float(c.replace(",", "")) for c in cells[1:len(periods) + 1]]
            if any(value is not None for value in values):  # the unit's line is a row too
                rows.append({"label": re.sub(r"\bNET\b", "Net", cells[0]), "values": values})
    if not periods or not rows:
        return None
    return {"basis": basis.group(1).strip() if basis else None,
            "unit": unit.group(1).lower() if unit else None, "periods": periods, "rows": rows}


def _period(text: str) -> str | None:
    try:
        return datetime.strptime(text, "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def _nse_fetch() -> Callable[[str], Any]:
    import requests

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    session.get("https://www.nseindia.com/", timeout=30)  # sets the cookies the API asks for

    def fetch(path: str) -> Any:
        time.sleep(0.3)
        response = session.get(f"{NSE_API}/{path}", timeout=30)
        response.raise_for_status()
        return response.json()

    return fetch


def _listing_bars(day: date) -> dict[str, tuple[float | None, float | None]]:
    from backtest.bhavcopy import BhavcopyStore

    frame = BhavcopyStore(BHAVCOPY_CACHE, series=LISTING_SERIES).get_day(day)
    return {str(r["Symbol"]).upper(): (safe_float(r.get("Open")), safe_float(r.get("Close")))
            for r in frame.to_dict("records")}


def _gmp_page() -> str | None:
    if os.getenv("IPO_GMP_ENABLED", "").lower() != "true":
        return None
    import requests

    response = requests.get(GMP_URL, headers={"User-Agent": REQUEST_HEADERS["User-Agent"]}, timeout=30)
    response.raise_for_status()
    return response.text


def _issue_page(path: str) -> str:
    """One issue's page on the tracker; ``path`` is its GMP page's, as the table links it."""
    import requests

    response = requests.get(TRACKER + path.replace("/gmp/", "/ipo/", 1),
                            headers={"User-Agent": REQUEST_HEADERS["User-Agent"]}, timeout=30)
    response.raise_for_status()
    return response.text


def _merge(row: dict, fields: dict) -> None:
    """Fill ``row`` from ``fields``, never replacing a value with nothing."""
    row.update({key: value for key, value in fields.items() if value is not None})


def _keep(row: dict, today: date, window_days: int) -> bool:
    listed, closed = row.get("listing_date"), row.get("close_date")
    # An IPO lists days after bidding closes; a listing long after the dates it carries
    # is a later issue by a listed company (partly-paid shares, an NCD), not an IPO.
    if listed and closed and date.fromisoformat(listed) - date.fromisoformat(closed) > timedelta(days=MAX_LISTING_LAG_DAYS):
        return False
    if row.get("listing_date"):
        return row["listing_date"] >= (today - timedelta(days=window_days)).isoformat()
    return not row.get("close_date") or row["close_date"] >= (today - timedelta(days=UNLISTED_DAYS)).isoformat()


def _try(what: str, call: Callable[[], Any]) -> Any:
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 -- display evidence: a refusal leaves the row as it was; the next run asks again
        logger.warning("IPOs: %s not read: %s", what, exc)
        return None


def run(
    repo,
    *,
    today: date | None = None,
    fetch: Callable[[str], Any] | None = None,
    bars: Callable[[date], dict] = _listing_bars,
    gmp_page: Callable[[], str | None] = _gmp_page,
    issue_page: Callable[[str], str] = _issue_page,
    book_budget: int = 40,
    listing_days: int = 8,
    window_days: int = 365,
    dry_run: bool = False,
) -> dict[str, int]:
    if resolve_market(repo.market).code != "NSE":
        logger.info("%s has no IPO source; nothing to store", repo.market)
        return {}
    today = today or datetime.now(IST).date()
    fetch = fetch or _nse_fetch()
    stored = {row["symbol"]: row for row in repo.ipo_issues()}
    feeds = [_try(path, lambda p=path: fetch(p)) or [] for path in
             ("ipo-current-issue", "all-upcoming-issues?category=ipo", "public-past-issues")]
    rows = {symbol: dict(row) for symbol, row in stored.items()}
    for symbol, base in parse_issues(*feeds, today, window_days).items():
        _merge(rows.setdefault(symbol, {}), base)
    rows = {symbol: row for symbol, row in rows.items() if _keep(row, today, window_days)}
    iso = today.isoformat()

    def due(needs: Callable[[dict], bool]) -> list[dict]:
        """Rows that need a read: every issue not yet closed, then ``book_budget`` older ones, newest first."""
        found = sorted((row for row in rows.values() if needs(row)),
                       key=lambda row: row.get("close_date") or "", reverse=True)
        return found[:max(book_budget, sum(1 for row in found if (row.get("close_date") or iso) >= iso))]

    for row in due(lambda r: bool(r.get("open_date")) and r["open_date"] <= iso and not r.get("book_final")):
        book = _try(f"{row['symbol']} book", lambda s=row["symbol"]: fetch(f"ipo-active-category?symbol={s}"))
        if book is None:
            continue
        _merge(row, parse_book(book))
        settled = row.get("close_date") and date.fromisoformat(row["close_date"]) + timedelta(days=BOOK_SETTLES_DAYS) < today
        row["book_final"] = 1 if settled else 0
    # Read once; again while bidding until the lot size is published.
    for row in due(lambda r: not r.get("detail_read") or (not r.get("lot_size") and (r.get("close_date") or iso) >= iso)):
        path = f"ipo-detail?symbol={row['symbol']}&series={DETAIL_SERIES.get(row.get('board'), 'EQ')}"
        detail = _try(f"{row['symbol']} detail", lambda p=path: fetch(p))
        if detail is not None:
            _merge(row, parse_detail(detail))
            row["detail_read"] = 1

    pending = sorted({row["listing_date"] for row in rows.values()
                      if row.get("listing_date") and row["listing_date"] < iso and not row.get("listing_checked")},
                     reverse=True)
    for day in pending[:listing_days]:
        prices = _try(f"bhavcopy {day}", lambda d=day: bars(date.fromisoformat(d)))
        if prices is None:
            continue
        for row in rows.values():
            if row.get("listing_date") == day:
                opened, closed = prices.get(row["symbol"], (None, None))
                _merge(row, {"listing_open": opened, "listing_close": closed, "listing_checked": 1})

    page = _try("GMP tracker", gmp_page)
    if page:
        tracker = {_name_key(item["name"]): item for item in parse_gmp(page)}
        for row in rows.values():
            if row.get("listing_date"):
                continue
            _merge(row, gmp_fields(row, tracker))
            found = _tracked(row, tracker)
            # Read once: a prospectus's figures do not change while the issue is open.
            if found and found.get("page") and not row.get("financials"):
                page_text = _try(f"{row['symbol']} financials", lambda p=found["page"]: issue_page(p))
                _merge(row, {"financials": parse_financials(page_text)})

    changed = [row for symbol, row in rows.items() if row != stored.get(symbol)]
    columns = {key for row in changed for key in row}
    changed = [{key: row.get(key) for key in sorted(columns)} for row in changed]  # one key set for the bulk upsert
    if not dry_run:
        if changed:
            repo.upsert_ipo_issues(changed)
        shown = sorted({key for row in rows.values() for key in row} - {*INTERNAL, "market"})
        repo.put_ipos_object(sorted(({key: row.get(key) for key in shown} for row in rows.values()),
                                    key=lambda row: row.get("open_date") or "", reverse=True))
    logger.info("IPOs: %d issues, %d changed%s", len(rows), len(changed), " (dry run, nothing written)" if dry_run else "")
    return {"issues": len(rows), "changed": len(changed)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--book-budget", type=int, default=40)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), book_budget=args.book_budget, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
