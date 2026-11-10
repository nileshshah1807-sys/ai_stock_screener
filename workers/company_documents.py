"""Links to a company's documents on the exchange's archive, into ``company_documents``.

Five kinds, links only (nothing is downloaded or stored but the address):
presentation, transcript, recording (the notice that a call's recording is available),
rating and annual_report. The first four are read from the announcements that
``workers.upcoming_events`` already fetches each run, so they cost no exchange call;
annual reports come from the per-company endpoint, one seventh of the universe a day.

Retention is a year by ``announced_at``; annual reports keep the latest three per company.
The Results card's presentation is not stored: the dashboard takes the newest one within
-1..+7 days of the result's broadcast time (median lag 0.2 days, 99% inside that).
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

from screener.quarterly_results import INDEX_MAINBOARD, INDEX_SME, read_boards
from transcripts.collector import is_earnings_transcript
from transcripts.recordings import is_recording_notice

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
RETENTION_DAYS = 365
ANNUAL_REPORTS_KEPT = 3
# Announcements newer than this are (re)written each run; a write that already exists changes nothing.
FRESH_DAYS = 2
BACKFILL_WINDOW_DAYS = 7
SWEEP_PAUSE_SECONDS = 0.5
SWEEP_BUDGET_SECONDS = 20 * 60
SWEEP_WRITE_EVERY = 50  # symbols; a cancelled run keeps what it had

TITLES = {
    "presentation": "Investor presentation",
    "transcript": "Earnings call transcript",
    "recording": "Earnings call recording",
    "rating": "Credit rating",
}
# Companies also file a deck under these subjects; the text names it.
_DECK_SUBJECTS = ("general updates", "updates", "analysts/institutional investor meet/con. call updates")
_DECK = re.compile(r"presentation", re.IGNORECASE)
# A notice that schedules or invites to a meeting mentions a presentation without being one.
_NOT_A_DECK = re.compile(r"schedule|invite|meet", re.IGNORECASE)
_DECK_NAME = re.compile(r"present|ppt|deck", re.IGNORECASE)


def is_deck(text: str, url: str) -> bool:
    """A file named a presentation is one; otherwise a schedule, invite or meeting notice is not."""
    name = url.rsplit("/", 1)[-1]
    return bool(_DECK_NAME.search(name)) or not _NOT_A_DECK.search(f"{text} {name}")


def kind_of(record: dict[str, Any]) -> str | None:
    """Which of the four announcement kinds this is, or None.

    Transcript and recording use the collectors' own tests so a filing has one owner.
    """
    desc = str(record.get("desc") or "").strip().lower()
    text = str(record.get("attchmntText") or "")
    if is_earnings_transcript(record):
        return "transcript"
    if is_recording_notice(record):
        return "recording"
    if desc.startswith("credit rating"):
        return "rating"
    if desc == "investor presentation" or (desc in _DECK_SUBJECTS and _DECK.search(text) and is_deck(text, str(record.get("attchmntFile") or ""))):
        return "presentation"
    return None


def _announced_at(value: Any) -> datetime | None:
    """NSE's 'DD-Mon-YYYY HH:MM:SS' (India time), also the annual-report endpoint's upper-case month."""
    try:
        return datetime.strptime(str(value).title(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        return None


def announcement_rows(records: Iterable[dict[str, Any]], *, since: datetime, universe: set[str] | None = None) -> list[dict[str, Any]]:
    """Document rows for the announcements filed since ``since`` (by symbol, kind and address, once each)."""
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        symbol = str(record.get("symbol") or "").strip().upper()
        url = str(record.get("attchmntFile") or "").strip()
        filed = _announced_at(record.get("an_dt"))
        kind = kind_of(record)
        if not (symbol and url.startswith("http") and filed and kind) or filed < since:
            continue
        if universe is not None and symbol not in universe:
            continue
        rows.setdefault((symbol, kind, url), {
            "symbol": symbol, "kind": kind, "announced_at": filed.isoformat(), "title": TITLES[kind], "url": url, "period": None,
        })
    return list(rows.values())


def annual_report_rows(symbol: str, payload: Any) -> list[dict[str, Any]]:
    """The latest ``ANNUAL_REPORTS_KEPT`` reports in the per-company endpoint's reply."""
    reports = []
    for item in (payload or {}).get("data") or []:
        url = str(item.get("fileName") or "").strip()
        try:
            start, end = int(item["fromYr"]), int(item["toYr"])
        except (KeyError, TypeError, ValueError):
            continue
        if not url.startswith("http"):
            continue
        at = _announced_at(item.get("broadcast_dttm")) or datetime(end, 3, 31, tzinfo=IST)  # shortcut: year end when NSE gives no time
        reports.append((end, {
            "symbol": symbol, "kind": "annual_report", "announced_at": at.isoformat(),
            "title": f"Annual report {start}-{str(end)[2:]}", "url": url, "period": f"{start}-{str(end)[2:]}",
        }))
    return [row for _, row in sorted(reports, key=lambda r: r[0], reverse=True)[:ANNUAL_REPORTS_KEPT]]


