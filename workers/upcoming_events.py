"""Which companies report soon, and which have announced an earnings call.

Display evidence only: the dashboard's calendar reads ``upcoming_events``, one
row per stock, and nothing scores it. NSE only; a company listed on BSE alone
has no notice here and no row.

``next_result_date``
    The board meeting that approves financial results, from NSE's board-meeting
    feed (the 'Financial Results' purposes). A date, never a time. When a
    company filed two intimations the later one wins, which is how a
    rescheduled meeting replaces the old date.

``next_call_at`` / ``next_call_date``
    An earnings call the company announced, read from the notice's PDF: the API
    carries neither the date nor the time. A notice is an earnings call, not an
    investor meet, when its text names a conference or earnings call *and*
    ties it to results (``is_earnings_call``); one-on-one and group meetings
    and broker conferences name no such call and are dropped. A time is kept
    only in India time; a call stated in another zone keeps its date alone.

A passed date is cleared here, so the reader has nothing to filter. A notice is
read once: ``updated_at`` is when the worker last looked at the stock, and only
a notice filed after it is fetched. A notice that fails to download leaves its
stock untouched, to be tried again next run.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

from transcripts.collector import discover_nse_announcements, is_earnings_transcript
from transcripts.recordings import download_notice, is_recording_notice

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
#: How far ahead the board-meeting feed is read.
RESULTS_HORIZON_DAYS = 60
#: How far back a run looks for call notices; a call is announced days ahead and runs are minutes apart.
NOTICE_LOOKBACK_DAYS = 3
#: Notices read in one run (the archive refuses a burst); the rest wait.
MAX_NOTICES_PER_RUN = 60
#: Seconds between two downloads from the archive.
NOTICE_PAUSE_SECONDS = 0.7

_RESULT_PURPOSE = "financial results"
_NOT_A_SCHEDULE = re.compile(r"presentation|outcome|minutes", re.IGNORECASE)
_CALL = re.compile(
    r"(?:earnings|conference|investor|analyst|results)\s+(?:con(?:ference)?\s*)?call|con-?call", re.IGNORECASE
)
_RESULTS = re.compile(
    r"financial results|results for|quarter(?:ly)?\s+(?:and\s+\w+\s+)?ended|half[- ]year|\bQ[1-4]\s*(?:FY|'?\d)|"
    r"\bH[12]\s*FY|earnings",
    re.IGNORECASE,
)

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_MONTH = r"(?P<{0}>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE = re.compile(
    r"(?<!\d)(?:(?P<d1>\d{1,2})(?:st|nd|rd|th)?[\s,.-]+(?:of\s+)?" + _MONTH.format("m1") + r"\.?[\s,.-]*(?P<y1>\d{4})"
    r"|" + _MONTH.format("m2") + r"\.?\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y2>\d{4})"
    r"|(?P<d3>\d{1,2})[/.-](?P<m3>\d{1,2})[/.-](?P<y3>\d{4}))(?!\d)",
    re.IGNORECASE,
)
_TIME = re.compile(
    r"(?<![\d/.:-])(?P<h>\d{1,2})(?:\s*[:.]\s*(?P<min>\d{2}))?\s*(?P<ap>a\.?\s?m\b|p\.?\s?m\b|noon|hrs\b)?",
    re.IGNORECASE,
)
#: Zones other than India: a time followed by one of these is not India time.
_FOREIGN_ZONE = re.compile(r"^[\s(]*(?:EST|EDT|ET|CST|PST|PDT|GMT|UTC|BST|CET|SGT|HKT|JST|AEST)\b")
#: How close a clock time sits to its date, in characters.
_NEAR = 70


def is_call_notice(record: dict[str, Any]) -> bool:
    """A 'Con. Call' announcement that may announce a call: not a recording, transcript or deck."""
    text = " ".join(str(record.get(key) or "") for key in ("desc", "attchmntText"))
    return (
        "con. call" in text.lower()
        and not _NOT_A_SCHEDULE.search(text)
        and not is_earnings_transcript(record)
        and not is_recording_notice(record)
    )


def is_earnings_call(text: str) -> bool:
    """The notice announces a call on the company's results, not an investor meet."""
    return bool(_CALL.search(text) and _RESULTS.search(text))


def _date_of(match: re.Match[str]) -> date | None:
    parts = match.groupdict()
    try:
        if parts["d1"]:
            return date(int(parts["y1"]), _MONTHS[parts["m1"].lower()], int(parts["d1"]))
        if parts["d2"]:
            return date(int(parts["y2"]), _MONTHS[parts["m2"].lower()], int(parts["d2"]))
        return date(int(parts["y3"]), int(parts["m3"]), int(parts["d3"]))
    except ValueError:
        return None


