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
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

from transcripts.collector import is_earnings_transcript
from transcripts.recordings import is_recording_notice

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
#: How far ahead the board-meeting feed is read.
RESULTS_HORIZON_DAYS = 60
#: How far back a run looks for call notices: a call is announced a median 7 days ahead, p90 13,
#: p95 14, longest 19 (112 notices read 24-31 Oct 2026), so 14 days reaches all but the rare early one.
NOTICE_LOOKBACK_DAYS = 14
#: Notices read in one run (the archive refuses a burst); the rest wait.
MAX_NOTICES_PER_RUN = 60
#: Seconds between two downloads from the archive.
NOTICE_PAUSE_SECONDS = 0.7
#: Stocks read between two writes: a run cut short keeps what it had read.
BATCH_STOCKS = 10
#: Stop starting new stocks after this long; the step's own timeout is 8 minutes and
#: opening the exchange session alone can take 35 s on a runner.
TIME_BUDGET_SECONDS = 5 * 60

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

    A reading with no am/pm is the 24-hour clock only as 'HH:MM' from 13:00 ('16:00') or with
    'hrs'; '10:00' or '4.30' alone could be either half of the day, and a time is never guessed.
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
        elif marker != "hrs" and (":" not in match.group(0) or hour < 13):
            continue
        return clock(hour, minute)
    return None


def call_schedule(text: str, *, filed: date) -> Call | None:
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


Call = tuple[date, clock | None]


def read_notice(record: dict[str, Any], fetch: Callable[[str], Path], *, filed: date) -> Call | None:
    """The call a notice announces; None for an investor meet or a notice with no stated date."""
    import pymupdf

    path = fetch(str(record["attchmntFile"]))
    if path.read_bytes()[:5] != b"%PDF-":
        raise ValueError("NSE attachment is not a valid PDF")
    with pymupdf.open(path) as document:
        text = "\n".join(page.get_text("text") for page in document)
    return call_schedule(text, filed=filed) if is_earnings_call(text) else None


def _call_fields(call: Call | None, url: str) -> dict[str, Any]:
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


def _looked_before(old: dict[str, Any], checked_at: datetime) -> datetime:
    """When the worker last read this stock's notices; for a stock it has not, the start of the window."""
    if old.get("updated_at"):
        return datetime.fromisoformat(str(old["updated_at"]))
    return checked_at - timedelta(days=NOTICE_LOOKBACK_DAYS)


def _same(column: str, new: Any, old: Any) -> bool:
    """Equal as stored: Postgres hands a timestamp back in UTC, whatever offset it was written in."""
    if column == "next_call_at" and new and old:
        return datetime.fromisoformat(str(new)) == datetime.fromisoformat(str(old))
    return new == old


_COLUMNS = ("company", "next_result_date", "result_purpose", "next_call_at", "next_call_date", "call_source_url")


def merge(
    stored: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]] | None,
    notices: dict[str, tuple[dict[str, Any], Call | None]],
    *,
    today: date,
    checked_at: datetime,
) -> list[dict[str, Any]]:
    """The rows to write: those whose content changed, and every stock whose notices were read.

    ``results`` is None when the board-meeting feed was not had: the stored result dates stand
    (a passed one is still cleared). ``updated_at`` advances only for a stock whose notices were read;
    a stock new to the table starts the notice window over, so notices filed in it are still read.

    ``notices`` maps a symbol to its newest earnings-call notice and what it announced
    (None: read, but no call date in it -- the stock keeps the call it had).
    """
    rows = []
    for symbol in sorted(set(stored) | set(results or ()) | set(notices)):
        old = stored.get(symbol, {})
        row = {column: old.get(column) for column in _COLUMNS}
        if results is not None:
            row.update({"next_result_date": None, "result_purpose": None, **results.get(symbol, {})})
        if row["next_result_date"] and date.fromisoformat(str(row["next_result_date"])[:10]) < today:
            row.update(next_result_date=None, result_purpose=None)
        if symbol in notices:
            record, call = notices[symbol]
            if call is not None:
                row.update(_call_fields(call, str(record["attchmntFile"])))
            row["company"] = row["company"] or record.get("sm_name")
        called = _call_day(row)
        if called is not None and called < today:
            row.update(next_call_at=None, next_call_date=None, call_source_url=None)
        if symbol in notices or any(not _same(c, row[c], old.get(c)) for c in _COLUMNS if c != "company"):
            looked = checked_at if symbol in notices else _looked_before(old, checked_at)
            rows.append({"symbol": symbol, **row, "updated_at": looked.isoformat(timespec="seconds")})
    return rows


def pending_notices(stored: dict[str, dict[str, Any]], records: list[dict[str, Any]]) -> list[tuple[str, datetime, dict[str, Any]]]:
    """The call notices filed since the worker last looked at their stock, newest first."""
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
    return sorted(fresh, key=lambda item: item[1], reverse=True)


