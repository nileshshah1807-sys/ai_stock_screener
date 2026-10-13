"""The dashboard's list of earnings calls, derived from the transcript tables.

The transcript tables hold the full text of every call and are private to the
service role. The Concalls page needs none of the text: a row per call with
its date, where its text came from, how it scored and the three things most
worth knowing about it. This writes those rows to ``concall_feed``.

One row is one call -- a company's call for a quarter. While only the
recording has been transcribed (`workers/call_recordings.py`) the row reads
from that and says so; once the company files its transcript, the same row
reads from the filed text and keeps the day the call was held.

Display evidence only. Nothing scores from this table: the screener reads the
tone score and the outlook from the transcript tables themselves.

Usage::

    python -m workers.concall_feed            # the market in $MARKET
    python -m workers.concall_feed --dry-run
"""

from __future__ import annotations

import argparse
import logging
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from scoring.transcript_enricher import _outlook_breakdown
from screener.numeric import round_half_up, safe_float
from sentiment.outlook import OUTLOOK_VERSION, STANCES, compare_outlooks, outlook_items
from storage.supabase_repository import PREVIOUS_CALL_MIN_GAP_DAYS
from transcripts.periods import reporting_period_end_for_call
from transcripts.recordings import VENDOR_METHOD_PREFIX, is_provisional

logger = logging.getLogger(__name__)

#: How far back the page goes: the season in progress and the one before it.
FEED_DAYS = 200
HIGHLIGHTS = 3
SOURCE_RECORDING = "recording"
SOURCE_TRANSCRIPT = "transcript"
#: A vendor's transcript of the call, standing in as a recording's text does.
SOURCE_VENDOR = "vendor"

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _quarter(transcript: dict[str, Any]) -> str | None:
    """The quarter end a stored call explains, as a date.

    Transcripts stored by an early version of the worker carry a label
    ("2026-Q3") where later ones carry the quarter end. The label does not say
    whose third quarter, so those are dated from the call by the worker's own
    rule -- the one that produced every later row's quarter.
    """
    stored = str(transcript.get("quarter") or "")[:10]
    if _ISO_DATE.fullmatch(stored):
        return stored
    try:
        return reporting_period_end_for_call(date.fromisoformat(str(transcript.get("call_date"))[:10])).isoformat()
    except ValueError:
        return None


def _one(value: Any) -> dict[str, Any]:
    """PostgREST embeds a to-one relation as an object, or a one-item list."""
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, dict) else {}


def _newest(rows: Any) -> dict[str, Any]:
    rows = [row for row in rows or [] if isinstance(row, dict)]
    return max(rows, key=lambda row: str(row.get("created_at") or ""), default={})


def _method(transcript: dict[str, Any]) -> str:
    return str(_one(transcript.get("transcript_documents")).get("extraction_method") or "")


def _from_recording(transcript: dict[str, Any]) -> bool:
    """Whether the text stands in for the filed transcript: a recording's, or a vendor's."""
    return is_provisional(_method(transcript))


def _source(transcript: dict[str, Any]) -> str:
    if not _from_recording(transcript):
        return SOURCE_TRANSCRIPT
    return SOURCE_VENDOR if _method(transcript).startswith(VENDOR_METHOD_PREFIX) else SOURCE_RECORDING


def highlights(extraction: dict[str, Any] | None, limit: int = HIGHLIGHTS) -> list[dict[str, str]]:
    """The scored statements of a call that moved its outlook most, one per quote.

    Each is something the call said, with the sentence it was read from --
    the outlook keeps no item whose sentence was not found in the text.
    """
    if not isinstance(extraction, dict):
        return []
    try:
        items = outlook_items(extraction)
    except (KeyError, TypeError, AttributeError):
        # A stored extraction from a shape this version does not read.
        return []
    chosen: list[dict[str, str]] = []
    quotes: set[str] = set()
    for reason, points, quote in sorted(items, key=lambda item: -abs(item[1])):
        quote = str(quote or "").strip()
        if not points or (quote and quote in quotes):
            continue
        quotes.add(quote)
        chosen.append({
            "text": str(reason),
            "tone": "positive" if points > 0 else "negative",
            "quote": quote,
        })
        if len(chosen) == limit:
            break
    return chosen


