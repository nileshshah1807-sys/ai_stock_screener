"""Backfill ``pct_change_1d`` for an already-published dashboard run.

The screener began emitting ``Pct_Change_1D`` in output schema 4.2.0. Runs
published before that carry null, which the grid honestly renders as a dash --
but a whole column of dashes is not much use, and waiting for the next
scheduled run means a day of it. This patches the current snapshot from history
that is already in Supabase.

**A backfilled value is raw-basis, and that is a real difference.** The screener
computes ``Pct_Change_1D`` from *adjusted* closes, so an ex-dividend or split
session reports the holder's return. This worker can only difference two
``screener_history.current_price`` values, which are *unadjusted*, so on such a
session it reports the mechanical price cut instead -- a 1:10 split reads as
-90%. On an ordinary session the two agree exactly. The same limitation already
applies to the stock page's derived 1D tile, which reads the same history tail.

Two consequences worth keeping in mind:

* Runs patched here keep raw-basis values permanently. The next scheduled run
  writes a *new* ``run_date``, so it never revisits and corrects this one.
* Rows that already have a value are skipped unless ``--overwrite`` is passed,
  so rerunning this cannot downgrade an adjusted value to a raw one.

Independent of the daily publisher, like ``logo_domain_backfill``. It patches
one nullable numeric column, never touches ``payload``, and is safe to rerun.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date

from storage.dashboard_repository import DashboardRepository

logger = logging.getLogger("session_change_backfill")

# Consecutive NSE sessions are one calendar day apart, three across a weekend,
# and up to about five when a holiday abuts one. Beyond that the previous
# published run is probably not the previous *session*, and differencing them
# would publish a multi-session move under a column labelled 1D.
DEFAULT_MAX_GAP_DAYS = 5


@dataclass
class BackfillSummary:
    run_date: str
    previous_run_date: str | None = None
    gap_days: int | None = None
    snapshot_rows: int = 0
    candidates: int = 0
    computed: int = 0
    no_previous_close: int = 0
    unusable_previous_close: int = 0
    written: int = 0
    failed: int = 0
    dry_run: bool = False


def resolve_run_date(
    repository: DashboardRepository,
    requested: str | None,
) -> str:
    if requested:
        return date.fromisoformat(requested).isoformat()
    latest = repository.latest_completed_run()
    if not latest or not latest.get("run_date"):
        raise RuntimeError("Supabase has no completed dashboard run to backfill")
    return date.fromisoformat(str(latest["run_date"])).isoformat()


def session_change_pct(latest: float, previous: float) -> float | None:
    """Percentage move between two closes, or None if the base is unusable.

    A non-positive or non-finite previous close is missing evidence, not a
    100% move. Rounded to two places to match ``numeric(10,2)`` so the value
    the worker logs is the value Postgres stores.
    """
    if previous is None or latest is None:
        return None
    if not (previous > 0):
        return None
    return round((latest / previous - 1.0) * 100.0, 2)


def backfill_session_change(
    repository: DashboardRepository,
    *,
    run_date: str | None = None,
    previous_run_date: str | None = None,
    limit: int = 0,
    overwrite: bool = False,
    max_gap_days: int = DEFAULT_MAX_GAP_DAYS,
    allow_gap: bool = False,
    dry_run: bool = False,
) -> BackfillSummary:
    """Compute and patch the session move for one snapshot."""
    target = resolve_run_date(repository, run_date)
    previous = (
        date.fromisoformat(previous_run_date).isoformat()
        if previous_run_date
        else repository.previous_completed_run_date(target)
    )

    summary = BackfillSummary(run_date=target, dry_run=dry_run)
    if not previous:
        raise RuntimeError(
            f"No completed run published before {target}; there is no prior "
            "session to difference against."
        )

    summary.previous_run_date = previous
    gap = (date.fromisoformat(target) - date.fromisoformat(previous)).days
    summary.gap_days = gap
    if gap > max_gap_days and not allow_gap:
        raise RuntimeError(
            f"{previous} is {gap} calendar days before {target}, which suggests "
            "a missed run rather than the previous session. Differencing them "
            "would publish a multi-session move as a 1-day change. Pass "
            "--allow-gap to override, or --previous-run-date to name the right "
            "session."
        )
    logger.info(
        "Differencing %s against %s (%s calendar day(s) apart)",
        target,
        previous,
        gap,
    )

    state = repository.snapshot_session_change_state(target)
    summary.snapshot_rows = len(state)
    if not state:
        raise RuntimeError(f"Snapshot {target} has no rows")

    latest_closes = repository.history_closes(target)
    previous_closes = repository.history_closes(previous)
    logger.info(
        "History closes: %s on %s, %s on %s",
        len(latest_closes),
        target,
        len(previous_closes),
        previous,
    )

    candidates = sorted(
        symbol
        for symbol, value in state.items()
        if overwrite or value is None
    )
    if limit > 0:
        candidates = candidates[:limit]
    summary.candidates = len(candidates)

    for index, symbol in enumerate(candidates, start=1):
        latest = latest_closes.get(symbol)
        prior = previous_closes.get(symbol)
        if latest is None or prior is None:
            # A symbol absent from either session has no one-day move. New
            # listings and rows the previous run failed to collect land here,
            # and leaving them null is the honest answer.
            summary.no_previous_close += 1
            continue

        change = session_change_pct(latest, prior)
        if change is None:
            summary.unusable_previous_close += 1
            continue

        summary.computed += 1
        if dry_run:
            continue

        try:
            repository.patch_snapshot_row(
                target,
                symbol,
                {"pct_change_1d": change},
            )
        except Exception as exc:  # one bad row must not lose the whole pass
            summary.failed += 1
            logger.warning("%s patch failed: %s", symbol, exc)
            continue
        summary.written += 1

        if index % 250 == 0 or index == len(candidates):
            logger.info(
                "Progress %s/%s: computed=%s written=%s no_previous=%s failed=%s",
                index,
                len(candidates),
                summary.computed,
                summary.written,
                summary.no_previous_close,
                summary.failed,
            )

    if dry_run:
        logger.info(
            "Dry run: would patch %s of %s candidate row(s)",
            summary.computed,
            summary.candidates,
        )
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill pct_change_1d on a published snapshot from screener_history. "
            "Values are raw-basis; see the module docstring."
        )
    )
    parser.add_argument(
        "--run-date",
        help="Snapshot date in YYYY-MM-DD format; defaults to latest completed run.",
    )
    parser.add_argument(
        "--previous-run-date",
        help=(
            "Session to difference against; defaults to the completed run "
            "published immediately before --run-date."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum rows to patch; 0 means every candidate row.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Also patch rows that already carry a value. Off by default so a "
            "rerun cannot replace an adjusted-basis value with a raw one."
        ),
    )
    parser.add_argument(
        "--max-gap-days",
        type=int,
        default=DEFAULT_MAX_GAP_DAYS,
        help=(
            "Refuse if the two run dates are further apart than this "
            f"(default: {DEFAULT_MAX_GAP_DAYS})."
        ),
    )
    parser.add_argument(
        "--allow-gap",
        action="store_true",
        help="Proceed even when the gap check fails.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report without writing anything.",
    )
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.max_gap_days < 1:
        parser.error("--max-gap-days must be at least 1")
    for field in ("run_date", "previous_run_date"):
        value = getattr(args, field)
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                parser.error(f"--{field.replace('_', '-')} must use YYYY-MM-DD")
    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = parse_args(argv)
    repository = DashboardRepository.from_environment()
    summary = backfill_session_change(
        repository,
        run_date=args.run_date,
        previous_run_date=args.previous_run_date,
        limit=args.limit,
        overwrite=args.overwrite,
        max_gap_days=args.max_gap_days,
        allow_gap=args.allow_gap,
        dry_run=args.dry_run,
    )
    print(json.dumps(asdict(summary), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
