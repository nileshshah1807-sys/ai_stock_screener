"""Run the P0 walk-forward test over the archived point-in-time data.

Wires the pieces together in the only order that preserves point-in-time
discipline: calendar -> security master -> corporate actions -> adjusted prices ->
per-date universe -> score -> next-session fill -> forward return -> metrics.

Every strategy in a run shares the same rebalance dates, universe, price
snapshots, execution convention and cost model, because `p0.md` §7 is explicit
that letting those differ compares the model and the execution rules together.

Usage::

    python -m tools.run_p0_backtest --start 2022-07-01 --horizons 3,6
    python -m tools.run_p0_backtest --frequency quarterly --gross
    python -m tools.run_p0_backtest --dry-run     # report the archive, score nothing

Reads only the local archive built by ``tools.backfill_backtest_archive``; makes
no network calls of its own.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import logging
from pathlib import Path
import sys
import time

logger = logging.getLogger("p0")

DEFAULT_ROOT = Path("reports_advanced/backtest")


def _parse_date(value):
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _parse_horizons(value):
    return tuple(int(part.strip()) for part in str(value).split(",") if part.strip())


def _action_span(actions):
    """First and last ex-date in the corporate-action feed, or None."""
    import pandas as pd

    if actions is None or actions.empty or "Ex_Date" not in actions:
        return None
    dates = pd.to_datetime(actions["Ex_Date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.min().date(), dates.max().date()


def load_archive(root, *, terminal_absence_sessions=None):
    """Load calendar, master, actions and the adjusted price panel."""
    from backtest.bhavcopy import BhavcopyStore
    from backtest.calendar import CalendarLedger, TradingCalendar
    from backtest.corporate_actions import ActionStore, AdjustmentTable
    from backtest.execution import PricePanel
    from backtest.features import HistoryPanel
    from backtest.security_master import SecurityMaster, build_master

    root = Path(root)
    store = BhavcopyStore(root / "bhavcopy")
    ledger = CalendarLedger(root / "calendar.csv")
    sessions = ledger.sessions()

    # The ledger is written only when build_calendar completes, so an interrupted
    # backfill leaves cached day-files the ledger does not know about. Silently
    # running on the ledger alone would backtest a fraction of the archive and
    # look entirely normal doing it, so reconcile against what is actually on
    # disk and say so.
    cached = store.cached_dates()
    missing = sorted(set(cached) - set(sessions))
    if missing:
        logger.warning(
            "Ledger lists %d sessions but %d day-files are cached; adopting %d "
            "unrecorded sessions (%s -> %s). An interrupted backfill will do this.",
            len(sessions),
            len(cached),
            len(missing),
            missing[0],
            missing[-1],
        )
        sessions = sorted(set(sessions) | set(cached))

    if not sessions:
        raise SystemExit(
            "No confirmed sessions in the archive. Run tools.backfill_backtest_archive first."
        )
    calendar = TradingCalendar(sessions)
    logger.info(
        "Calendar: %d sessions, %s -> %s", len(calendar), sessions[0], sessions[-1]
    )

    master_path = root / "security_master.csv"
    if master_path.exists():
        master = SecurityMaster.load(master_path)
    else:
        logger.info("Building security master from cached day-files")
        master = SecurityMaster(
            build_master(
                store, sessions, terminal_absence_sessions=terminal_absence_sessions
            )
        )
        master.save(master_path)
    logger.info("Security master: %s", json.dumps(master.survivorship_summary()))

    actions = ActionStore(root / "corporate_actions.csv").load()
    table = AdjustmentTable(actions, master=master)
    logger.info("Corporate actions: %s", json.dumps(table.summary()))
    action_span = _action_span(actions)
    if actions.empty:
        logger.warning(
            "No corporate actions cached. Splits will read as ~50%% losses; "
            "run the backfill's action stage before trusting any result."
        )
    elif action_span and (
        action_span[0] > sessions[0] or action_span[1] < sessions[-1]
    ):
        # A partial feed is more dangerous than an empty one: the empty case is
        # obvious, while a feed covering only part of the window silently leaves
        # every split outside it as a fabricated ~50% loss.
        logger.warning(
            "Corporate-action feed covers %s -> %s but the archive spans %s -> %s. "
            "Splits outside the feed will read as fabricated losses. Re-run "
            "tools.backfill_backtest_archive over the full window.",
            action_span[0],
            action_span[1],
            sessions[0],
            sessions[-1],
        )

    logger.info("Assembling adjusted price panel over %d sessions", len(sessions))
    started = time.monotonic()
    price_panel = PricePanel.build(store, sessions, master, table)
    history_panel = HistoryPanel(price_panel.frame)
    logger.info(
        "Panel: %d securities, %d priced observations (%.1fs)",
        len(history_panel),
        len(price_panel),
        time.monotonic() - started,
    )
    return {
        "calendar": calendar,
        "master": master,
        "actions": actions,
        "table": table,
        "price_panel": price_panel,
        "history_panel": history_panel,
        "sessions": sessions,
    }


def build_runner(archive, args):
    from backtest.costs import CostModel
    from backtest.fundamentals import FundamentalPanel
    from backtest.runner import UniverseRule, WalkForwardRunner
    from backtest.security_master import DelistingPolicy

    fundamental_panel = None
    if getattr(args, "with_fundamentals", False):
        panel_path = Path(args.root) / "fundamental_panel.csv"
        if not panel_path.exists():
            raise SystemExit(
                f"No fundamental panel at {panel_path}. Build it first. "
                "  python -m tools.build_fundamental_panel"
            )
        fundamental_panel = FundamentalPanel.load(panel_path)
        logger.info("Fundamental panel: %d securities", len(fundamental_panel))

    universe_rule = UniverseRule(
        min_median_turnover_inr=args.min_turnover,
        min_trading_frequency=args.min_trading_frequency,
        min_history_sessions=args.min_history,
    )
    policy = DelistingPolicy(args.delisting_strategy, args.recovery_rate)

    # The Model 5.0 regime overlay is a real gate, so the gated strategy needs a
    # point-in-time regime. Built from the cached index history before the run
    # rather than from the comparison stage, which happens after it.
    provider = None
    if not getattr(args, "no_comparison", False):
        from backtest.benchmarks import IndexStore, regime_provider

        index_frame = IndexStore(Path(args.root) / "indices.csv").load()
        if not index_frame.empty:
            provider = regime_provider(index_frame)
        else:
            logger.warning(
                "No cached index history; the gated strategy runs without a "
                "market-regime overlay"
            )

    cost_model = None if args.gross else CostModel(
        half_spread_rate=args.half_spread,
        impact_coefficient=args.impact_coefficient,
        max_participation_rate=args.max_participation,
    )
    runner = WalkForwardRunner(
        archive["calendar"],
        archive["history_panel"],
        archive["price_panel"],
        master=archive["master"],
        adjustment_table=archive["table"],
        delisting_policy=policy,
        universe_rule=universe_rule,
        cost_model=cost_model,
        value_per_position=args.position_size,
        horizons=_parse_horizons(args.horizons),
        fundamental_panel=fundamental_panel,
        max_statement_age_days=getattr(args, "max_statement_age_days", None),
        require_fundamentals=(
            fundamental_panel is not None
            and not getattr(args, "allow_missing_fundamentals", False)
        ),
        regime_provider=provider,
    )
    return runner, universe_rule, policy, cost_model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--start", default=None, help="defaults to archive start")
    parser.add_argument("--end", default=None, help="defaults to archive end")
    parser.add_argument("--frequency", default="monthly", choices=["monthly", "quarterly"])
    parser.add_argument("--horizons", default="1,3,6,12")
    parser.add_argument("--portfolio-sizes", default="10,20,50")
    parser.add_argument("--min-turnover", type=float, default=2_000_000.0)
    parser.add_argument("--min-trading-frequency", type=float, default=0.80)
    parser.add_argument("--min-history", type=int, default=200)
    parser.add_argument("--position-size", type=float, default=100_000.0)
    parser.add_argument("--half-spread", type=float, default=0.0010)
    parser.add_argument("--impact-coefficient", type=float, default=0.10)
    parser.add_argument("--max-participation", type=float, default=0.10)
    parser.add_argument("--delisting-strategy", default="haircut",
                        choices=["haircut", "last_close", "zero"])
    parser.add_argument("--recovery-rate", type=float, default=0.5)
    parser.add_argument("--gross", action="store_true", help="skip the cost model")
    parser.add_argument("--dry-run", action="store_true",
                        help="load and report the archive without scoring")
    # ``--out`` is the original spelling and still works. The default is stamped
    # with the resolved window because a fixed name silently overwrote the
    # previous run: comparing two windows means having both files.
    parser.add_argument("--json-out", "--out", dest="json_out", default=None,
                        help="report path (JSON); defaults to a window-stamped "
                             "name under --root")
    parser.add_argument("--fills-out", default=None, help="optional fill-level CSV")
    # The PDF goes to a tracked path by default. reports_advanced/ is gitignored,
    # so a report written there could not be committed or shared.
    parser.add_argument(
        "--pdf-out",
        default="docs/Review/p0_backtest_report.pdf",
        help="PDF report path (tracked in git so it can be shared)",
    )
    parser.add_argument("--no-pdf", action="store_true", help="skip the PDF report")
    parser.add_argument(
        "--comparison-pdf-out",
        default="docs/Review/p0_index_comparison.pdf",
        help="CAGR-vs-index comparison PDF (tracked in git so it can be shared)",
    )
    parser.add_argument(
        "--no-comparison",
        action="store_true",
        help="skip the index comparison (also skips fetching index history)",
    )
    parser.add_argument(
        "--comparison-size", type=int, default=20,
        help="portfolio size used for the CAGR comparison",
    )
    parser.add_argument(
        "--with-fundamentals",
        action="store_true",
        help="run the full Model 5.0 matrix using the point-in-time statement panel",
    )
    parser.add_argument(
        "--max-statement-age-days",
        type=int,
        default=550,
        help="drop evidence older than this; 550 allows one late annual filing",
    )
    parser.add_argument(
        "--allow-missing-fundamentals",
        action="store_true",
        help="score names with no visible statement instead of dropping them",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    archive = load_archive(args.root)
    sessions = archive["sessions"]
    start = _parse_date(args.start) if args.start else sessions[0]
    end = _parse_date(args.end) if args.end else sessions[-1]

    from backtest.runner import (
        evaluate,
        portfolio_turnover_series,
        rebalance_dates,
        write_report,
    )
    from backtest.strategies import FUNDAMENTAL_STRATEGIES, PRICE_ONLY_STRATEGIES

    dates = rebalance_dates(archive["calendar"], start, end, frequency=args.frequency)
    horizons = _parse_horizons(args.horizons)
    logger.info(
        "%d %s rebalance dates from %s to %s; horizons %s",
        len(dates),
        args.frequency,
        start,
        end,
        horizons,
    )

    if args.dry_run:
        logger.info("Dry run: archive loaded, nothing scored")
        return 0

    if not dates:
        raise SystemExit("No rebalance dates in the requested window")

    runner, universe_rule, policy, cost_model = build_runner(archive, args)
    strategies = list(
        FUNDAMENTAL_STRATEGIES if args.with_fundamentals else PRICE_ONLY_STRATEGIES
    )
    logger.info(
        "Strategies: %s", ", ".join(strategy.name for strategy in strategies)
    )

    def on_progress(signal_date, index, total, diagnostics):
        logger.info(
            "  [%d/%d] %s | universe %d of %d eligible",
            index,
            total,
            signal_date,
            diagnostics.get("eligible", 0),
            diagnostics.get("input", 0),
        )

    started = time.monotonic()
    fills, diagnostics = runner.run(strategies, dates, on_progress=on_progress)
    logger.info("Scored %d fill rows in %.1fs", len(fills), time.monotonic() - started)

    if fills.empty:
        raise SystemExit("No fills produced; check the universe rules and archive span")

    sizes = _parse_horizons(args.portfolio_sizes)
    gross_results = evaluate(
        fills, horizons=horizons, portfolio_sizes=sizes, net=False
    )
    net_results = (
        None if args.gross
        else evaluate(fills, horizons=horizons, portfolio_sizes=sizes, net=True)
    )

    from backtest.execution import coverage_report

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {"start": str(start), "end": str(end)},
        "frequency": args.frequency,
        "rebalance_dates": [day.isoformat() for day in dates],
        "horizons": list(horizons),
        "universe_rule": universe_rule.describe(),
        "delisting_policy": policy.describe(),
        "cost_model": (
            None if cost_model is None
            else {
                "half_spread_rate": cost_model.half_spread_rate,
                "impact_coefficient": cost_model.impact_coefficient,
                "max_participation_rate": cost_model.max_participation_rate,
                "value_per_position": args.position_size,
            }
        ),
        "securities": archive["master"].survivorship_summary(),
        "corporate_actions": archive["table"].summary(),
        "universe_diagnostics": diagnostics.to_dict("records"),
        "fill_coverage": coverage_report(fills, horizons=horizons),
        "turnover": portfolio_turnover_series(fills, size=20),
        "gross": gross_results,
        "net": net_results,
    }

    # --- index comparison -------------------------------------------------
    # CAGR is only meaningful from chaining periods. At a monthly rebalance that
    # is the 1-month horizon: each period's exit session is the next period's
    # entry. Compounding an overlapping horizon would count the same market move
    # several times over.
    comparison = None
    if not args.no_comparison:
        chaining = {"monthly": 1, "quarterly": 3}[args.frequency]
        periods_per_year = {"monthly": 12, "quarterly": 4}[args.frequency]
        if chaining not in horizons:
            logger.warning(
                "CAGR comparison needs the %d-month horizon to chain at a %s "
                "rebalance; add it to --horizons. Skipping the comparison.",
                chaining,
                args.frequency,
            )
        else:
            from backtest.benchmarks import (
                DEFAULT_INDICES,
                IndexSeries,
                IndexStore,
                build_comparison,
            )

            index_store = IndexStore(Path(args.root) / "indices.csv")
            index_frame = index_store.load()
            if index_frame.empty:
                logger.info("Fetching index history (first run only)")
                index_frame = index_store.fetch(DEFAULT_INDICES, start, end)
            series = IndexSeries(index_frame)
            logger.info("Indices available: %s", ", ".join(series.names()))
            comparison = build_comparison(
                fills,
                series,
                archive["calendar"],
                size=args.comparison_size,
                horizon_months=chaining,
                periods_per_year=periods_per_year,
                return_column="Forward_Return_Chain_Pct",
                cost_rate_column=f"Cost_Rate_{chaining}M",
            )
            payload["comparison"] = comparison

    if args.json_out:
        out = Path(args.json_out)
    else:
        out = Path(args.root) / f"p0_backtest_{start}_{end}.json"
    write_report(out, payload)
    logger.info("Report written: %s", out)

    if args.fills_out:
        fills.to_csv(args.fills_out, index=False)
        logger.info("Fills written: %s", args.fills_out)

    if not args.no_pdf:
        from backtest.report_pdf import write_pdf

        pdf_path = write_pdf(payload, args.pdf_out)
        if pdf_path:
            logger.info("PDF report written: %s", pdf_path)

    if comparison and not args.no_pdf:
        from backtest.comparison_pdf import write_comparison_pdf

        comparison_path = write_comparison_pdf(
            payload, args.comparison_pdf_out, comparison=comparison
        )
        if comparison_path:
            logger.info("Comparison PDF written: %s", comparison_path)

    _print_summary(payload, horizons)
    if comparison:
        _print_comparison(comparison)
    if not args.no_pdf:
        print(f"\nPDF report: {args.pdf_out}")
        print(f"JSON report: {out}")
    return 0


def _print_comparison(comparison):
    """Console view of the CAGR table."""
    indices = comparison.get("indices", {})
    strategies = comparison.get("strategies", {})
    if not strategies:
        return
    index_names = sorted(indices)
    print()
    print("=" * 78)
    print(
        f"CAGR COMPARISON  (top {comparison.get('portfolio_size')}, "
        f"{comparison.get('horizon_months')}M non-overlapping, "
        f"{comparison.get('rebalances')} periods)"
    )
    print("=" * 78)
    print("index CAGR:")
    for name in index_names:
        print(f"  {name:<26}{indices[name].get('cagr_pct'):>9.2f}%")
    universe = comparison.get("eligible_universe", {})
    if universe.get("cagr_pct") is not None:
        print(f"  {'eligible universe (EW)':<26}{universe['cagr_pct']:>9.2f}%")
    print()
    header = f"{'strategy':<24}{'gross':>9}{'net':>9}"
    for name in index_names:
        header += f"{'vs ' + name.replace('NIFTY ', 'N'):>16}"
    print(header)
    for name in sorted(strategies):
        entry = strategies[name]
        gross = entry.get("gross_cagr_pct")
        net = entry.get("net_cagr_pct")
        row = (
            f"{name:<24}"
            f"{'-' if gross is None else format(gross, '.2f'):>9}"
            f"{'-' if net is None else format(net, '.2f'):>9}"
        )
        for index_name in index_names:
            diff = entry.get("versus", {}).get(index_name, {}).get("cagr_difference_pct")
            row += f"{'-' if diff is None else format(diff, '+.2f'):>16}"
        print(row)


def _print_summary(payload, horizons):
    """Console summary. The JSON report is the artefact; this is for reading."""
    print()
    print("=" * 78)
    print(f"P0 WALK-FORWARD  {payload['window']['start']} -> {payload['window']['end']}"
          f"  ({payload['frequency']}, {len(payload['rebalance_dates'])} rebalances)")
    print("=" * 78)
    securities = payload["securities"]
    print(
        f"universe: {securities['securities_total']} securities "
        f"({securities['delisted']} delisted, {securities['face_value_changes']} "
        f"face-value changes bridged)"
    )
    print(f"delisting policy: {payload['delisting_policy']}")
    print()

    for basis in ("gross", "net"):
        results = payload.get(basis)
        if not results:
            continue
        print(f"--- {basis.upper()} ---")
        header = f"{'strategy':<24}" + "".join(
            f"{'IC ' + str(h) + 'M':>12}" for h in horizons
        )
        print(header)
        for strategy_name in sorted(results):
            row = f"{strategy_name:<24}"
            for horizon in horizons:
                entry = results[strategy_name].get(f"{horizon}M", {})
                mean = entry.get("ic", {}).get("mean")
                row += f"{'-' if mean is None else format(mean, '.4f'):>12}"
            print(row)
        print()
        print(f"{'strategy':<24}{'horizon':>8}{'top20 vs univ':>16}{'monotonic':>12}{'spread':>10}")
        for strategy_name in sorted(results):
            for horizon in horizons:
                entry = results[strategy_name].get(f"{horizon}M", {})
                top = entry.get("portfolios", {}).get("top_20", {})
                versus = top.get("vs_universe_pct")
                mono = entry.get("monotonicity")
                spread = entry.get("bucket_spread")
                print(
                    f"{strategy_name:<24}{str(horizon) + 'M':>8}"
                    f"{'-' if versus is None else format(versus, '+.3f'):>16}"
                    f"{'-' if mono is None else format(mono, '.3f'):>12}"
                    f"{'-' if spread is None else format(spread, '+.3f'):>10}"
                )
        print()

    print("turnover (top-20, one-way per rebalance):")
    for strategy_name, entry in sorted(payload["turnover"].items()):
        value = entry.get("mean_one_way_turnover")
        print(f"  {strategy_name:<24}{'-' if value is None else format(value, '.3f')}")
    print()
    print("fill coverage:")
    for horizon, entry in payload["fill_coverage"].items():
        print(
            f"  {horizon:<5} {entry['coverage']:.1%} of {entry['total']} "
            f"({entry['skipped']})"
        )


if __name__ == "__main__":
    sys.exit(main())