def management_stance(extraction: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """``(view, quote)`` as the outlook read it, or ``(None, None)``.

    None for a call read before the outlook asked the question, and for one
    the model could not place: neither is a neutral call.
    """
    stance = extraction.get("stance") if isinstance(extraction, dict) else None
    view = stance.get("view") if isinstance(stance, dict) else None
    if view not in STANCES or view == "unknown":
        return None, None
    return view, str(stance.get("quote") or "").strip() or None


def _verified_outlook(outlook: dict[str, Any]) -> bool:
    """Whether a stored outlook is one the screener would score: something verified."""
    return safe_float(outlook.get("outlook_score")) is not None and int(
        safe_float(outlook.get("verified_fields")) or 0
    ) > 0


def outlook_detail(
    call_date: str, outlook: dict[str, Any], previous: tuple[str, dict[str, Any]] | None
) -> dict[str, Any] | None:
    """A call's outlook in the fields the stock page's panel reads from a run.

    The screener writes these into every snapshot row
    (`TranscriptEnricher._attach_outlooks`), which is why the panel shows a
    call only after a run has scored it. Built here by the same rules and
    under the same names, the panel can show a call the evening it is read and
    hand over to the run's own row without changing what it says.

    None where the screener would attach nothing: an outlook with no verified
    item says nothing, which is not a neutral 50.
    """
    if not _verified_outlook(outlook):
        return None
    score = safe_float(outlook["outlook_score"])
    extraction = outlook.get("extraction") or {}
    detail: dict[str, Any] = {
        "Transcript_Call_Date": call_date,
        "Transcript_Outlook_Score": round_half_up(score, 2),
        "Transcript_Outlook_Points": _outlook_breakdown(extraction),
    }
    if previous and _verified_outlook(previous[1]):
        previous_date, earlier = previous
        previous_score = safe_float(earlier["outlook_score"])
        detail |= {
            "Transcript_Outlook_Previous_Call_Date": previous_date,
            "Transcript_Outlook_Previous_Score": round_half_up(previous_score, 2),
            "Transcript_Outlook_QoQ_Delta": round_half_up(score - previous_score, 2),
            "Transcript_Outlook_QoQ_Items": compare_outlooks(earlier.get("extraction") or {}, extraction),
        }
    return detail


def _days_apart(earlier: str, later: str) -> int:
    try:
        return (date.fromisoformat(later[:10]) - date.fromisoformat(earlier[:10])).days
    except ValueError:
        return -1


def build_feed(
    transcripts: Iterable[dict[str, Any]],
    companies: dict[str, str | None],
    held: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """One row per (symbol, quarter) from the stored transcripts of a window.

    ``held`` is the call date each row already carries. A filed transcript is
    dated by its filing and replaces the recording's, so without it a call
    would move to the day its transcript was filed.
    """
    held = held or {}
    calls: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for transcript in transcripts:
        symbol = str(transcript.get("symbol") or "").strip().upper()
        quarter = _quarter(transcript)
        if symbol and quarter and transcript.get("call_date"):
            calls.setdefault((symbol, quarter), []).append(transcript)

    rows = []
    # Each row's outlook and the date of the transcript it was read from, in
    # row order and again by company for finding the quarter before.
    read: list[tuple[str, dict[str, Any]]] = []
    outlooks: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for (symbol, quarter), stored in calls.items():
        filed = [transcript for transcript in stored if not _from_recording(transcript)]
        # The filed transcript wins; among several of one kind, the latest.
        chosen = max(filed or stored, key=lambda transcript: str(transcript.get("call_date")))
        sentiment = _newest(chosen.get("transcript_sentiments"))
        outlook = _newest(
            row for row in chosen.get("transcript_outlooks") or []
            if isinstance(row, dict) and row.get("analysis_version") == OUTLOOK_VERSION
        )
        tone = safe_float(sentiment.get("overall_score"))
        outlook_score = safe_float(outlook.get("outlook_score"))
        stance, stance_quote = management_stance(outlook.get("extraction"))
        rows.append({
            "symbol": symbol,
            "quarter": quarter,
            "company": companies.get(symbol),
            # The day the call was held is the earliest it was heard of: the
            # recording's date, where there was one.
            "call_date": min(
                [str(transcript.get("call_date"))[:10] for transcript in stored]
                + [known for known in [held.get((symbol, quarter))] if known]
            ),
            "source": _source(chosen),
            "tone_score": None if tone is None else round_half_up(tone, 2),
            "tone_percentile": None,
            "guidance_direction": sentiment.get("guidance_direction"),
            "management_stance": stance,
            "management_stance_quote": stance_quote,
            "outlook_score": None if outlook_score is None else round_half_up(outlook_score, 2),
            "highlights": highlights(outlook.get("extraction")),
            "outlook_detail": None,
        })
        # Dated as the screener dates it -- by the transcript read -- so "the
        # quarter before" is the same call here as in a run.
        read.append((str(chosen.get("call_date"))[:10], outlook))
        outlooks.setdefault(symbol, []).append(read[-1])
    for row, (call_date, outlook) in zip(rows, read):
        row["outlook_detail"] = outlook_detail(
            row["call_date"], outlook, _previous_call(outlooks[row["symbol"]], call_date)
        )
    _rank_tone(rows)
    return sorted(rows, key=lambda row: (row["call_date"], row["symbol"]), reverse=True)


def _previous_call(
    calls: list[tuple[str, dict[str, Any]]], call_date: str
) -> tuple[str, dict[str, Any]] | None:
    """The company's latest call at least a results season before ``call_date``.

    The gap is `latest_outlooks`' own: a second document from one season is
    not a previous quarter.
    """
    earlier = [
        call for call in calls if _days_apart(call[0], call_date) >= PREVIOUS_CALL_MIN_GAP_DAYS
    ]
    return max(earlier, key=lambda call: call[0], default=None)


def _rank_tone(rows: list[dict[str, Any]]) -> None:
    """Where each call's tone stands among the window's scored calls, 0-100.

    The tone score has no natural scale -- most calls sit within a few points
    of each other -- so the page labels a call by its standing, not its score.
    A call with no score has no standing; it is not the lowest.
    """
    scored = sorted(row["tone_score"] for row in rows if row["tone_score"] is not None)
    if len(scored) < 2:
        return
    for row in rows:
        if row["tone_score"] is None:
            continue
        below = sum(1 for score in scored if score < row["tone_score"])
        equal = sum(1 for score in scored if score == row["tone_score"])
        row["tone_percentile"] = round_half_up(100.0 * (below + 0.5 * equal) / len(scored), 2)


def run(repo, *, today: date | None = None, dry_run: bool = False) -> dict[str, int]:
    today = today or datetime.now(UTC).date()
    since = (today - timedelta(days=FEED_DAYS)).isoformat()
    counts = {"calls": 0, "from_recording": 0, "written": 0}
    try:
        held = repo.concall_call_dates()
    except Exception as exc:  # noqa: BLE001 - nothing to write to either
        logger.warning("%s concall feed unreadable (%s). Apply storage/concalls_schema.sql.", repo.market, exc)
        return counts
    rows = build_feed(repo.calls_since(since), repo.snapshot_companies(), held)
    counts["calls"] = len(rows)
    counts["from_recording"] = sum(1 for row in rows if row["source"] == SOURCE_RECORDING)
    if not dry_run:
        counts["written"] = _write(repo, rows, since)
    logger.info("%s concall feed: %s%s", repo.market, counts, " (dry run, nothing written)" if dry_run else "")
    return counts


# Columns added after the table first shipped, newest first.
STANCE_COLUMNS = ("outlook_detail", "management_stance", "management_stance_quote")


def _write(repo, rows: list[dict[str, Any]], since: str) -> int:
    """Write the feed; without its newer columns where the table lacks them.

    Some columns arrived after the table. A deployment that has not re-applied
    the schema keeps its page -- every call, minus what those columns hold --
    instead of losing the feed to an unknown column.
    """
    try:
        return repo.replace_concall_feed(rows, since)
    except Exception as exc:  # noqa: BLE001 - try again as an older table would accept it
        logger.warning(
            "%s concall feed rejected (%s); writing what an older table accepts. "
            "Re-apply storage/concalls_schema.sql.",
            repo.market,
            exc,
        )
    # A table that predates the vendor source refuses the word. Such a call is
    # provisional either way, which is what the older word says.
    if any(row["source"] == SOURCE_VENDOR for row in rows):
        rows = [{**row, "source": SOURCE_RECORDING} if row["source"] == SOURCE_VENDOR else row for row in rows]
        try:
            return repo.replace_concall_feed(rows, since)
        except Exception:  # noqa: BLE001 - the columns, then
            pass
    try:
        older = [{key: value for key, value in row.items() if key not in STANCE_COLUMNS} for row in rows]
        return repo.replace_concall_feed(older, since)
    except Exception as exc:  # noqa: BLE001 - the page keeps its previous rows
        logger.warning("%s concall feed not written (%s). Apply storage/concalls_schema.sql.", repo.market, exc)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--market", default=None, help="NSE or US (default: $MARKET)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
