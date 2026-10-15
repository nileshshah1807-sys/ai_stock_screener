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

Where the market has an index of results filings (NSE), the quarterly
results are the filings', not the vendor's. ``workers.quarterly_filings``
stores every filing as the company makes it, and the quarterly statement is
built from those rows (`compose_quarters`):

* every quarter the company has filed is drawn from its filing, on one basis
  -- consolidated where the latest quarter was filed consolidated, which is
  also the vendor's convention;
* the vendor's figures stand only for a quarter with no filing on that basis
  (before the exchange's index begins, or a filing missing from it), and of
  those only the lines that mean the same at both sources: a vendor line that
  disagrees with the filing on the latest quarter both have (a broker's
  revenue net of its fees, pretax profit that counts associates) stays
  ``null`` there rather than sitting beside figures it is not comparable to.

The vendor's own quarterly statement is kept under
``quarterly.vendor_income``, so a newly stored filing can be drawn into the
page (`recompose_quarters`) without asking the vendor again. The filed
periods are listed under ``quarterly.income.filed_periods`` and the row's
``source`` names both origins.
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

SOURCE_WITH_FILINGS = "NSE filings (quarterly results) and Yahoo Finance"
# Three years of quarters. The vendor serves five or six; the filings grow by
# one a quarter and would otherwise widen the table without end.
MAX_QUARTERS = 12
# Both sources publish the filing's own figure, so agreement is exact or it is
# a different line; the margin only absorbs rounding.
FILED_MATCH_TOLERANCE = 0.01
# The page's rows a filing supplies (screener.quarterly_results.STATEMENT_TAGS
# and the operating profit derived from them).
FILED_LINES = (
    "revenue",
    "other_income",
    "interest",
    "depreciation",
    "pbt",
    "tax",
    "net_profit",
    "eps",
    "operating_profit",
)

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


def _anchored(lines: dict[str, Any] | None) -> bool:
    lines = lines or {}
    return any(lines.get(key) is not None for key in ANCHORS["income"])


def filed_statement(filings: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """A company's stored filings as one quarterly statement, on one basis."""
    usable = [f for f in filings if _anchored(f.get("lines"))]
    if not usable:
        return None
    period_of = {id(f): str(f["period_end"])[:10] for f in usable}
    latest = max(period_of.values())
    consolidated = any(
        f.get("is_consolidated") and period_of[id(f)] == latest for f in usable
    )
    chosen = {
        period_of[id(f)]: f["lines"]
        for f in usable
        if bool(f.get("is_consolidated")) == consolidated
    }
    periods = sorted(chosen)
    return {
        "periods": periods,
        "rows": {
            key: [_clean(chosen[p].get(key), DECIMALS.get(key, 0)) for p in periods]
            for key in FILED_LINES
        },
    }


def vendor_quarters(quarterly: dict[str, Any]) -> dict[str, Any]:
    """The vendor's own quarterly income statement out of a stored payload.

    Rows written before ``vendor_income`` existed carry the vendor's quarters
    and the filed ones in one statement; the filed columns are listed, so
    dropping them gives the vendor's back.
    """
    if "vendor_income" in quarterly:
        return quarterly["vendor_income"]
    income = quarterly.get("income") or {"periods": [], "rows": {}}
    filed = set(income.get("filed_periods") or ())
    if not filed:
        return income
    keep = [i for i, period in enumerate(income["periods"]) if period not in filed]
    rows = {
        key: [values[i] for i in keep]
        for key, values in income["rows"].items()
        if key != "expenses"
    }
    _derive("income", rows, len(keep))
    return {
        "periods": [income["periods"][i] for i in keep],
        "rows": {k: v for k, v in rows.items() if any(x is not None for x in v)},
    }


def _disagreeing_lines(vendor: dict[str, Any], filed: dict[str, Any]) -> set[str]:
    """Vendor lines that mean something else than the filing's line of that name.

    Judged on the latest quarter both report the line for. A line either side
    never reported for a shared quarter cannot be judged and is kept.
    """
    filed_at = {period: i for i, period in enumerate(filed["periods"])}
    shared = [(i, filed_at[p]) for i, p in enumerate(vendor["periods"]) if p in filed_at]
    disagree = set()
    for key, values in vendor["rows"].items():
        filed_values = filed["rows"].get(key)
        if key == "expenses" or filed_values is None:
            continue
        for vendor_i, filed_i in reversed(shared):
            if values[vendor_i] is None or filed_values[filed_i] is None:
                continue
            if not _agrees(filed_values[filed_i], values[vendor_i]):
                disagree.add(key)
            break
    return disagree


def compose_quarters(
    vendor: dict[str, Any], filings: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """The quarterly statement: filed quarters first, the vendor's for the rest."""
    filed = filed_statement(filings)
    if filed is None:
        return vendor
    filed_periods = set(filed["periods"])
    disagree = _disagreeing_lines(vendor, filed)
    merged = sorted(filed_periods | set(vendor["periods"]))
    keys = [*FILED_LINES, *(k for k in vendor["rows"] if k not in FILED_LINES)]
    rows: dict[str, list] = {}
    for key in keys:
        if key == "expenses":  # derived again below, across every column
            continue
        from_filing = dict(zip(filed["periods"], filed["rows"].get(key, ()), strict=False))
        from_vendor = (
            {}
            if key in disagree
            else dict(zip(vendor["periods"], vendor["rows"].get(key, ()), strict=False))
        )
        rows[key] = [
            from_filing.get(p) if p in filed_periods else from_vendor.get(p)
            for p in merged
        ]
    # A vendor quarter left with neither anchor line is not a column.
    keep = [
        i for i in range(len(merged))
        if any(rows.get(a, [None] * len(merged))[i] is not None for a in ANCHORS["income"])
    ][-MAX_QUARTERS:]
    periods = [merged[i] for i in keep]
    rows = {key: [values[i] for i in keep] for key, values in rows.items()}
    _derive("income", rows, len(periods))
    return {
        "periods": periods,
        "rows": {k: v for k, v in rows.items() if any(x is not None for x in v)},
        "filed_periods": [p for p in periods if p in filed_periods],
    }


def apply_filings(payload: dict[str, Any], filings: Iterable[dict[str, Any]]) -> bool:
    """Draw ``payload``'s quarterly results from the filings; True if any was used."""
    statements = payload["statements"]
    vendor = vendor_quarters(statements["quarterly"])
    composed = compose_quarters(vendor, list(filings))
    if not composed.get("filed_periods"):
        statements["quarterly"] = {"income": vendor}
        payload["latest_quarter"] = vendor["periods"][-1] if vendor["periods"] else None
        return False
    statements["quarterly"] = {"income": composed, "vendor_income": vendor}
    payload["latest_quarter"] = composed["periods"][-1]
    payload["has_data"] = True
    return True


def load_filings(repo, profile, symbols: list[str]) -> dict[str, list[dict[str, Any]]] | None:
    """Stored filings for ``symbols``, or None where the market has none."""
    if not profile.quarterly_results_provider or not symbols:
        return None
    try:
        return repo.quarterly_filings(symbols)
    except Exception as exc:  # the vendor's statements are still worth publishing
        logger.warning(
            "Stored results filings unavailable (%s); publishing the vendor's "
            "quarters only this run. Apply storage/quarterly_filings_schema.sql "
            "if the table is missing.",
            exc,
        )
        return None


def recompose_quarters(repo, symbols: Iterable[str], *, dry_run: bool = False) -> int:
    """Redraw stored rows' quarterly results from the filings now stored.

    What a newly parsed filing reaches the page through, without asking the
    vendor again. A company with no stored row yet gets one, filings
    included, on the vendor refresh that creates it.
    """
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return 0
    filings = repo.quarterly_filings(symbols)
    updated = []
    for row in repo.financial_statement_rows(symbols):
        payload = {
            "statements": row["statements"],
            "has_data": row.get("has_data"),
            "latest_annual": row.get("latest_annual"),
            "latest_quarter": row.get("latest_quarter"),
        }
        filed = apply_filings(payload, filings.get(row["symbol"], []))
        updated.append(
            {**row, **payload, "source": SOURCE_WITH_FILINGS if filed else row["source"]}
        )
    if updated and not dry_run:
        repo.upsert_financial_statements(updated)
    logger.info(
        "Quarterly results redrawn from filings for %d stored row(s)%s",
        len(updated), " (dry run, nothing written)" if dry_run else "",
    )
    return len(updated)


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
    """Symbols to refresh this run: never-fetched first, then oldest first."""
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
        # The filings are read just before the write, not once per run. The
        # Quarterly filings job stores and draws a result while this run is
        # still fetching; a copy of the filings taken when the run began
        # would overwrite that quarter, and nothing would draw it again.
        filings = load_filings(repo, profile, [row["symbol"] for row in pending])
        for row in pending:
            if filings is not None and apply_filings(row, filings.get(row["symbol"], [])):
                row["source"] = SOURCE_WITH_FILINGS
                counts["with_filed_quarters"] += 1
            counts["with_data" if row["has_data"] else "empty"] += 1
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
        counts["fetched"] += 1
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

