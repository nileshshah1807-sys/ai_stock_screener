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

Runs are bounded by time, not only by count. A cold build (a new table, or a
new market) keeps fetching until ``--time-budget-minutes`` is spent and then
stops cleanly, so it fills as fast as the job allows without ever being cut
off by the runner's timeout; the next scheduled run continues where it
stopped, because never-fetched symbols always come first.

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
so there is no standalone/consolidated split here.

Where the market has an index of results filings (NSE), a quarter the company
has filed and Yahoo does not have yet is added from the filing itself
(`FiledQuarters`). Yahoo republishes a result days or weeks after it is filed,
and has holes of its own; through a results season the page would otherwise
show last quarter for a company that reported this one a week ago. A filed
quarter is added only on the terms that keep one table honest:

* the filing must reproduce Yahoo's revenue on a quarter both have, which
  also settles which basis Yahoo is reporting;
* a line is filled only if it reproduced Yahoo's figure on that same quarter.
  One that did not means something else at the vendor (EBITDA without
  depreciation, profit before a regulatory adjustment) and stays ``null`` for
  the filed quarter rather than sitting beside figures it is not comparable to.

The filed periods are listed under ``quarterly.income.filed_periods`` and the
row's ``source`` names both origins.
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from screener import quarterly_results
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

SOURCE_WITH_FILINGS = f"{SOURCE}; latest quarters from NSE filings"
# A company whose filing is ahead of its stored quarter is re-asked daily, not
# on every run: one whose filing cannot be reconciled with the vendor stays
# ahead until the vendor catches up.
FILED_RECHECK_DAYS = 1
# Both sources publish the filing's own figure, so agreement is exact or it is
# a different line; the margin only absorbs rounding.
FILED_MATCH_TOLERANCE = 0.01
MAX_FILED_QUARTERS = 4
FILING_INDEX_LOOKBACK_DAYS = 600

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


def _agrees(filed, vendor) -> bool:
    if filed is None or vendor is None:
        return False
    if vendor == 0:
        return filed == 0
    return abs(filed / vendor - 1.0) <= FILED_MATCH_TOLERANCE


class FiledQuarters:
    """Quarters a company has filed with the exchange that the vendor lacks."""

    def __init__(self, index: pd.DataFrame, *, fetch_document) -> None:
        # {symbol: {period: {is_consolidated: document url}}}
        self._filed: dict[str, dict[str, dict[bool, str]]] = {}
        readable = index[index["Taxonomy"].isin(quarterly_results.SUPPORTED_TAXONOMIES)]
        for row in readable.to_dict("records"):
            period = pd.Timestamp(row["Period_End"]).date().isoformat()
            self._filed.setdefault(str(row["Symbol"]), {}).setdefault(period, {})[
                bool(row["Is_Consolidated"])
            ] = row["XBRL_URL"]
        self._fetch_document = fetch_document

    def latest(self) -> dict[str, date]:
        """Each symbol's latest filed quarter, for deciding what is due."""
        return {
            symbol: date.fromisoformat(max(periods))
            for symbol, periods in self._filed.items()
        }

    def _lines(self, url: str | None) -> dict[str, float | None] | None:
        if not url:
            return None
        text = self._fetch_document(url)
        if not text:
            return None
        return {
            key: _clean(value, DECIMALS.get(key, 0))
            for key, value in quarterly_results.parse_quarter_statement(text).items()
        }

    def extend(self, symbol: str, statement: dict[str, Any]) -> dict[str, Any]:
        """``statement`` with the filed quarters it lacks, or unchanged."""
        filed = self._filed.get(symbol)
        periods = statement["periods"]
        if not filed or not periods:
            return statement
        missing = sorted(p for p in filed if p not in periods and p > periods[0])
        shared = [p for p in periods if p in filed]
        if not missing or not shared:
            return statement

        anchor = shared[-1]
        position = periods.index(anchor)
        vendor = {key: values[position] for key, values in statement["rows"].items()}
        for basis in (True, False):
            lines = self._lines(filed[anchor].get(basis))
            if lines is not None and _agrees(lines["revenue"], vendor.get("revenue")):
                agreed = [key for key in lines if _agrees(lines[key], vendor.get(key))]
                break
        else:
            logger.debug("%s: no filing reproduces the vendor's %s revenue", symbol, anchor)
            return statement

        columns: dict[str, dict[str, float | None]] = {}
        for period in missing[-MAX_FILED_QUARTERS:]:
            lines = self._lines(filed[period].get(basis))
            if lines is not None and lines["revenue"] is not None:
                columns[period] = {key: lines[key] for key in agreed}
        if not columns:
            return statement

        merged = sorted({*periods, *columns})
        rows: dict[str, list] = {}
        for key, values in statement["rows"].items():
            if key == "expenses":  # derived again below, across every column
                continue
            reported = dict(zip(periods, values, strict=True))
            rows[key] = [
                columns[p].get(key) if p in columns else reported[p] for p in merged
            ]
        _derive("income", rows, len(merged))
        rows = {k: v for k, v in rows.items() if any(x is not None for x in v)}
        return {"periods": merged, "rows": rows, "filed_periods": sorted(columns)}


