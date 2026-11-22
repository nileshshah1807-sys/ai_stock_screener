"""NSE's industry classification for every NSE-listed stock, for the sector pages.

NSE classifies each security on four levels -- macro-economic sector (12),
sector (22, the scheme NSDL's FPI report uses), industry and basic industry --
and states them only in the stock's own quote (``secInfo.macro``, ``sector``,
``industryInfo``, ``basicIndustry``); no file lists them all. So this worker
asks the quote for each symbol of the latest snapshot, within a time budget per
run: unclassified symbols first, then each again after ``RECHECK_DAYS``, since a
company is reclassified rarely. An SME stock is quoted under its own series
(SM/ST/SZ), a mainboard stock under EQ (BE/BZ for one in the trade-for-trade
segment), so each series is tried in turn until one answers.

The result is the R2 object ``live/NSE/nse-sectors.json`` (one row per symbol,
its own store, no table), which ``tools/publish_market_breadth.py`` reads to
group the sector pages (``workers/sectors.nse_sector_rows``). A BSE-only name
(``SYMBOL.BO``) has no NSE quote and is not asked. Display evidence only:
nothing scores on it.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from screener.markets import is_bse_only

logger = logging.getLogger(__name__)

RECHECK_DAYS = 30
TIME_BUDGET_SECONDS = 150
# This many symbols asked in a row with none classified means the endpoint, not the symbols, failed.
FAILED_STREAK = 20
REQUEST_PAUSE_SECONDS = 0.4
MAINBOARD_SERIES = ("EQ", "BE", "BZ")
SME_SERIES = ("SM", "ST", "SZ")
LEVELS = {"macro": "macro", "sector": "sector", "industry": "industryInfo", "basic": "basicIndustry"}


def classification(quote: dict[str, Any]) -> dict[str, str] | None:
    """The four levels from a quote record; None when it carries no sector."""
    info = (quote or {}).get("secInfo") or {}
    out = {key: str(info.get(field) or "").strip() for key, field in LEVELS.items()}
    return out if out["sector"] else None


def classify(quote: Callable[[str, str], dict[str, Any]], symbol: str, sme: bool) -> dict[str, str] | None:
    """The symbol's classification from the first series NSE quotes it under, or None.

    A series the symbol does not trade in answers with an empty body, which the
    client raises as a decode or lookup error; anything else (a dropped
    session, a refusal) is not about this symbol and is raised.
    """
    for series in (*SME_SERIES, *MAINBOARD_SERIES) if sme else (*MAINBOARD_SERIES, *SME_SERIES):
        try:
            found = classification(quote(symbol, series))
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if found:
            return found
    return None


def due(universe: Iterable[tuple[str, bool]], held: dict[str, dict[str, Any]], today: date) -> list[tuple[str, bool]]:
    """Symbols to ask this run: never asked first, then the oldest check past RECHECK_DAYS."""
    stale = (today - timedelta(days=RECHECK_DAYS)).isoformat()
    fresh, old = [], []
    for symbol, sme in universe:
        if is_bse_only(symbol):
            continue
        checked = (held.get(symbol) or {}).get("checked")
        if not checked:
            fresh.append((symbol, sme))
        elif checked < stale:
            old.append((checked, symbol, sme))
    return fresh + [(symbol, sme) for _, symbol, sme in sorted(old)]


def run(
    repo,
    quote: Callable[[str, str], dict[str, Any]],
    *,
    today: date | None = None,
    budget_seconds: float = TIME_BUDGET_SECONDS,
    pause: float = REQUEST_PAUSE_SECONDS,
    dry_run: bool = False,
) -> dict[str, int]:
    today = today or date.today()
    counts = {"asked": 0, "classified": 0, "unclassified": 0, "held": 0}
    try:
        body = repo.nse_sectors_object()
    except Exception as exc:  # never overwrite an object that could not be read
        logger.warning("NSE sectors not refreshed: the object is unreadable (%s)", exc)
        return counts
    held = {row["symbol"]: row for row in (body or {}).get("rows") or [] if row.get("symbol")}

    _, snapshot = repo.latest_snapshot_fields(("is_sme",))
    todo = due(((row["symbol"], bool(row.get("is_sme"))) for row in snapshot), held, today)
    deadline = time.monotonic() + budget_seconds
    learnt: dict[str, dict[str, Any]] = {}
    streak = 0
    try:
        for symbol, sme in todo:
            if time.monotonic() > deadline:
                break
            found = classify(quote, symbol, sme)
            counts["asked"] += 1
            counts["classified" if found else "unclassified"] += 1
            streak = 0 if found else streak + 1
            # An unclassified symbol is stamped too, so it waits RECHECK_DAYS like the rest.
            learnt[symbol] = {"symbol": symbol, **(found or {}), "checked": today.isoformat()}
            if streak >= FAILED_STREAK:
                raise RuntimeError(f"{streak} symbols in a row unclassified")
            time.sleep(pause)
    except Exception as exc:  # the session or the endpoint failed: keep what this run did learn
        logger.warning("NSE quotes stopped after %d symbols (%s)", counts["asked"], exc)
        # The failed streak is the endpoint's doing, not the symbols': none of it is stamped.
        for symbol in list(learnt)[len(learnt) - streak:] if streak else []:
            del learnt[symbol]
    held.update(learnt)

    counts["held"] = sum(1 for row in held.values() if row.get("sector"))
    logger.info(
        "NSE sectors: asked %d (%d classified, %d not), %d of %d left, %d symbols classified in all",
        counts["asked"], counts["classified"], counts["unclassified"],
        len(todo) - counts["asked"], len(todo), counts["held"],
    )
    if learnt and not dry_run:
        repo.put_nse_sectors_object(sorted(held.values(), key=lambda row: row["symbol"]))
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--budget-seconds", type=float, default=TIME_BUDGET_SECONDS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.market != "NSE":
        logger.info("NSE sectors: nothing to do for %s", args.market)
        return 0

    from tempfile import TemporaryDirectory

    from storage.dashboard_repository import DashboardRepository
    from workers.upcoming_events import open_session

    repo = DashboardRepository.from_environment(args.market)
    with TemporaryDirectory(prefix="nse_sectors_") as folder:
        try:
            nse = open_session(folder)
        except Exception as exc:  # a refused warm-up: nothing to read this run, not a failed step
            logger.warning("Exchange session not opened (%s); nothing read this run", exc)
            return 0
        with nse:
            run(repo, nse.quote, budget_seconds=args.budget_seconds, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
