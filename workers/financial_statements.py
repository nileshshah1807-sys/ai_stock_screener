"""Collect reported financial statements and publish them for the stock page.

Display evidence only. The scoring path derives its own statement factors in
``screener/statements.py`` and never reads what this worker writes, so running
it -- or not -- cannot move a score, a rating, or the run manifest.

Stored, not fetched per page view. A live vendor fetch costs 1-3 s per stock
and is rate limited, while a company's statements change once a quarter. So a
row is refreshed only when it is due:

* it has never been fetched, or
* it is older than ``--max-age-days``, or
* its latest reported quarter ended more than ``RESULTS_DUE_DAYS`` ago, which
  means the next quarter's results are out or imminent -- checked at most every
  ``RESULTS_RECHECK_DAYS`` so a company that reports late is not re-asked daily.

In steady state that is a few dozen symbols a day, not the whole universe.

The payload contract (``statements`` column)::

    {
      "v": 1,
      "annual":    {"income": S, "balance": S, "cashflow": S},
      "quarterly": {"income": S}
    }
    S = {"periods": ["2023-03-31", ...ascending], "rows": {"revenue": [...], ...}}

Every row array is aligned to its statement's ``periods``. A value the vendor
did not report is ``null`` -- never zero -- and a derived line (expenses,
reserves, other liabilities, other assets) is computed only when every input it
needs was reported. Quarterly balance sheets and cash flows are omitted: Yahoo
publishes them for too few NSE issuers to be worth a tab.

Yahoo reports one basis per issuer (consolidated where the company files one),
so there is no standalone/consolidated split here; that arrives with the NSE
filings source.
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from screener.markets import resolve as resolve_market
from screener.markets import ticker_for
from screener.numeric import round_half_up, safe_float

logger = logging.getLogger(__name__)

PAYLOAD_VERSION = 1
SOURCE = "Yahoo Finance"

DEFAULT_MAX_AGE_DAYS = 30
# A quarter's results are due within 45 days of quarter end (60 for Q4 in
# India). Past 100 days the next quarter has almost certainly been reported.
RESULTS_DUE_DAYS = 100
RESULTS_RECHECK_DAYS = 7
DEFAULT_MAX_SYMBOLS = 500

# Yahoo row labels, first available wins. Several are absent for banks and
# insurers, which is expected: the page shows only rows that were reported.
INCOME_LINES: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "operating_profit": ("EBITDA", "Normalized EBITDA"),
    "other_income": ("Other Non Operating Income Expenses",),
    "net_interest_income": ("Net Interest Income",),
    "interest": ("Interest Expense", "Interest Expense Non Operating"),
    "depreciation": (
        "Reconciled Depreciation",
        "Depreciation And Amortization In Income Statement",
    ),
    "pbt": ("Pretax Income",),
    "tax": ("Tax Provision",),
    "net_profit": ("Net Income", "Net Income Common Stockholders"),
    "eps": ("Diluted EPS", "Basic EPS"),
}
BALANCE_LINES: dict[str, tuple[str, ...]] = {
    "equity_capital": ("Capital Stock", "Common Stock"),
    "shareholders_equity": ("Stockholders Equity", "Common Stock Equity"),
    "borrowings": ("Total Debt",),
    "fixed_assets": ("Net PPE",),
    "cwip": ("Construction In Progress",),
    "investments": (
        "Investments And Advances",
        "Investmentin Financial Assets",
        "Long Term Equity Investment",
    ),
    "cash": ("Cash And Cash Equivalents",),
    "total_assets": ("Total Assets",),
}
CASHFLOW_LINES: dict[str, tuple[str, ...]] = {
    "cfo": ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
    "cfi": ("Investing Cash Flow", "Cash Flow From Continuing Investing Activities"),
    "cff": ("Financing Cash Flow", "Cash Flow From Continuing Financing Activities"),
    "net_cash_flow": ("Changes In Cash",),
    "capex": ("Capital Expenditure", "Capital Expenditure Reported"),
    "fcf": ("Free Cash Flow",),
}

# A period column is kept only if its anchor line was reported. Yahoo pads the
# oldest column with a handful of stray values, which would otherwise render as
# a column of dashes with one number in it.
ANCHORS = {
    "income": ("revenue", "net_profit"),
    "balance": ("total_assets",),
    "cashflow": ("cfo",),
}

DECIMALS = {"eps": 2}


def _clean(value: Any, places: int) -> float | None:
    number = safe_float(value)
    if number is None or not math.isfinite(number):
        return None
    rounded = round_half_up(number, places)
    return int(rounded) if places == 0 else rounded


def _line(frame: pd.DataFrame, labels: Iterable[str]) -> pd.Series | None:
    for label in labels:
        if label in frame.index:
            row = frame.loc[label]
            if isinstance(row, pd.DataFrame):  # duplicated label: first wins
                row = row.iloc[0]
            if row.notna().any():
                return row
    return None


def _difference(minuend, *subtrahends):
    """``minuend - sum(subtrahends)`` only when every input was reported."""
    if minuend is None or any(value is None for value in subtrahends):
        return None
    return minuend - sum(subtrahends)


def extract_statement(
    frame: pd.DataFrame | None,
    lines: dict[str, tuple[str, ...]],
    kind: str,
) -> dict[str, Any]:
    """Normalise one vendor statement into ascending periods and aligned rows."""
    empty = {"periods": [], "rows": {}}
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return empty

    columns = sorted(
        (c for c in frame.columns if pd.notna(pd.to_datetime(c, errors="coerce"))),
        key=lambda c: pd.Timestamp(c),
    )
    raw: dict[str, list[float | None]] = {}
    for key, labels in lines.items():
        series = _line(frame, labels)
        if series is None:
            continue
        places = DECIMALS.get(key, 0)
        raw[key] = [_clean(series.get(c), places) for c in columns]

    anchors = ANCHORS[kind]
    keep = [
        i for i in range(len(columns))
        if any(raw.get(a, [None] * len(columns))[i] is not None for a in anchors)
    ]
    if not keep:
        return empty

    rows = {key: [values[i] for i in keep] for key, values in raw.items()}
    periods = [pd.Timestamp(columns[i]).date().isoformat() for i in keep]
    _derive(kind, rows, len(periods))
    # Drop lines that are null across every kept period.
    rows = {k: v for k, v in rows.items() if any(x is not None for x in v)}
    return {"periods": periods, "rows": rows}


def _derive(kind: str, rows: dict[str, list], n: int) -> None:
    def col(key):
        return rows.get(key, [None] * n)

    if kind == "income":
        revenue, op = col("revenue"), col("operating_profit")
        rows["expenses"] = [_difference(revenue[i], op[i]) for i in range(n)]
        # Yahoo files a lender's core income line and an industrial company's
        # net non-operating interest under the same "Net Interest Income"
        # label. It is only the headline line for issuers that report no
        # operating profit (banks, NBFCs); elsewhere it would read as a large,
        # meaningless income line beside revenue.
        if any(value is not None for value in op):
            rows.pop("net_interest_income", None)
    elif kind == "balance":
        capital, equity = col("equity_capital"), col("shareholders_equity")
        debt, assets = col("borrowings"), col("total_assets")
        fixed, cwip, investments = col("fixed_assets"), col("cwip"), col("investments")
        rows["reserves"] = [_difference(equity[i], capital[i]) for i in range(n)]
        rows["other_liabilities"] = [
            _difference(assets[i], equity[i], debt[i]) for i in range(n)
        ]
        rows["other_assets"] = [
            _difference(assets[i], fixed[i], cwip[i], investments[i]) for i in range(n)
        ]


def build_payload(frames: dict[str, pd.DataFrame | None]) -> dict[str, Any]:
    """Assemble the stored payload from the four vendor frames."""
    statements = {
        "v": PAYLOAD_VERSION,
        "annual": {
            "income": extract_statement(frames.get("income_stmt"), INCOME_LINES, "income"),
            "balance": extract_statement(frames.get("balance_sheet"), BALANCE_LINES, "balance"),
            "cashflow": extract_statement(frames.get("cashflow"), CASHFLOW_LINES, "cashflow"),
        },
        "quarterly": {
            "income": extract_statement(
                frames.get("quarterly_income_stmt"), INCOME_LINES, "income"
            ),
        },
    }
    annual_periods = [
        p for s in statements["annual"].values() for p in s["periods"]
    ]
    quarter_periods = statements["quarterly"]["income"]["periods"]
    return {
        "statements": statements,
        "has_data": bool(annual_periods or quarter_periods),
        "latest_annual": max(annual_periods) if annual_periods else None,
        "latest_quarter": quarter_periods[-1] if quarter_periods else None,
    }


FRAME_ATTRIBUTES = ("income_stmt", "quarterly_income_stmt", "balance_sheet", "cashflow")


def fetch_frames(ticker) -> dict[str, pd.DataFrame | None]:
    """Read the four statements, tolerating any one of them failing."""
    frames: dict[str, pd.DataFrame | None] = {}
    for name in FRAME_ATTRIBUTES:
        try:
            frames[name] = getattr(ticker, name)
        except Exception as exc:  # vendor raises on missing/blocked data
            logger.debug("%s unavailable: %s", name, exc)
            frames[name] = None
    return frames


def select_due(
    symbols: Iterable[str],
    state: dict[str, dict[str, Any]],
    today: date,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    limit: int = DEFAULT_MAX_SYMBOLS,
) -> list[str]:
    """Symbols to refresh this run, never-fetched first, then oldest first."""
    never, due = [], []
    for symbol in dict.fromkeys(str(s).strip().upper() for s in symbols if s):
        row = state.get(symbol)
        if row is None:
            never.append(symbol)
            continue
        fetched = _as_date(row.get("fetched_at"))
        if fetched is None:
            never.append(symbol)
            continue
        age = (today - fetched).days
        quarter = _as_date(row.get("latest_quarter"))
        results_due = (
            quarter is not None
            and (today - quarter).days > RESULTS_DUE_DAYS
            and age >= RESULTS_RECHECK_DAYS
        )
        if age >= max_age_days or results_due:
            due.append((fetched, symbol))
    due.sort()
    ordered = never + [symbol for _, symbol in due]
    return ordered[:limit] if limit > 0 else ordered


def _as_date(value) -> date | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def run(
    repo,
    *,
    ticker_factory,
    max_symbols: int = DEFAULT_MAX_SYMBOLS,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    pause_seconds: float = 0.25,
    symbols: list[str] | None = None,
    dry_run: bool = False,
    today: date | None = None,
    flush_every: int = 50,
) -> dict[str, int]:
    profile = resolve_market(repo.market)
    today = today or datetime.now(UTC).date()
    wanted = (
        [s.strip().upper() for s in symbols] if symbols else repo.latest_snapshot_symbols()
    )
    state = repo.financial_statement_state()
    todo = wanted if symbols else select_due(
        wanted, state, today, max_age_days=max_age_days, limit=max_symbols
    )
    logger.info(
        "%s financial statements: %d in universe, %d stored, %d due this run",
        profile.code, len(wanted), len(state), len(todo),
    )

    pending: list[dict[str, Any]] = []
    counts = {"fetched": 0, "with_data": 0, "empty": 0, "written": 0}

    def flush():
        if pending and not dry_run:
            counts["written"] += repo.upsert_financial_statements(pending)
        pending.clear()

    for position, symbol in enumerate(todo, start=1):
        frames = fetch_frames(ticker_factory(ticker_for(symbol, profile)))
        payload = build_payload(frames)
        counts["fetched"] += 1
        counts["with_data" if payload["has_data"] else "empty"] += 1
        pending.append({
            "symbol": symbol,
            **payload,
            "currency": profile.currency,
            "source": SOURCE,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        })
        if len(pending) >= flush_every:
            flush()
            logger.info("  %d/%d processed", position, len(todo))
        if pause_seconds:
            time.sleep(pause_seconds)
    flush()
    logger.info(
        "%s financial statements done: %s%s",
        profile.code, counts, " (dry run, nothing written)" if dry_run else "",
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default=None, help="NSE or US (default: $MARKET)")
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS)
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--pause", type=float, default=0.25, help="seconds between symbols")
    parser.add_argument("--symbols", nargs="*", help="refresh exactly these, ignoring staleness")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import yfinance as yf

    from storage.dashboard_repository import DashboardRepository

    repo = DashboardRepository.from_environment(args.market)
    run(
        repo,
        ticker_factory=yf.Ticker,
        max_symbols=args.max_symbols,
        max_age_days=args.max_age_days,
        pause_seconds=args.pause,
        symbols=args.symbols,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

