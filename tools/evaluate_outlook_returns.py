"""Measure the stored call outlooks against the returns that followed them.

The outlook score's point weights (`sentiment.outlook.outlook_items`) are a
judgment. This reads every stored outlook of a market, the stock's closes
and the equal-weight universe's daily return (``universe_index``), and asks
of each results season and horizon:

* how well the outlook score ranks the return in excess of the universe
  (Spearman), and what the top fifth earned over the bottom fifth;
* for each scored item -- guidance raised, order book rising, weak demand,
  a headwind... -- how many calls carried it, and the excess return of those
  calls against the rest, so an item whose sign flips between seasons shows.

A call is entered at the close of the first session after it was held, so
the reaction on the morning after is not counted: the screener reads an
outlook once it is stored, the evening of the call or later. Excess returns
are winsorised within each season and horizon for the averages; the rank
correlations need no such help.

Read-only, and it sends nothing to a language model: no tokens, no writes.
Two limits to keep in mind. The outlooks of older calls were extracted after
the fact (the prompt forbids outside knowledge, which is not proof). And a
season's longer horizon exists only once that many sessions have passed.

Usage::

    python -m tools.evaluate_outlook_returns                    # NSE, 21 and 63 sessions
    python -m tools.evaluate_outlook_returns --horizons 10 21 --out reports/outlook_returns.json

Needs ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY``, from the environment
or ``.env``.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import logging
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentiment.outlook import OUTLOOK_VERSION, outlook_items  # noqa: E402
from tools.publish_price_series import load_env_file  # noqa: E402

logger = logging.getLogger("evaluate_outlook_returns")

HORIZONS = (21, 63)
# Excess returns beyond these quantiles are pulled in for the averages: one
# stock that doubles should not decide whether an item helps.
WINSOR = (0.025, 0.975)
# Two calls of one company this close together are one call stored twice (a
# recording and the filed transcript before the recording's was deleted).
SAME_CALL_DAYS = 10


def item_key(reason: str) -> str:
    """The item a scored reason belongs to: "tailwind: new plant" is a tailwind."""
    head = str(reason).split(":", 1)[0].strip()
    return head if head in ("tailwind", "headwind") else str(reason).strip()


def season(call_date: dt.date) -> str:
    """The results season a call belongs to, by the calendar quarter it was held in."""
    first = {1: "Jan", 4: "Apr", 7: "Jul", 10: "Oct"}[(call_date.month - 1) // 3 * 3 + 1]
    last = {1: "Mar", 4: "Jun", 7: "Sep", 10: "Dec"}[(call_date.month - 1) // 3 * 3 + 1]
    return f"{first}-{last} {call_date.year}"


def forward_excess(
    closes: dict[dt.date, float],
    sessions: list[dt.date],
    universe: dict[dt.date, float],
    call_day: dt.date,
    horizon: int,
) -> float | None:
    """The stock's return over ``horizon`` sessions after the call, less the universe's, in percent.

    Entered at the close of the first session after ``call_day`` and left at
    the close ``horizon`` sessions later. None where the stock has no close
    on either day, or the universe misses a session in between.
    """
    start = bisect.bisect_right(sessions, call_day)
    end = start + horizon
    if end >= len(sessions):
        return None
    entry, exit_ = sessions[start], sessions[end]
    if entry not in closes or exit_ not in closes or closes[entry] <= 0:
        return None
    market = 1.0
    for day in sessions[start + 1 : end + 1]:
        if day not in universe:
            return None
        market *= 1.0 + universe[day] / 100.0
    return (closes[exit_] / closes[entry] - market) * 100.0


def spearman(first: list[float], second: list[float]) -> float | None:
    import pandas as pd

    frame = pd.DataFrame({"a": first, "b": second})
    if len(frame) < 10 or frame["a"].nunique() < 2 or frame["b"].nunique() < 2:
        return None
    return float(frame["a"].rank().corr(frame["b"].rank()))


def _winsorised(values: list[float]) -> list[float]:
    import numpy as np

    if not values:
        return []
    low, high = np.quantile(values, WINSOR)
    return [min(max(value, low), high) for value in values]


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def distinct_calls(outlooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One outlook per call: the newest of a company's readings within `SAME_CALL_DAYS`."""
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in outlooks:
        try:
            row = {**row, "day": dt.date.fromisoformat(str(row.get("call_date"))[:10])}
        except ValueError:
            continue
        by_symbol.setdefault(str(row.get("symbol")), []).append(row)
    kept: list[dict[str, Any]] = []
    for rows in by_symbol.values():
        rows.sort(key=lambda row: (row["day"], str(row.get("created_at") or "")))
        for row in rows:
            if kept and kept[-1]["symbol"] == row["symbol"] and (row["day"] - kept[-1]["day"]).days <= SAME_CALL_DAYS:
                kept[-1] = row
            else:
                kept.append(row)
    return kept


def evaluate(
    calls: list[dict[str, Any]],
    closes: dict[str, dict[dt.date, float]],
    sessions: list[dt.date],
    universe: dict[dt.date, float],
    horizons: Iterable[int] = HORIZONS,
) -> dict[str, Any]:
    """The report: by season and horizon, the score's rank agreement and each item's excess return."""
    report: dict[str, Any] = {"calls": len(calls), "seasons": {}}
    for horizon in horizons:
        measured = []
        for call in calls:
            series = closes.get(str(call.get("symbol")))
            score = call.get("outlook_score")
            if series is None or score is None:
                continue
            excess = forward_excess(series, sessions, universe, call["day"], horizon)
            if excess is None:
                continue
            try:
                reasons = [item_key(reason) for reason, _, _ in outlook_items(call.get("extraction") or {})]
            except (KeyError, TypeError, AttributeError):
                reasons = []
            measured.append({
                "season": season(call["day"]), "score": float(score), "excess": excess, "items": set(reasons),
                "verified": int(call.get("verified_fields") or 0),
                # Nearly every call names a tailwind and a headwind, so their
                # presence says nothing; how many it names can.
                "counts": {key: reasons.count(key) for key in ("tailwind", "headwind")},
            })
        for name in sorted({row["season"] for row in measured}, key=_season_order):
            rows = [row for row in measured if row["season"] == name]
            report["seasons"].setdefault(name, {})[str(horizon)] = _season_report(rows)
    return report