def add_filed_quarters(
    payload: dict[str, Any], symbol: str, filed_quarters: FiledQuarters
) -> bool:
    """Extend ``payload``'s quarterly income in place; True if anything was added."""
    quarterly = payload["statements"]["quarterly"]
    extended = filed_quarters.extend(symbol, quarterly["income"])
    if not extended.get("filed_periods"):
        return False
    quarterly["income"] = extended
    payload["latest_quarter"] = extended["periods"][-1]
    return True


def load_filed_quarters(profile, today: date) -> FiledQuarters | None:
    """The market's filing index, or None where there is none or it is down."""
    if not profile.quarterly_results_provider:
        return None
    try:
        index = quarterly_results.fetch_index(
            today - timedelta(days=FILING_INDEX_LOOKBACK_DAYS), today
        )
    except Exception as exc:  # the vendor's statements are still worth publishing
        logger.warning(
            "Results filing index unavailable (%s); publishing the vendor's "
            "quarters only this run",
            exc,
        )
        return None
    fetcher = quarterly_results.DocumentFetcher(workers=1)
    return FiledQuarters(index, fetch_document=fetcher.fetch_one)


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
    filed_latest: dict[str, date] | None = None,
) -> list[str]:
    """Symbols to refresh this run.

    Never-fetched first, then those whose filed quarter is ahead of the stored
    one (``filed_latest``, where the market has a filing index), then the rest
    oldest first.
    """
    filed_latest = filed_latest or {}
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
        filed = filed_latest.get(symbol)
        filed_ahead = (
            quarter is not None
            and filed is not None
            and filed > quarter
            and age >= FILED_RECHECK_DAYS
        )
        if age >= max_age_days or results_due or filed_ahead:
            due.append((not filed_ahead, fetched, symbol))
    due.sort()
    ordered = never + [symbol for *_, symbol in due]
    return ordered[:limit] if limit > 0 else ordered


def _as_date(value) -> date | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _universe(repo) -> list[str]:
    """Rated symbols in rank order, then recent listings not yet rated.

    New listings are included so their stock page has statements to show while
    they wait for a rating. They come after every rated name, so a cold build
    still reaches the most investable companies first.
    """
    rated = repo.latest_snapshot_symbols()
    try:
        pending = repo.new_listing_symbols()
    except Exception as exc:  # table not deployed yet: rated names only
        logger.warning("New listings unavailable (%s); covering rated names only", exc)
        pending = []
    return list(dict.fromkeys([*rated, *pending]))


def run(
    repo,
    *,
    ticker_factory,
    max_symbols: int = DEFAULT_MAX_SYMBOLS,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    pause_seconds: float = 0.25,
    time_budget_seconds: float | None = None,
    clock=time.monotonic,
    symbols: list[str] | None = None,
    dry_run: bool = False,
    today: date | None = None,
    flush_every: int = 50,
    filed_quarters: FiledQuarters | None = None,
) -> dict[str, int]:
    profile = resolve_market(repo.market)
    today = today or datetime.now(UTC).date()
    wanted = [s.strip().upper() for s in symbols] if symbols else _universe(repo)
    state = repo.financial_statement_state()
    todo = wanted if symbols else select_due(
        wanted,
        state,
        today,
        max_age_days=max_age_days,
        limit=max_symbols,
        filed_latest=filed_quarters.latest() if filed_quarters else None,
    )
    logger.info(
        "%s financial statements: %d in universe, %d stored, %d due this run",
        profile.code, len(wanted), len(state), len(todo),
    )

    pending: list[dict[str, Any]] = []
    counts = {
        "fetched": 0, "with_data": 0, "empty": 0, "written": 0, "deferred": 0,
        "with_filed_quarters": 0,
    }

    def flush():
        if pending and not dry_run:
            counts["written"] += repo.upsert_financial_statements(pending)
        pending.clear()

    started = clock()
    for position, symbol in enumerate(todo, start=1):
        if time_budget_seconds is not None and clock() - started >= time_budget_seconds:
            counts["deferred"] = len(todo) - position + 1
            logger.info(
                "Time budget spent; %d due symbols left for the next run",
                counts["deferred"],
            )
            break
        frames = fetch_frames(ticker_factory(ticker_for(symbol, profile)))
        payload = build_payload(frames)
        source = SOURCE
        if filed_quarters is not None and add_filed_quarters(
            payload, symbol, filed_quarters
        ):
            source = SOURCE_WITH_FILINGS
            counts["with_filed_quarters"] += 1
        counts["fetched"] += 1
        counts["with_data" if payload["has_data"] else "empty"] += 1
        pending.append({
            "symbol": symbol,
            **payload,
            "currency": profile.currency,
            "source": source,
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
    parser.add_argument(
        "--time-budget-minutes",
        type=float,
        default=None,
        help="stop fetching once this much time is spent (the rest waits for the next run)",
    )
    parser.add_argument("--symbols", nargs="*", help="refresh exactly these, ignoring staleness")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import yfinance as yf

    from storage.dashboard_repository import DashboardRepository

    repo = DashboardRepository.from_environment(args.market)
    run(
        repo,
        filed_quarters=load_filed_quarters(
            resolve_market(repo.market), datetime.now(UTC).date()
        ),
        ticker_factory=yf.Ticker,
        max_symbols=args.max_symbols,
        max_age_days=args.max_age_days,
        pause_seconds=args.pause,
        time_budget_seconds=(
            args.time_budget_minutes * 60 if args.time_budget_minutes else None
        ),
        symbols=args.symbols,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