def _time_in(chunk: str) -> clock | None:
    """The first India-time clock reading in ``chunk``, or None.

    A reading with no am/pm needs a colon and an hour a day starts with the 24-hour
    clock ('16:00'); '4.30' alone could be either half of the day.
    """
    for match in _TIME.finditer(chunk):
        hour, minute, marker = int(match["h"]), int(match["min"] or 0), (match["ap"] or "").lower().replace(" ", "")
        if match["min"] is None and not marker:
            continue  # a bare number is not a time
        if minute > 59 or hour > 23 or _FOREIGN_ZONE.match(chunk[match.end():]):
            continue
        if marker.startswith(("a", "p")):
            if hour == 0 or hour > 12:
                continue
            hour = hour % 12 + (12 if marker.startswith("p") else 0)
        elif marker == "noon":
            hour = 12
        elif not (marker == "hrs" or ":" in match.group(0)) or hour < 7:
            continue
        return clock(hour, minute)
    return None


def call_schedule(text: str, *, filed: date) -> tuple[date, clock | None] | None:
    """The date, and the India time if stated, of the call a notice announces.

    A date with a time beside it wins; failing that the first date after the
    day the notice was filed -- the letter's own date is the filing day and says
    nothing about the call.
    """
    text = re.sub(r"\s+", " ", text)
    found = [(match, _date_of(match)) for match in _DATE.finditer(text)]
    found = [(match, day) for match, day in found if day]
    without_time = None
    for index, (match, day) in enumerate(found):
        # A time belongs to the nearer date: the window stops at a neighbouring date.
        stop = found[index + 1][0].start() if index + 1 < len(found) else len(text)
        start = found[index - 1][0].end() if index else 0
        stamp = _time_in(text[match.end(): min(match.end() + _NEAR, stop)]) or _time_in(
            text[max(start, match.start() - _NEAR): match.start()]
        )
        if stamp and day >= filed:
            return day, stamp
        if without_time is None and day > filed:
            without_time = day
    return (without_time, None) if without_time else None


def result_dates(meetings: list[dict[str, Any]], *, today: date) -> dict[str, dict[str, Any]]:
    """Each symbol's coming result meeting: its latest intimation dated today or later."""
    chosen: dict[str, tuple[str, dict[str, Any]]] = {}
    for meeting in meetings:
        purpose = str(meeting.get("bm_purpose") or "")
        symbol = str(meeting.get("bm_symbol") or "").strip().upper()
        try:
            day = datetime.strptime(str(meeting.get("bm_date")), "%d-%b-%Y").date()
        except ValueError:
            continue
        if not symbol or day < today or not purpose.lower().startswith(_RESULT_PURPOSE):
            continue
        filed = _stamp(meeting.get("bm_timestamp"))
        if symbol not in chosen or filed > chosen[symbol][0]:
            chosen[symbol] = (
                filed,
                {"company": meeting.get("sm_name"), "next_result_date": day.isoformat(), "result_purpose": purpose},
            )
    return {symbol: found for symbol, (_, found) in chosen.items()}


def _stamp(value: Any) -> str:
    """A feed's 'DD-Mon-YYYY HH:MM:SS' as a sortable string; '' when it is not one."""
    try:
        return datetime.strptime(str(value), "%d-%b-%Y %H:%M:%S").isoformat()
    except ValueError:
        return ""