def _season_order(name: str) -> tuple[int, int]:
    month, year = name.split(" ")[0].split("-")[0], int(name.split(" ")[1])
    return year, ["Jan", "Apr", "Jul", "Oct"].index(month)


def _season_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    excess = _winsorised([row["excess"] for row in rows])
    for row, value in zip(rows, excess):
        row["clipped"] = value
    ranked = sorted(rows, key=lambda row: row["score"])
    fifth = max(1, len(ranked) // 5)
    scored = [row for row in rows if row["verified"] > 0]
    items: dict[str, dict[str, Any]] = {}
    for key in sorted({key for row in rows for key in row["items"]}):
        with_item = [row["clipped"] for row in rows if key in row["items"]]
        without = [row["clipped"] for row in rows if key not in row["items"]]
        items[key] = {
            "calls": len(with_item),
            "excess_with": _rounded(_mean(with_item)),
            "excess_without": _rounded(_mean(without)),
            "difference": _rounded(
                None if not with_item or not without else _mean(with_item) - _mean(without)
            ),
        }
    return {
        "calls": len(rows),
        "spearman": _rounded(spearman([row["score"] for row in rows], [row["excess"] for row in rows]), 3),
        "spearman_verified_only": _rounded(
            spearman([row["score"] for row in scored], [row["excess"] for row in scored]), 3
        ),
        "top_fifth_excess": _rounded(_mean(row["clipped"] for row in ranked[-fifth:])),
        "bottom_fifth_excess": _rounded(_mean(row["clipped"] for row in ranked[:fifth])),
        "mean_excess": _rounded(_mean(excess)),
        "count_spearman": {
            key: _rounded(spearman([row["counts"][key] for row in rows], [row["excess"] for row in rows]), 3)
            for key in ("tailwind", "headwind")
        },
        "items": items,
    }


def _rounded(value: float | None, places: int = 2) -> float | None:
    from screener.numeric import round_half_up

    return None if value is None else float(round_half_up(value, places))


def render(report: dict[str, Any]) -> list[str]:
    lines = [f"{report['calls']} distinct calls with a stored outlook"]
    for name, horizons in report["seasons"].items():
        for horizon, block in horizons.items():
            lines.append("")
            lines.append(
                f"{name}, {horizon} sessions: {block['calls']} calls; "
                f"Spearman {block['spearman']} (verified only {block['spearman_verified_only']}); "
                f"top fifth {block['top_fifth_excess']}% vs bottom fifth {block['bottom_fifth_excess']}% "
                f"(all calls {block['mean_excess']}%)"
            )
            counts = block["count_spearman"]
            lines.append(
                f"    number of tailwinds named: Spearman {counts['tailwind']}; "
                f"number of headwinds named: Spearman {counts['headwind']}"
            )
            ordered = sorted(block["items"].items(), key=lambda item: -(item[1]["calls"]))
            for key, stats in ordered:
                if stats["calls"] < 5:
                    continue
                lines.append(
                    f"    {key:48} {stats['calls']:5} calls  with {stats['excess_with']:>7}%  "
                    f"without {stats['excess_without']:>7}%  difference {stats['difference']:>7}"
                )
    return lines


def load(market: str):
    """Outlooks, closes by symbol, the session calendar and the universe's daily return."""
    from storage.dashboard_repository import DashboardRepository
    from workers.price_series import decode_calendar, decode_series

    repository = DashboardRepository.from_environment(market)
    outlooks = repository._paged(
        "transcript_outlooks",
        {
            "select": "symbol,call_date,outlook_score,verified_fields,extraction,created_at",
            "analysis_version": f"eq.{OUTLOOK_VERSION}",
            "order": "call_date,symbol",
        },
    )
    calls = distinct_calls(outlooks)
    sessions = sorted(decode_calendar(repository.read_price_calendar()["sessions"]))
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol, row in repository.read_price_series(sorted({call["symbol"] for call in calls})).items():
        closes[symbol] = {
            dt.date.fromisoformat(point["date"]): float(point["close"]) for point in decode_series(row, sessions)
        }
    universe = {
        dt.date.fromisoformat(str(row["observed_on"])[:10]): float(row["ew_return_pct"])
        for row in repository._paged("universe_index", {"select": "observed_on,ew_return_pct", "order": "observed_on"})
        if row.get("ew_return_pct") is not None
    }
    logger.info(
        "%d outlooks, %d distinct calls, %d price series, %d universe sessions (%s to %s)",
        len(outlooks), len(calls), len(closes), len(universe),
        min(universe, default=None), max(universe, default=None),
    )
    return calls, closes, sessions, universe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--horizons", type=int, nargs="+", default=list(HORIZONS))
    parser.add_argument("--out", default=None, help="also write the report here as JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env_file()

    calls, closes, sessions, universe = load(args.market)
    report = evaluate(calls, closes, sessions, universe, args.horizons)
    print("\n".join(render(report)))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