def record_announcements(repo, announcements: list[dict[str, Any]], *, now: datetime, dry_run: bool = False) -> int:
    """Write the fresh documents among ``announcements``; a failure warns and writes nothing."""
    if repo.market != "NSE":
        return 0
    try:
        universe = set(repo.snapshot_companies())
        if not universe:  # no list to keep to: write nothing rather than every symbol the exchange names
            logger.warning("Company documents not recorded: the universe is empty")
            return 0
        rows = announcement_rows(announcements, since=now - timedelta(days=FRESH_DAYS), universe=universe)
        return 0 if dry_run or not rows else repo.upsert_company_documents(rows)
    except Exception as exc:  # noqa: BLE001 -- display evidence: never fail the step that fetched the announcements
        logger.warning("Company documents not recorded (%s). Apply storage/company_documents_schema.sql.", exc)
        return 0


def sweep_slice(symbols: Iterable[str], today: date, *, everything: bool = False) -> list[str]:
    """Today's seventh of the universe: every symbol is visited once a week with no stored state."""
    ordered = sorted(symbols)
    return ordered if everything else [s for i, s in enumerate(ordered) if i % 7 == today.weekday()]


def _annual_reports(nse, symbol: str) -> list[dict[str, Any]]:
    """A company's annual reports from the mainboard, or from NSE Emerge where it has none there."""
    for segment in (INDEX_MAINBOARD, INDEX_SME):
        rows = annual_report_rows(symbol, nse.annual_reports(symbol=symbol, segment=segment))
        if rows:
            return rows
    return []


def sweep_annual_reports(repo, nse, symbols: list[str], *, dry_run: bool = False, budget: float = SWEEP_BUDGET_SECONDS, pause: float = SWEEP_PAUSE_SECONDS) -> dict[str, int]:
    counts = {"symbols": 0, "rows": 0, "written": 0, "dropped": 0}
    stored = repo.company_documents(kind="annual_report")
    deadline = time.monotonic() + budget
    batch: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []

    def flush() -> None:
        counts["rows"] += len(batch)
        if not dry_run:
            counts["written"] += repo.upsert_company_documents(batch) if batch else 0
            counts["dropped"] += repo.delete_company_documents(stale) if stale else 0
        batch.clear()
        stale.clear()

    for symbol in symbols:
        if time.monotonic() > deadline:
            logger.warning("Annual-report sweep stopped at its time budget after %s symbols", counts["symbols"])
            break
        try:
            rows = _annual_reports(nse, symbol)
        except Exception as exc:  # noqa: BLE001 -- one symbol's refusal must not stop the sweep
            logger.warning("Annual reports for %s unavailable (%s)", symbol, exc)
            continue
        finally:
            time.sleep(pause)
        counts["symbols"] += 1
        keep = {row["url"] for row in rows}
        stale += [d for d in stored.get(symbol, []) if d["url"] not in keep and rows]
        batch += rows
        if counts["symbols"] % SWEEP_WRITE_EVERY == 0:
            flush()
    flush()
    logger.info("Annual-report sweep: %s%s", counts, " (dry run, nothing written)" if dry_run else "")
    return counts