def read_notices(
    fresh: list[tuple[str, datetime, dict[str, Any]]],
    fetch: Callable[[str], Path],
    *,
    pause: float | None = None,
    limit: int = MAX_NOTICES_PER_RUN,
    deadline: float | None = None,
    read: Callable[..., Call | None] | None = None,
) -> Iterator[tuple[str, dict[str, Any], Call | None]]:
    """Each stock's newest earnings-call notice and what it announced, one stock at a time.

    A stock is yielded once all its fresh notices are settled: the newest one that reads as
    an earnings call stands (an investor meet falls through to an older notice); one that
    reads as none is yielded with ``None`` so the stock is still marked as looked at. A
    stock whose notice would not download is left alone, and so is one the ``limit`` of
    notices, or the ``deadline`` (a ``time.monotonic()`` value), cut short.
    """
    by_stock: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for symbol, filed, record in fresh:
        by_stock.setdefault(symbol, []).append((filed, record))
    reads = 0
    for symbol, notices in by_stock.items():
        if deadline is not None and time.monotonic() >= deadline:
            return
        result: tuple[str, dict[str, Any], Call | None] | None = (symbol, notices[0][1], None)
        for filed, record in notices:
            if reads >= limit:
                return
            reads += 1
            try:
                call = (read or read_notice)(record, fetch, filed=filed.date())
            except Exception as exc:
                logger.warning("Call notice for %s not read: %s", symbol, exc)
                result = None
                break
            finally:
                time.sleep(NOTICE_PAUSE_SECONDS if pause is None else pause)
            if call is not None:
                result = (symbol, record, call)
                break
        if result:
            yield result


def open_session(folder: str):
    """One exchange session for the run: opening it costs a warm-up request that can take 35 s."""
    from nse import NSE

    return NSE(download_folder=folder, timeout=60, server=False)


def _stamped_window(today: date, days: int) -> tuple[datetime, datetime]:
    return datetime.combine(today, datetime.min.time()), datetime.combine(today + timedelta(days=days), datetime.min.time())


def run(repo, *, now: datetime | None = None, dry_run: bool = False) -> dict[str, int]:
    now = now or datetime.now(UTC)
    today = now.astimezone(IST).date()
    counts = {"results": 0, "calls": 0, "read": 0, "written": 0}
    try:
        stored = dict(repo.upcoming_events())
    except Exception as exc:
        logger.warning(
            "Upcoming events not recorded: upcoming_events is unreadable (%s). Apply storage/upcoming_events_schema.sql.", exc
        )
        return counts

    deadline = time.monotonic() + TIME_BUDGET_SECONDS

    def write(rows: list[dict[str, Any]]) -> None:
        if rows and not dry_run:
            counts["written"] += repo.upsert_upcoming_events(rows)
        for row in rows:  # what is stored now, so the next write sees only what changed
            stored[row["symbol"]] = {**stored.get(row["symbol"], {}), **row}

    with TemporaryDirectory(prefix="upcoming_events_") as folder, open_session(folder) as nse:
        try:
            meetings = nse.boardMeetings(index="equities", from_date=_stamped_window(today, RESULTS_HORIZON_DAYS)[0],
                                         to_date=_stamped_window(today, RESULTS_HORIZON_DAYS)[1])
        except Exception as exc:  # the call notices are still worth reading
            logger.warning("Board meetings unavailable (%s); result dates left as they were", exc)
            meetings = []
        # An empty feed is a failed read, not a market where nobody reports.
        results = result_dates(meetings, today=today) if meetings else None
        write(merge(stored, results, {}, today=today, checked_at=now))

        try:
            start = datetime.combine(today - timedelta(days=NOTICE_LOOKBACK_DAYS), datetime.min.time())
            records = [
                record
                for record in nse.announcements(index="equities", from_date=start, to_date=datetime.combine(today, datetime.max.time()))
                if is_call_notice(record)
            ]
        except Exception as exc:  # the result dates are already written
            logger.warning("Call notices unavailable (%s)", exc)
            records = []

        def fetch(url: str) -> Path:
            return Path(nse.download_document(url))

        batch: dict[str, tuple[dict[str, Any], Call | None]] = {}
        for symbol, record, call in read_notices(pending_notices(stored, records), fetch, deadline=deadline):
            batch[symbol] = (record, call)
            counts["read"] += 1
            if len(batch) >= BATCH_STOCKS:
                write(merge(stored, results, batch, today=today, checked_at=now))
                batch = {}
        if batch:
            write(merge(stored, results, batch, today=today, checked_at=now))

    counts["results"] = sum(1 for row in stored.values() if row.get("next_result_date"))
    counts["calls"] = sum(1 for row in stored.values() if row.get("next_call_at") or row.get("next_call_date"))
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