def _filed_at(record: dict[str, Any]) -> datetime | None:
    try:
        return datetime.strptime(str(record.get("an_dt")), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        return None


def read_notice(record: dict[str, Any], folder: Path, *, filed: date) -> tuple[date, clock | None] | None:
    """The call a notice announces; None for an investor meet or a notice with no stated date."""
    import pymupdf

    path = download_notice(str(record["attchmntFile"]), folder)
    with pymupdf.open(path) as document:
        text = "\n".join(page.get_text("text") for page in document)
    return call_schedule(text, filed=filed) if is_earnings_call(text) else None


def _call_fields(call: tuple[date, clock | None] | None, url: str) -> dict[str, Any]:
    if call is None:
        return {"next_call_at": None, "next_call_date": None, "call_source_url": url}
    day, stamp = call
    return {
        "next_call_at": datetime.combine(day, stamp, tzinfo=IST).isoformat() if stamp else None,
        "next_call_date": None if stamp else day.isoformat(),
        "call_source_url": url,
    }


def _call_day(row: dict[str, Any]) -> date | None:
    if row.get("next_call_at"):
        return datetime.fromisoformat(str(row["next_call_at"])).astimezone(IST).date()
    return date.fromisoformat(str(row["next_call_date"])[:10]) if row.get("next_call_date") else None


def _same(new: Any, old: Any) -> bool:
    """Equal as stored: Postgres hands a timestamp back in UTC, whatever offset it was written in."""
    if isinstance(new, str) and "T" in new and isinstance(old, str):
        return datetime.fromisoformat(new) == datetime.fromisoformat(old)
    return new == old


_COLUMNS = ("company", "next_result_date", "result_purpose", "next_call_at", "next_call_date", "call_source_url")


def merge(
    stored: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    notices: dict[str, tuple[dict[str, Any], tuple[date, clock | None] | None]],
    *,
    today: date,
    checked_at: datetime,
) -> list[dict[str, Any]]:
    """The rows to write: those whose content changed, and every stock whose notices were read.

    ``notices`` maps a symbol to its newest earnings-call notice and what it announced
    (None: read, but no call date in it -- the stock keeps the call it had).
    """
    rows = []
    for symbol in sorted(set(stored) | set(results) | set(notices)):
        old = stored.get(symbol, {})
        row = {column: old.get(column) for column in _COLUMNS}
        row.update({"next_result_date": None, "result_purpose": None, **results.get(symbol, {})})
        if symbol in notices:
            record, call = notices[symbol]
            if call is not None:
                row.update(_call_fields(call, str(record["attchmntFile"])))
            row["company"] = row["company"] or record.get("sm_name")
        called = _call_day(row)
        if called is not None and called < today:
            row.update(next_call_at=None, next_call_date=None, call_source_url=None)
        if symbol in notices or any(_same(row[c], old.get(c)) is False for c in _COLUMNS if c != "company"):
            rows.append({"symbol": symbol, **row, "updated_at": checked_at.isoformat(timespec="seconds")})
    return rows


def collect_notices(
    stored: dict[str, dict[str, Any]],
    *,
    folder: Path,
    pause: float = NOTICE_PAUSE_SECONDS,
    limit: int = MAX_NOTICES_PER_RUN,
    discover=None,
    read=None,
) -> dict[str, tuple[dict[str, Any], tuple[date, clock | None] | None]]:
    """For each stock with a notice filed since the worker last looked, its newest earnings-call one.

    Newest filings first; at most ``limit`` are read, and the stocks of those not
    reached are left alone. A stock whose notice would not download is left alone too.
    """
    records = (discover or discover_nse_announcements)(NOTICE_LOOKBACK_DAYS, is_call_notice)
    fresh = []
    for record in records:
        symbol = str(record.get("symbol") or "").strip().upper()
        filed = _filed_at(record)
        seen = stored.get(symbol, {}).get("updated_at")
        if not (symbol and filed and record.get("attchmntFile")):
            continue
        if seen and filed <= datetime.fromisoformat(str(seen)):
            continue
        fresh.append((symbol, filed, record))
    fresh.sort(key=lambda item: item[1], reverse=True)

    found: dict[str, tuple[dict[str, Any], tuple[date, clock | None] | None]] = {}
    failed: set[str] = set()
    for symbol, filed, record in fresh[:limit]:
        if symbol in found or symbol in failed:
            continue  # the newest earnings-call notice of a stock is the one that stands
        try:
            call = (read or read_notice)(record, folder, filed=filed.date())
        except Exception as exc:
            logger.warning("Call notice for %s not read: %s", symbol, exc)
            failed.add(symbol)
            continue
        finally:
            time.sleep(pause)
        if call is not None:
            found[symbol] = (record, call)
    # A stock whose every notice read as an investor meet is still marked as looked at.
    for symbol, _, record in fresh[:limit]:
        if symbol not in found and symbol not in failed:
            found[symbol] = (record, None)
    return found


def fetch_board_meetings(today: date) -> list[dict[str, Any]]:
    from nse import NSE

    with TemporaryDirectory(prefix="nse_meetings_") as folder, NSE(download_folder=folder, timeout=60, server=False) as nse:
        return nse.boardMeetings(
            index="equities",
            from_date=datetime.combine(today, datetime.min.time()),
            to_date=datetime.combine(today + timedelta(days=RESULTS_HORIZON_DAYS), datetime.min.time()),
        )


def run(repo, *, now: datetime | None = None, dry_run: bool = False) -> dict[str, int]:
    now = now or datetime.now(UTC)
    today = now.astimezone(IST).date()
    counts = {"results": 0, "calls": 0, "read": 0, "written": 0}
    try:
        stored = repo.upcoming_events()
    except Exception as exc:
        logger.warning(
            "Upcoming events not recorded: upcoming_events is unreadable (%s). Apply storage/upcoming_events_schema.sql.", exc
        )
        return counts

    results = result_dates(fetch_board_meetings(today), today=today)
    with TemporaryDirectory(prefix="call_notices_") as folder:
        try:
            notices = collect_notices(stored, folder=Path(folder))
        except Exception as exc:  # the result dates are still worth writing
            logger.warning("Call notices unavailable (%s)", exc)
            notices = {}
    rows = merge(stored, results, notices, today=today, checked_at=now)
    counts.update(
        results=sum(1 for row in rows if row["next_result_date"]),
        calls=sum(1 for row in rows if row["next_call_at"] or row["next_call_date"]),
        read=len(notices),
    )
    if rows and not dry_run:
        counts["written"] = repo.upsert_upcoming_events(rows)
    logger.info("%s upcoming events: %s%s", repo.market, counts, " (dry run, nothing written)" if dry_run else "")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE", help="NSE (the only market with these feeds)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
