"""Resumable backfill of the point-in-time backtest archive.

Ingests the exchange archive the P0 walk-forward test runs on: one bhavcopy per
session, the derived trading calendar, the corporate-action feed and the security
master. Every stage is resumable, so this can be run in bounded chunks and
interrupted freely -- a later invocation continues where the previous one stopped
rather than starting again.

Usage::

    python -m tools.backfill_backtest_archive --start 2022-07-01 --max-fetches 200
    python -m tools.backfill_backtest_archive --status
    python -m tools.backfill_backtest_archive --start 2022-07-01 --master-only

The bhavcopy stage is the long pole: one network round trip per session, roughly
1,000 sessions for the agreed 2022-07 window. ``--max-fetches`` exists so that
cost can be spread out and so a rate-limited run degrades into a partial one
instead of a failed one.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import logging
from pathlib import Path
import sys
import time

logger = logging.getLogger("backfill")

DEFAULT_ROOT = Path("reports_advanced/backtest")
DEFAULT_START = "2022-07-01"


def _parse_date(value):
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _paths(root):
    root = Path(root)
    return {
        "root": root,
        "bhavcopy": root / "bhavcopy",
        "calendar": root / "calendar.csv",
        "actions": root / "corporate_actions.csv",
        "master": root / "security_master.csv",
        "manifest": root / "archive_manifest.json",
    }


def run_status(root):
    from backtest.bhavcopy import BhavcopyStore
    from backtest.calendar import CalendarLedger
    from backtest.security_master import SecurityMaster

    paths = _paths(root)
    store = BhavcopyStore(paths["bhavcopy"])
    ledger = CalendarLedger(paths["calendar"])
    cached = store.cached_dates()
    sessions = ledger.sessions()
    master = SecurityMaster.load(paths["master"])

    print(f"archive root        : {paths['root']}")
    print(f"cached day-files    : {len(cached)}")
    if cached:
        print(f"  span              : {cached[0]} -> {cached[-1]}")
    print(f"confirmed sessions  : {len(sessions)}")
    print(f"unresolved weekdays : {len(ledger.unresolved())}")
    print(f"actions cached      : {paths['actions'].exists()}")
    print(f"securities in master: {len(master)}")
    if len(master):
        print(f"  summary           : {json.dumps(master.survivorship_summary())}")
    return 0


def run_bhavcopy(root, start, end, max_fetches, holidays=()):
    from backtest.bhavcopy import BhavcopyStore
    from backtest.calendar import CalendarLedger, build_calendar

    paths = _paths(root)
    store = BhavcopyStore(paths["bhavcopy"])
    ledger = CalendarLedger(paths["calendar"])

    started = time.monotonic()
    state = {"last": None}

    def on_progress(day, fetched, failed):
        state["last"] = day
        if fetched and fetched % 25 == 0:
            elapsed = time.monotonic() - started
            rate = fetched / elapsed if elapsed else 0.0
            logger.info(
                "  %s | fetched %d, unavailable %d | %.2f sessions/s",
                day,
                fetched,
                failed,
                rate,
            )

    calendar = build_calendar(
        store,
        start,
        end,
        ledger=ledger,
        market_holidays=holidays,
        max_fetches=max_fetches,
        on_progress=on_progress,
    )
    elapsed = time.monotonic() - started
    logger.info(
        "Bhavcopy stage finished in %.1fs; %d confirmed sessions, reached %s",
        elapsed,
        len(calendar),
        state["last"],
    )
    return calendar


def run_actions(root, start, end):
    from backtest.corporate_actions import ActionStore

    paths = _paths(root)
    store = ActionStore(paths["actions"])
    frame = store.fetch(start, end)
    if frame.empty:
        logger.warning("Corporate-action feed returned nothing for %s..%s", start, end)
        return frame
    by_type = frame["Action_Type"].value_counts().to_dict()
    unparsed = frame[frame["Parse_Status"].astype(str).str.startswith("unparsed")]
    logger.info("Actions ingested: %d %s", len(frame), json.dumps(by_type))
    if len(unparsed):
        # Loud on purpose: an unparsed ratio silently treated as 1.0 would put a
        # fabricated ~50% move into the adjusted series.
        logger.warning(
            "%d actions have an unparsed ratio and will BLOCK their securities: %s",
            len(unparsed),
            sorted(set(unparsed["Symbol"].astype(str)))[:20],
        )
    return frame


def run_master(root, terminal_absence_sessions=None):
    from backtest.bhavcopy import BhavcopyStore
    from backtest.calendar import CalendarLedger
    from backtest.security_master import SecurityMaster, build_master

    paths = _paths(root)
    store = BhavcopyStore(paths["bhavcopy"])
    ledger = CalendarLedger(paths["calendar"])
    sessions = ledger.sessions()
    if not sessions:
        logger.error("No confirmed sessions yet; run the bhavcopy stage first")
        return None
    frame = build_master(
        store, sessions, terminal_absence_sessions=terminal_absence_sessions
    )
    master = SecurityMaster(frame)
    master.save(paths["master"])
    summary = master.survivorship_summary(as_of=sessions[-1])
    logger.info("Security master: %s", json.dumps(summary))
    reused = master.reused_symbols()
    if reused:
        logger.warning(
            "%d tickers mapped to more than one security; resolve by date only: %s",
            len(reused),
            sorted(reused)[:15],
        )
    return master


def write_manifest(root, start, end):
    """Record what the archive covers so a run report can cite its inputs."""
    from backtest.bhavcopy import BHAVCOPY_SCHEMA_VERSION, BhavcopyStore
    from backtest.calendar import CalendarLedger
    from backtest.corporate_actions import ACTIONS_SCHEMA_VERSION
    from backtest.security_master import MASTER_SCHEMA_VERSION, SecurityMaster

    paths = _paths(root)
    ledger = CalendarLedger(paths["calendar"])
    sessions = ledger.sessions()
    master = SecurityMaster.load(paths["master"])
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "requested_window": {"start": str(start), "end": str(end)},
        "schema_versions": {
            "bhavcopy": BHAVCOPY_SCHEMA_VERSION,
            "security_master": MASTER_SCHEMA_VERSION,
            "corporate_actions": ACTIONS_SCHEMA_VERSION,
        },
        "sessions": {
            "confirmed": len(sessions),
            "first": sessions[0].isoformat() if sessions else None,
            "last": sessions[-1].isoformat() if sessions else None,
            "unresolved_weekdays": len(ledger.unresolved()),
        },
        "day_files": len(BhavcopyStore(paths["bhavcopy"]).cached_dates()),
        "securities": master.survivorship_summary(
            as_of=sessions[-1] if sessions else None
        ),
    }
    paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
    paths["manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Manifest written: %s", paths["manifest"])
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None, help="defaults to today")
    parser.add_argument(
        "--max-fetches",
        type=int,
        default=None,
        help="cap bhavcopy downloads this run; omit for no cap",
    )
    parser.add_argument("--status", action="store_true", help="report and exit")
    parser.add_argument("--skip-bhavcopy", action="store_true")
    parser.add_argument("--skip-actions", action="store_true")
    parser.add_argument(
        "--master-only",
        action="store_true",
        help="rebuild the security master from cached day-files only",
    )
    parser.add_argument(
        "--terminal-absence-sessions",
        type=int,
        default=None,
        help="sessions absent before an absence is treated as a delisting",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    if args.status:
        return run_status(args.root)

    start = _parse_date(args.start)
    end = _parse_date(args.end) if args.end else date.today()
    if end < start:
        parser.error("--end must not precede --start")

    if args.master_only:
        run_master(args.root, args.terminal_absence_sessions)
        write_manifest(args.root, start, end)
        return 0

    if not args.skip_bhavcopy:
        logger.info("Bhavcopy stage: %s -> %s", start, end)
        run_bhavcopy(args.root, start, end, args.max_fetches)

    if not args.skip_actions:
        logger.info("Corporate-action stage: %s -> %s", start, end)
        run_actions(args.root, start, end)

    run_master(args.root, args.terminal_absence_sessions)
    write_manifest(args.root, start, end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
