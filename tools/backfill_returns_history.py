"""Backfill the Returns page's history before the live ranking record.

The dashboard has published rankings only since 2026-08-11 (NSE). This tool
reaches further back with the point-in-time backtest, and writes two tables
(`storage/returns_backfill_schema.sql`):

* ``simulated_rankings`` -- the Model 5 top N on the last session of every week
  from November 2018 until the day before the first published ranking, keyed by
  each security's *current* ticker so it joins to ``price_series`` across
  renames. In-sample: the 5.1 weights were fitted on this period.
* ``universe_index`` -- the equal-weight one-session return of every ranked
  stock, from the backtest's price panel before the live record and from
  published prices after it. The daily publisher appends to it from then on.

Two stages, because scoring ~400 weekly cross-sections takes about an hour and
publishing should not have to repeat it::

    python -m tools.backfill_returns_history build --out reports_advanced/returns_backfill
    python -m tools.backfill_returns_history publish --from reports_advanced/returns_backfill --dry-run
    python -m tools.backfill_returns_history publish --from reports_advanced/returns_backfill
    python -m tools.backfill_returns_history annotate-live --dry-run

``build`` needs the local backtest archive (``reports_advanced/backtest``).
``publish`` reads the live record from Supabase to extend the index past the
archive, so it needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, read from the
environment or ``.env``. NSE only for now: the US has no point-in-time archive.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from screener.numeric import round_half_up  # noqa: E402
from tools.publish_price_series import load_env_file  # noqa: E402

logger = logging.getLogger("backfill_returns_history")

DEFAULT_ROOT = Path("reports_advanced/backtest")
DEFAULT_START = dt.date(2018, 11, 1)
TOP_N = 50
MODEL_VERSION = "5.1.0-backtest"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def weekly_signal_dates(sessions, start, end):
    """The last session of each ISO week in ``[start, end]``."""
    last = {}
    for day in sessions:
        if start <= day <= end:
            last[day.isocalendar()[:2]] = day
    return [last[week] for week in sorted(last)]


def next_session(sessions, day):
    """The first session strictly after ``day``, or None."""
    for session in sessions:
        if session > day:
            return session
    return None


#: A week is rated only when at least this share of its ranked names has a
#: sufficient quality block. The archive's filings carry too little balance
#: sheet before FY2023 to clear it, and without it every name fails the BUY
#: gate on coverage -- an artefact of the archive, not a rating production
#: would have published -- so those weeks carry no rating at all.
MIN_RATED_COVERAGE = 0.5

#: A Stage 2 advance at most this many calendar days old counts as fresh --
#: the same `Advance_Age_Days` production publishes, so both eras agree.
FRESH_STAGE2_DAYS = 30

#: Picks the Returns page offers, each a predicate on one ranked row. Every
#: filter's own top N is stored with its rank inside that filter, so a
#: filtered top 10 is as cheap to read as the plain one.
PICKS = {
    "rank_buy": lambda row: row["rating"] in ("BUY", "STRONG BUY"),
    "rank_strong_buy": lambda row: row["rating"] == "STRONG BUY",
    "rank_stage2": lambda row: row["stage"] == "Stage 2",
    "rank_fresh_stage2": lambda row: row["stage"] == "Stage 2"
    and row["advance_age_days"] is not None
    and row["advance_age_days"] <= FRESH_STAGE2_DAYS,
}


def gated_rating(row, regime, config=None):
    """The rating production would publish, from the backtest's gate mirror.

    `backtest.gates` omits a few BUY-side gates the archive cannot support
    (coverage floors, data-integrity and liquidity checks), so this is the
    same or more generous than production -- never stricter.
    """
    from backtest.gates import CEILING_BUY_FAILED, CEILING_CLEAR, CEILING_STRONG_FAILED, gate_failures
    from screener.recommendation import rating_from_score

    buy, strong = gate_failures(row, config, regime=regime)
    ceiling = CEILING_BUY_FAILED if buy else CEILING_STRONG_FAILED if strong else CEILING_CLEAR
    return rating_from_score(min(float(row["Research_Score"]), ceiling))


def _int_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else int(round(number))


def top_rankings(fills, current_symbol, top_n=TOP_N, rate=None):
    """Rows for ``simulated_rankings``: each week's top N, overall and per pick.

    Walks each week's ranking once, best first, giving every row its overall
    ``investment_rank`` and, for each pick in ``PICKS`` it satisfies, its rank
    inside that pick. A row is kept when it is inside the top N overall or of
    any pick, so every filtered top N can be read back exactly.

    ``current_symbol`` maps Security_ID to today's ticker; a security it cannot
    map is skipped rather than published under a stale ticker that no
    ``price_series`` row would match. ``rate(row, signal_date)`` gives the
    rating; without it, or in a week below ``MIN_RATED_COVERAGE``, no rating
    is recorded and the rating picks stay empty that week.
    """
    rows = []
    scored = fills[fills["Research_Score"].notna()]
    for signal_date, group in scored.groupby("Signal_Date"):
        day = str(signal_date)[:10]
        coverage = group.get("Quality_Coverage_Sufficient")
        rated = rate is not None and (
            coverage is None or coverage.fillna(False).astype(bool).mean() >= MIN_RATED_COVERAGE
        )
        ordered = group.sort_values(["Research_Score", "Security_ID"], ascending=[False, True])
        counts = dict.fromkeys(PICKS, 0)
        rank = 0
        for _, row in ordered.iterrows():
            symbol = current_symbol.get(str(row["Security_ID"]))
            if not symbol:
                continue
            rank += 1
            stage = row.get("Stage")
            record = {
                "observed_on": day,
                "symbol": symbol,
                "investment_rank": rank,
                "research_score": round_half_up(float(row["Research_Score"]), 2),
                "stage": stage if isinstance(stage, str) and stage else None,
                "advance_age_days": _int_or_none(row.get("Advance_Age_Days")),
                "rating": rate(row, day) if rated else None,
                "model_version": MODEL_VERSION,
            }
            keep = rank <= top_n
            for column, pick in PICKS.items():
                record[column] = None
                if counts[column] < top_n and pick(record):
                    counts[column] += 1
                    record[column] = counts[column]
                    keep = True
            if keep:
                rows.append(record)
            if rank >= top_n and all(count >= top_n for count in counts.values()):
                break
    return rows


#: Stages a holding may stay in under a stage pick: the advance, including a
#: pullback under MA50. Leaving it -- a break into Stage 3 or 4 -- is the exit
#: P5 found improved risk-adjusted return.
ADVANCING = ("Stage 2", "S2 Candidate")
BUY_PLUS = ("BUY", "STRONG BUY")


def weekly_states(fills, current_symbol, rate=None):
    """Per week, the ranked names a held stock may stay in the basket as.

    ``advancing`` is every ranked name in Stage 2 or S2 Candidate; ``buy_plus``
    every name rated BUY or better, or None in a week too thin to rate. The
    Returns page reads these for the names it holds at each rebalance, so a
    stock bought as "fresh Stage 2" is kept while its advance runs rather than
    sold the week it stops being fresh.
    """
    states = []
    scored = fills[fills["Research_Score"].notna()]
    for signal_date, group in scored.groupby("Signal_Date"):
        day = str(signal_date)[:10]
        coverage = group.get("Quality_Coverage_Sufficient")
        rated = rate is not None and (
            coverage is None or coverage.fillna(False).astype(bool).mean() >= MIN_RATED_COVERAGE
        )
        advancing, buy_plus = [], []
        for _, row in group.iterrows():
            symbol = current_symbol.get(str(row["Security_ID"]))
            if not symbol:
                continue
            if row.get("Stage") in ADVANCING:
                advancing.append(symbol)
            if rated and rate(row, day) in BUY_PLUS:
                buy_plus.append(symbol)
        states.append(
            {
                "observed_on": day,
                "advancing": sorted(set(advancing)),
                "buy_plus": sorted(set(buy_plus)) if rated else None,
            }
        )
    return states


def equal_weight_index(closes_by_day, memberships, sessions):
    """Daily equal-weight returns of a changing membership.

    ``closes_by_day`` maps each session to ``{key: close}``. ``memberships`` is
    an ascending list of ``(effective_after, keys)``: a membership bought at the
    close of ``effective_after`` earns from the next session on, until the next
    membership takes over. A member that did not trade on a day is left out of
    that day's mean and credited, when it next trades, with the whole move since
    its last close -- so no return is lost and none is invented.

    Returns ``[(session, return_pct, members_priced)]`` for sessions after the
    first membership takes effect.
    """
    rows = []
    last_close = {}
    active = -1
    for day in sessions:
        while active + 1 < len(memberships) and memberships[active + 1][0] < day:
            active += 1
        today = closes_by_day.get(day, {})
        if active >= 0:
            returns = [
                today[key] / last_close[key] - 1.0
                for key in memberships[active][1]
                if key in today and key in last_close and last_close[key] > 0
            ]
            if returns:
                rows.append((day, sum(returns) / len(returns) * 100.0, len(returns)))
        last_close.update(today)
    return rows


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build(args):
    from backtest.strategies import Model5
    from tools.run_p0_backtest import build_runner, load_archive

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    archive = load_archive(args.root)
    sessions = list(archive["calendar"].sessions)
    end = dt.date.fromisoformat(args.end)
    dates = weekly_signal_dates(sessions, DEFAULT_START, end)
    logger.info("%d weekly signal dates, %s -> %s", len(dates), dates[0], dates[-1])

    fills_path = out / "fills.pkl"
    if args.reuse_fills and fills_path.exists():
        fills = pd.read_pickle(fills_path)
        logger.info("Reusing %d scored rows from %s", len(fills), fills_path)
    else:
        # The production-like universe: no turnover floor, as the live ranking
        # has none, with the backtest's own trading-frequency and history rules.
        runner_args = SimpleNamespace(
            root=args.root, with_fundamentals=True,
            min_turnover=0.0, min_trading_frequency=0.80, min_history=200,
            delisting_strategy="haircut", recovery_rate=0.5, no_comparison=False,
            gross=False, half_spread=0.0010, impact_coefficient=0.10,
            max_participation=0.10, position_size=100_000.0, horizons="1",
            max_statement_age_days=None, allow_missing_fundamentals=False,
        )
        runner, *_ = build_runner(archive, runner_args)
        fills, _ = runner.run([Model5()], dates)
        fills.to_pickle(fills_path)
        logger.info("Scored %d rows", len(fills))

    master = pd.read_csv(Path(args.root) / "security_master.csv", dtype=str)
    current_symbol = dict(zip(master["Security_ID"], master["Current_Symbol"]))

    # The regime overlay is a real gate, so each week is rated in the regime
    # it was actually in, read point-in-time from the archive's index history.
    from backtest.benchmarks import IndexStore, regime_provider
    from backtest.gates import GateConfig

    regime_for = regime_provider(IndexStore(Path(args.root) / "indices.csv").load())
    gate_config = GateConfig.from_runtime()
    rankings = top_rankings(
        fills,
        current_symbol,
        args.top,
        rate=lambda row, day: gated_rating(row, regime_for(day), gate_config),
    )
    pd.DataFrame(rankings).to_csv(out / "simulated_rankings.csv", index=False)
    logger.info("simulated_rankings: %d rows", len(rankings))

    states = weekly_states(
        fills,
        current_symbol,
        rate=lambda row, day: gated_rating(row, regime_for(day), gate_config),
    )
    (out / "simulated_states.json").write_text(json.dumps(states))
    logger.info("simulated_states: %d weeks", len(states))

    # Every scored security is a member of that week's universe.
    scored = fills[fills["Research_Score"].notna()]
    memberships = []
    for signal_date, group in scored.groupby("Signal_Date"):
        entry = next_session(sessions, dt.date.fromisoformat(str(signal_date)[:10]))
        if entry is not None:
            memberships.append((entry, set(group["Security_ID"].astype(str))))
    memberships.sort(key=lambda item: item[0])

    panel = archive["price_panel"].frame
    days = pd.to_datetime(panel["Trade_Date"]).dt.date
    closes = pd.to_numeric(panel.get("Adj_Close", panel.get("Close")), errors="coerce")
    closes_by_day = {}
    for key, day, close in zip(panel["Security_ID"].astype(str), days, closes):
        if pd.notna(close) and close > 0:
            closes_by_day.setdefault(day, {})[key] = float(close)

    index = equal_weight_index(closes_by_day, memberships, sessions)
    pd.DataFrame(index, columns=["observed_on", "ew_return_pct", "members"]).assign(
        source="archive"
    ).to_csv(out / "universe_index_archive.csv", index=False)
    logger.info("universe_index (archive): %d sessions", len(index))
    (out / "build.json").write_text(
        json.dumps(
            {
                "signal_dates": [len(dates), dates[0].isoformat(), dates[-1].isoformat()],
                "rankings": len(rankings),
                "index_sessions": len(index),
                "top_n": args.top,
                "model_version": MODEL_VERSION,
            },
            indent=2,
        )
    )


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


def _live_index(repository, first_live_entry):
    """Equal-weight index over the published record, from adjusted closes.

    Membership is each published ranking's ranked universe; prices are the
    split-adjusted ``price_series`` base with ``screener_history``'s raw closes
    after it, the same composition the dashboard uses.
    """
    from workers.price_series import decode_calendar, decode_series

    history = repository._paged(
        "screener_history",
        {"select": "observed_on,symbol,investment_rank,current_price", "order": "observed_on,symbol"},
    )
    frame = pd.DataFrame(history)
    frame = frame[frame["investment_rank"].notna()]
    frame["observed_on"] = pd.to_datetime(frame["observed_on"]).dt.date
    run_days = sorted(frame["observed_on"].unique())

    calendar = repository._request(
        "GET", "price_calendar", params=repository._scoped({"select": "sessions"})
    )
    calendar_days = decode_calendar(calendar[0]["sessions"])
    sessions = sorted(set(calendar_days) | set(run_days))

    # About 12 KB a row, so a small page keeps each response a manageable size.
    series = repository._paged(
        "price_series",
        {"select": "symbol,session_deltas,closes,volumes,last_session", "order": "symbol"},
        page=100,
    )
    closes_by_day = {}
    base_last = {}
    for row in series:
        for point in decode_series(row, calendar_days):
            if point["date"] >= first_live_entry.isoformat():
                day = dt.date.fromisoformat(point["date"])
                closes_by_day.setdefault(day, {})[row["symbol"]] = point["close"]
        base_last[row["symbol"]] = row["last_session"]
    for record in frame.itertuples():
        price = float(record.current_price) if record.current_price else 0.0
        if price > 0 and record.observed_on.isoformat() > base_last.get(record.symbol, ""):
            closes_by_day.setdefault(record.observed_on, {})[record.symbol] = price

    memberships = []
    for day in run_days:
        entry = next_session(sessions, day)
        if entry is not None:
            members = set(frame.loc[frame["observed_on"] == day, "symbol"])
            memberships.append((entry, members))
    window = [day for day in sessions if day >= first_live_entry]
    return equal_weight_index(closes_by_day, memberships, window)


def _annotate_market(repository, market):
    """Stage and advance age for every published ranked row that lacks them.

    Runs published before the publisher recorded `advance_age_days` get it
    reconstructed here, with `screener.stage.stage_features` over the stored
    split-adjusted closes -- the archive prices the backtest era also uses.
    Production computes stage from its own vendor bars, so the two disagree for
    about one stock in five near a moving-average boundary; a published stage
    is therefore never overwritten, only a missing one filled.
    """
    from screener.stage import stage_features
    from workers.price_series import decode_calendar, decode_series

    rows = repository._paged(
        "screener_history",
        {
            "select": "observed_on,symbol,stage,current_price",
            "investment_rank": "not.is.null",
            "advance_age_days": "is.null",
            "order": "symbol,observed_on",
        },
    )
    if not rows:
        return [], []
    frame = pd.DataFrame(rows)
    symbols = sorted(frame["symbol"].unique())
    calendar = repository._request(
        "GET", "price_calendar", params=repository._scoped({"select": "sessions"})
    )
    sessions = decode_calendar(calendar[0]["sessions"]) if calendar else []
    base = {}
    for index in range(0, len(symbols), 100):
        part = symbols[index:index + 100]
        for row in repository._paged(
            "price_series",
            {
                "select": "symbol,session_deltas,closes,volumes,last_session",
                "symbol": "in.(" + ",".join(f'"{symbol}"' for symbol in part) + ")",
            },
            page=100,
        ):
            base[row["symbol"]] = row

    fill_stage, age_only = [], []
    for symbol, group in frame.groupby("symbol"):
        points = []
        last = ""
        if symbol in base:
            points = [(point["date"], point["close"]) for point in decode_series(base[symbol], sessions)]
            last = base[symbol]["last_session"]
        # Raw closes after the base's last rebuild, as the dashboard does.
        for record in group.itertuples():
            if record.observed_on > last and record.current_price:
                points.append((record.observed_on, float(record.current_price)))
        if not points:
            continue
        closes = pd.Series(
            [close for _, close in points], index=pd.to_datetime([day for day, _ in points])
        ).sort_index()
        closes = closes[~closes.index.duplicated(keep="first")]
        for record in group.itertuples():
            features = stage_features(closes[closes.index <= pd.Timestamp(record.observed_on)])
            age = _int_or_none(features.get("Advance_Age_Days"))
            base_row = {"observed_on": record.observed_on, "symbol": symbol, "advance_age_days": age}
            # A missing stage reads back from the frame as NaN, which is truthy.
            if isinstance(record.stage, str) and record.stage:
                age_only.append(base_row)
            else:
                fill_stage.append({**base_row, "stage": features.get("Stage")})
    logger.info(
        "%s: %d rows lacked annotations (%d need a stage too)",
        market, len(age_only) + len(fill_stage), len(fill_stage),
    )
    return fill_stage, age_only


def annotate_live(args):
    from storage.dashboard_repository import DashboardRepository

    load_env_file()
    for market in args.markets:
        repository = DashboardRepository.from_environment(market)
        fill_stage, age_only = _annotate_market(repository, market)
        if args.dry_run:
            continue
        # PostgREST wants every object in one request to carry the same keys,
        # and an upsert touches only the columns sent -- so the two shapes go
        # separately, and a published stage is never sent at all.
        written = repository.upsert_history_rows(fill_stage) + repository.upsert_history_rows(age_only)
        logger.info("%s: annotated %d rows", market, written)


def publish(args):
    from storage.dashboard_repository import DashboardRepository

    load_env_file()
    source = Path(args.source)
    rankings = pd.read_csv(source / "simulated_rankings.csv").to_dict("records")
    archive_index = pd.read_csv(source / "universe_index_archive.csv")

    repository = DashboardRepository.from_environment("NSE")
    first_live = repository._request(
        "GET",
        "screener_history",
        params=repository._scoped(
            {"select": "observed_on", "investment_rank": "eq.1", "order": "observed_on", "limit": "1"}
        ),
    )
    if not first_live:
        raise SystemExit("No published NSE ranking yet; nothing to join the backfill to.")
    first_live_day = dt.date.fromisoformat(first_live[0]["observed_on"])
    rankings = [row for row in rankings if row["observed_on"] < first_live_day.isoformat()]

    # The archive index runs until the live membership takes over: sessions up
    # to and including the first live ranking's entry session.
    calendar = repository._request(
        "GET", "price_calendar", params=repository._scoped({"select": "sessions"})
    )
    sessions = sorted(dt.date.fromisoformat(day) for day in json.loads(calendar[0]["sessions"]))
    first_live_entry = next_session(sessions, first_live_day)
    archive_rows = [
        row
        for row in archive_index.to_dict("records")
        if row["observed_on"] <= first_live_entry.isoformat()
    ]
    live_rows = [
        {"observed_on": day.isoformat(), "ew_return_pct": value, "members": members, "source": "history"}
        for day, value, members in _live_index(repository, first_live_entry)
        if day > first_live_entry
    ]
    index_rows = [
        {**row, "ew_return_pct": round_half_up(float(row["ew_return_pct"]), 4), "members": int(row["members"])}
        for row in archive_rows + live_rows
    ]

    logger.info(
        "simulated_rankings: %d rows (%s -> %s); universe_index: %d archive + %d live sessions",
        len(rankings),
        rankings[0]["observed_on"] if rankings else "-",
        rankings[-1]["observed_on"] if rankings else "-",
        len(archive_rows),
        len(live_rows),
    )
    if args.dry_run:
        return
    # CSV round trip: blank text reads back as NaN, and an integer column with
    # blanks as floats. Postgres wants nulls and integers.
    integer_columns = ("investment_rank", "advance_age_days", *PICKS)
    for row in rankings:
        for column in ("stage", "rating"):
            if isinstance(row.get(column), float):
                row[column] = None
        for column in integer_columns:
            row[column] = _int_or_none(row.get(column))
    states = json.loads((source / "simulated_states.json").read_text())
    states = [row for row in states if row["observed_on"] < first_live_day.isoformat()]
    written = repository.upsert_simulated_rankings(rankings)
    repository.upsert_simulated_states(states)
    indexed = repository.upsert_universe_index(index_rows)
    logger.info(
        "Published %d ranking rows, %d weekly states and %d index rows", written, len(states), indexed
    )


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="stage", required=True)
    b = sub.add_parser("build", help="score weekly cross-sections and compute both tables")
    b.add_argument("--root", default=str(DEFAULT_ROOT))
    b.add_argument("--out", required=True)
    b.add_argument("--end", default="2026-08-10", help="last signal date (the day before live)")
    b.add_argument("--top", type=int, default=TOP_N)
    b.add_argument("--reuse-fills", action="store_true", help="skip scoring if OUT/fills.pkl exists")
    p = sub.add_parser("publish", help="upload a build to Supabase")
    p.add_argument("--from", dest="source", required=True)
    p.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("annotate-live", help="fill stage/advance age on published runs lacking them")
    a.add_argument("--markets", nargs="+", default=["NSE", "US"])
    a.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    {"build": build, "publish": publish, "annotate-live": annotate_live}[args.stage](args)


if __name__ == "__main__":
    main()
