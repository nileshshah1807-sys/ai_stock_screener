"""Build and publish the stock-page price series.

    python -m tools.publish_price_series --dry-run
    python -m tools.publish_price_series
    python -m tools.publish_price_series --market US

NSE reads the same archive the point-in-time backtest reads, so the chart and
the model are drawn from one set of corporate-action-adjusted prices.

No such archive exists for the US, so that market is sourced from yfinance
instead -- see `workers/price_series_market.py`, which states the trade. The
encoding, the shrink guard and the publish path are shared, so both markets
produce the same rows and the dashboard reads them the same way.

Apply `storage/price_series_schema.sql` once before the first real run, and
`storage/multi_market_migration.sql` before the first non-NSE one.
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


def _publish_vendor_sourced(args, profile, repository):
    """Build and publish a market that has no point-in-time archive.

    Shares everything downstream of the observations with the NSE path: the
    same encoder, the same row builder, the same shrink guard and the same
    writer, so both markets land identical row shapes and the dashboard reads
    them with one decoder.
    """
    from screener.universe import fetch as fetch_universe
    from workers.price_series_market import (
        DEFAULT_START,
        collect_observations,
        identity_symbols,
        trading_calendar,
    )
    from workers.price_series_publisher import build_rows, publish

    if args.since:
        # Yahoo back-adjusts silently, so there is no action ledger to ask
        # "what changed since". Failing is better than accepting the flag and
        # quietly publishing a full rebuild the caller did not ask for.
        raise SystemExit(
            f"--since is archive-only; {profile.code} has no corporate-action "
            "ledger to target a rebuild from. Re-run without it for a full "
            "rebuild, which for this market takes a few minutes."
        )

    start = args.start or DEFAULT_START
    sessions = trading_calendar(profile, start=start, end=args.end)
    if len(sessions) < 2:
        raise SystemExit(f"Fewer than two {profile.code} sessions in {start}..{args.end}")

    universe = fetch_universe(profile, _UniverseConfig(args))
    if not universe.symbols:
        raise SystemExit(
            f"{profile.code} universe came back empty ({universe.status}); "
            "refusing to publish a chart set with no symbols"
        )
    symbols = list(universe.symbols)
    if args.limit:
        symbols = symbols[: args.limit]
    logger.info("Universe: %d symbols from %s", len(symbols), universe.source_url)

    started = time.monotonic()
    observations = collect_observations(symbols, profile, start=start, end=args.end)
    logger.info(
        "Fetched %d symbols in %.0fs", len(observations), time.monotonic() - started
    )

    rows = build_rows(
        sessions,
        observations,
        identity_symbols(observations),
        min_points=args.min_points,
    )

    publish(
        repository,
        sessions,
        rows,
        dry_run=args.dry_run,
        allow_shrink=args.allow_shrink,
    )
    return 0


class _UniverseConfig:
    """Minimal config for the universe fetch.

    ``screener.universe`` reads one setting, and building a full Config here
    would drag in the whole runtime -- including its email and cache side
    effects -- to answer a single question.
    """

    def __init__(self, args):
        self.US_UNIVERSE_SOURCE = os.getenv("US_UNIVERSE_SOURCE", "")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--market",
        default=os.getenv("MARKET", "NSE"),
        help="Market to publish: NSE (archive-sourced) or US (vendor-sourced)",
    )
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

    from screener.markets import NSE
    from screener.markets import resolve as resolve_market

    profile = resolve_market(args.market)

    # Constructed before the archive read, which takes about a minute. Missing
    # credentials should fail in the first second, not the sixty-first.
    repository = None
    if not args.dry_run:
        from storage.dashboard_repository import DashboardRepository

        try:
            repository = DashboardRepository.from_environment(profile.code)
        except ValueError as error:
            hint = [
                str(error),
                "",
                "Set them in .env or the environment, e.g.",
                "  SUPABASE_URL=https://<project>.supabase.co",
                "  SUPABASE_SERVICE_ROLE_KEY=<service role key>",
            ]
            raise SystemExit("\n".join(hint)) from error

    if profile.code != NSE:
        return _publish_vendor_sourced(args, profile, repository)

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
