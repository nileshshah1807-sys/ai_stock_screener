"""Build and publish the stock-page price series from the backtest archive.

    python -m tools.publish_price_series --dry-run
    python -m tools.publish_price_series

Reads the same archive the point-in-time backtest reads, so the chart and the
model are drawn from one set of corporate-action-adjusted prices. Apply
`storage/price_series_schema.sql` once before the first real run.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_ROOT = Path("reports_advanced/backtest")

logger = logging.getLogger("publish_price_series")


def load_env_file(path=Path(".env")):
    """Read a local ``.env`` into the environment if one is present.

    Deliberately local to this tool rather than added to `screener.runtime`:
    the scheduled workflow sets real environment variables, and giving the
    production config a file-loading side effect would mean a stray `.env` on a
    runner could silently redirect a live run.

    A real variable always wins, so `SUPABASE_URL=... python -m tools...` still
    overrides the file. Written by hand to avoid adding python-dotenv for a
    fifteen-line parser.
    """
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--start", default=None,
                        help="earliest session to publish (default: archive start)")
    parser.add_argument("--end", default=None)
    parser.add_argument("--min-points", type=int, default=30,
                        help="skip securities with fewer observations")
    parser.add_argument("--limit", type=int, default=None,
                        help="publish only the first N symbols, for a bounded trial")
    parser.add_argument("--since", default=None,
                        help="republish only symbols with a corporate action on "
                             "or after this date, instead of the whole universe")
    parser.add_argument("--allow-shrink", action="store_true",
                        help="publish even if the archive is much smaller than "
                             "what is already live (normally a cold cache)")
    parser.add_argument("--dry-run", action="store_true",
                        help="build and report sizes without writing")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    loaded = load_env_file()
    if loaded:
        logger.info("Loaded %s from .env", ", ".join(sorted(loaded)))

    # Constructed before the archive read, which takes about a minute. Missing
    # credentials should fail in the first second, not the sixty-first.
    repository = None
    if not args.dry_run:
        from storage.dashboard_repository import DashboardRepository

        try:
            repository = DashboardRepository.from_environment()
        except ValueError as error:
            hint = [
                str(error),
                "",
                "Set them in .env or the environment, e.g.",
                "  SUPABASE_URL=https://<project>.supabase.co",
                "  SUPABASE_SERVICE_ROLE_KEY=<service role key>",
            ]
            raise SystemExit("\n".join(hint)) from error

    from datetime import date

    from backtest.bhavcopy import BhavcopyStore
    from backtest.calendar import CalendarLedger
    from backtest.corporate_actions import ActionStore, AdjustmentTable
    from backtest.security_master import SecurityMaster
    from workers.price_series_publisher import build_rows, collect_observations, publish

    root = Path(args.root)
    store = BhavcopyStore(root / "bhavcopy")
    sessions = sorted(set(CalendarLedger(root / "calendar.csv").sessions())
                      | set(store.cached_dates()))
    if args.start:
        first = date.fromisoformat(args.start)
        sessions = [day for day in sessions if day >= first]
    if args.end:
        last = date.fromisoformat(args.end)
        sessions = [day for day in sessions if day <= last]
    if len(sessions) < 2:
        raise SystemExit(
            "Fewer than two sessions in the archive. Run "
            "tools.backfill_backtest_archive first."
        )
    logger.info("Sessions: %d, %s -> %s", len(sessions), sessions[0], sessions[-1])

    master_path = root / "security_master.csv"
    if not master_path.exists():
        raise SystemExit(f"No security master at {master_path}")
    master = SecurityMaster.load(master_path)

    actions_path = root / "corporate_actions.csv"
    table = None
    if actions_path.exists():
        table = AdjustmentTable(ActionStore(actions_path).load(), master=master)
        logger.info("Corporate actions: %s", table.summary())
    else:
        # Without it a split reads as a ~50% crash, which is worse than no chart.
        raise SystemExit(
            f"No corporate actions at {actions_path}. Publishing unadjusted "
            "prices would draw every split as a crash; run "
            "tools.backfill_backtest_archive first."
        )

    started = time.monotonic()
    observations, symbols = collect_observations(store, sessions, master, table)
    logger.info(
        "Read %d sessions in %.0fs; %d securities observed",
        len(sessions), time.monotonic() - started, len(observations),
    )

    rows = build_rows(sessions, observations, symbols, min_points=args.min_points)

    if args.since:
        # A back-adjustment restates a symbol's whole history, so only symbols
        # with a *new* ratio action need republishing -- typically a handful a
        # month out of three thousand. Dividends do not rescale the price series
        # this chart draws, so they are not a reason to rebuild.
        affected = table.securities_with_actions_since(date.fromisoformat(args.since))
        wanted = {symbols[key] for key in affected if key in symbols}
        before = len(rows)
        rows = [row for row in rows if row["symbol"] in wanted]
        logger.info(
            "Targeted rebuild since %s: %d of %d symbols have a new ratio action",
            args.since, len(rows), before,
        )
        if not rows:
            logger.info("Nothing to republish")
            return 0

    if args.limit:
        rows = rows[: args.limit]

    publish(
        repository,
        sessions,
        rows,
        dry_run=args.dry_run,
        # A targeted run publishes a subset by design; the calendar is
        # unchanged, so the shrink guard would be comparing the wrong thing.
        allow_shrink=args.allow_shrink or bool(args.since),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
