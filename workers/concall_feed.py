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
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from screener.numeric import round_half_up, safe_float
from sentiment.outlook import OUTLOOK_VERSION, outlook_items
from transcripts.recordings import SPEECH_METHOD_PREFIX

logger = logging.getLogger(__name__)

#: How far back the page goes: the season in progress and the one before it.
FEED_DAYS = 200
HIGHLIGHTS = 3
SOURCE_RECORDING = "recording"
SOURCE_TRANSCRIPT = "transcript"


def _one(value: Any) -> dict[str, Any]:
    """PostgREST embeds a to-one relation as an object, or a one-item list."""
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, dict) else {}


def _newest(rows: Any) -> dict[str, Any]:
    rows = [row for row in rows or [] if isinstance(row, dict)]
    return max(rows, key=lambda row: str(row.get("created_at") or ""), default={})


def _from_recording(transcript: dict[str, Any]) -> bool:
    method = str(_one(transcript.get("transcript_documents")).get("extraction_method") or "")
    return method.startswith(SPEECH_METHOD_PREFIX)


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
        quarter = str(transcript.get("quarter") or "")[:10]
        if symbol and quarter and transcript.get("call_date"):
            calls.setdefault((symbol, quarter), []).append(transcript)

    rows = []
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
            "source": SOURCE_TRANSCRIPT if filed else SOURCE_RECORDING,
            "tone_score": None if tone is None else round_half_up(tone, 2),
            "tone_percentile": None,
            "guidance_direction": sentiment.get("guidance_direction"),
            "outlook_score": None if outlook_score is None else round_half_up(outlook_score, 2),
            "highlights": highlights(outlook.get("extraction")),
        })
    _rank_tone(rows)
    return sorted(rows, key=lambda row: (row["call_date"], row["symbol"]), reverse=True)


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
        try:
            counts["written"] = repo.replace_concall_feed(rows, since)
        except Exception as exc:  # noqa: BLE001 - the page keeps its previous rows
            logger.warning(
                "%s concall feed not written (%s). Apply storage/concalls_schema.sql.", repo.market, exc
            )
    logger.info("%s concall feed: %s%s", repo.market, counts, " (dry run, nothing written)" if dry_run else "")
    return counts


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