def prune(repo, *, now: datetime | None = None, dry_run: bool = False) -> None:
    """Drop links announced more than a year ago (annual reports are kept to a count instead)."""
    if not dry_run:
        repo.prune_company_documents(((now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)).isoformat())


def clean_presentations(repo, *, dry_run: bool = False) -> int:
    """By hand: remove stored presentations whose file name says schedule/invite/meet and not presentation."""
    misfiled = [row for rows in repo.company_documents(kind="presentation").values() for row in rows if not is_deck("", row["url"])]
    for row in misfiled:
        logger.info("%s %s %s", "would delete" if dry_run else "deleting", row["symbol"], row["url"])
    logger.info("Misfiled presentations: %s%s", len(misfiled), " (dry run, nothing deleted)" if dry_run else "")
    return 0 if dry_run or not misfiled else repo.delete_company_documents(misfiled, kind="presentation")


def backfill(repo, nse, *, days: int, now: datetime, dry_run: bool = False) -> int:
    """Seven-day announcement windows back ``days`` days: for a by-hand backfill, never scheduled."""
    universe = set(repo.snapshot_companies())
    written, end = 0, now
    while end > now - timedelta(days=days):
        start = max(end - timedelta(days=BACKFILL_WINDOW_DAYS), now - timedelta(days=days))
        records = read_boards(
            lambda first, last, index=INDEX_MAINBOARD: nse.announcements(index=index, from_date=first, to_date=last),
            start.replace(tzinfo=None),
            end.replace(tzinfo=None),
        )
        rows = announcement_rows(records, since=start, universe=universe)
        logger.info("Backfill %s..%s: %s announcements, %s documents", start.date(), end.date(), len(records), len(rows))
        if rows and not dry_run:
            written += repo.upsert_company_documents(rows)
        end = start
        time.sleep(SWEEP_PAUSE_SECONDS)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--annual-reports", action="store_true", help="sweep today's seventh of the universe")
    parser.add_argument("--prune", action="store_true", help="drop links older than a year (needs no exchange session)")
    parser.add_argument("--clean-presentations", action="store_true", help="by hand: delete stored schedules misfiled as presentations (try --dry-run first)")
    parser.add_argument("--all", action="store_true", help="with --annual-reports: the whole universe")
    parser.add_argument("--backfill-days", type=int, default=0, help="by hand: announcements back this many days")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository
    from workers.upcoming_events import open_session

    repo = DashboardRepository.from_environment(args.market)
    if repo.market != "NSE" or not (args.annual_reports or args.backfill_days or args.prune or args.clean_presentations):
        logger.warning("Nothing to do: pass --prune, --annual-reports, --backfill-days or --clean-presentations on the NSE")
        return 0
    now = datetime.now(UTC)
    if args.prune:
        prune(repo, now=now, dry_run=args.dry_run)
    if args.clean_presentations:
        clean_presentations(repo, dry_run=args.dry_run)
    if not (args.annual_reports or args.backfill_days):
        return 0
    with TemporaryDirectory(prefix="company_documents_") as folder:
        try:
            nse = open_session(folder)
        except Exception as exc:  # noqa: BLE001 -- a refused session is a warning, not a failed step
            logger.warning("Exchange session not opened (%s); nothing read", exc)
            return 0
        with nse:
            if args.backfill_days:
                backfill(repo, nse, days=args.backfill_days, now=now, dry_run=args.dry_run)
            if args.annual_reports:
                symbols = sweep_slice([s for s in repo.snapshot_companies() if not s.endswith(".BO")], now.astimezone(IST).date(), everything=args.all)
                sweep_annual_reports(repo, nse, symbols, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
