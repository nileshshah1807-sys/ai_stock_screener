"""The US Results page's data: each stock's last quarters, as filings rows.

The Results page reads ``quarterly_filings`` through ``quarterly_result_feed``
(see ``dashboard/lib/results.ts``). The US has no filing index, so this fills
the same table for ``market = 'US'`` from the quarterly income the Financial
statements workflow has already stored in ``financial_statements`` -- nothing
is fetched, and the page, the feed view and the YoY arithmetic need no US
branch.

What a US row is, against an NSE one:

* ``period_end`` is the company's fiscal quarter end, as the vendor states it.
* ``broadcast_at`` / ``filed_at`` is when the bell first recorded the quarter
  (``market_events``), else when the statements row that first held it was
  fetched. It is the time *we* first saw the quarter, not the company's
  release; it is never moved by a later run.
* One basis (``is_consolidated`` true); ``document_url`` is empty and there is
  no viewer link -- the vendor names no filing.
* ``lines`` are the vendor's quarterly income lines, whole USD; a line the
  vendor lacks is null.

A quarter already stored is not rewritten (shortcut: a figure the vendor later
restates stays as first stored; upgrade when that matters).
"""

from __future__ import annotations

import argparse
import logging
import math
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

#: The vendor's quarterly rows that become a filing's ``lines``.
LINE_NAMES = (
    "revenue", "other_income", "interest", "depreciation", "pbt", "tax", "net_profit", "eps", "operating_profit",
)
#: Marks a row as the vendor's, for the NSE parser which ignores it by market anyway.
TAXONOMY = "US"
PARSER_VERSION = 1


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def quarter_lines(rows: dict[str, list[Any]], index: int) -> dict[str, float | int | None]:
    """One quarter's ``lines``: the vendor's income rows at ``index``, plus ``pat`` (the profit growth is measured on)."""
    lines = {name: _number((rows.get(name) or [None] * (index + 1))[index]) for name in LINE_NAMES}
    lines["pat"] = lines["net_profit"]
    return lines


def filing_rows(
    statement: dict[str, Any],
    stored: set[str],
    first_seen: dict[tuple[str, str], str],
    company: str | None,
) -> list[dict[str, Any]]:
    """The not-yet-stored quarters of one stock's statements row, as ``quarterly_filings`` rows."""
    income = (statement.get("statements") or {}).get("quarterly", {}).get("income") or {}
    periods = income.get("periods") or []
    rows = income.get("rows") or {}
    symbol = str(statement["symbol"])
    out = []
    for index, period in enumerate(periods):
        period = str(period)[:10]
        lines = quarter_lines(rows, index)
        # A quarter that reported neither revenue nor profit is not a result to show.
        if period in stored or (lines["revenue"] is None and lines["net_profit"] is None):
            continue
        seen = first_seen.get((symbol, period)) or statement.get("fetched_at")
        out.append(
            {
                "symbol": symbol,
                "period_end": period,
                "is_consolidated": True,
                "seq_id": f"vendor:{period}",
                "filed_at": seen,
                "broadcast_at": seen,
                "taxonomy": TAXONOMY,
                "document_url": "",
                "viewer_url": None,
                "company": company,
                "lines": lines,
                "parser_version": PARSER_VERSION,
            }
        )
    return out


def stocks_to_read(state: dict[str, dict[str, Any]], stored_through: dict[str, str]) -> list[str]:
    """Stocks whose statements hold a later quarter than the filings stored for them."""
    return [
        symbol
        for symbol, row in sorted(state.items())
        if row.get("has_data") and str(row.get("latest_quarter") or "")[:10] > stored_through.get(symbol, "")
    ]


def run(repo, *, dry_run: bool = False) -> dict[str, int]:
    counts = {"stocks": 0, "rows": 0, "written": 0}
    if repo.market != "US":
        logger.warning("US results are written for the US only (market %s)", repo.market)
        return counts
    try:
        filings = repo.quarterly_filing_state()
    except Exception as exc:
        logger.warning("US results not stored: quarterly_filings is unreadable (%s). Apply storage/quarterly_filings_schema.sql.", exc)
        return counts
    stored: dict[str, set[str]] = {}
    for symbol, period, _ in filings:
        stored.setdefault(symbol, set()).add(period)
    symbols = stocks_to_read(repo.financial_statement_state(), {s: max(p) for s, p in stored.items()})
    if not symbols:
        logger.info("US results: nothing new")
        return counts

    first_seen = repo.result_first_seen()
    companies = repo.snapshot_companies()
    rows: list[dict[str, Any]] = []
    for statement in repo.financial_statement_rows(symbols):
        rows += filing_rows(statement, stored.get(str(statement["symbol"]), set()), first_seen, companies.get(str(statement["symbol"])))
    counts.update(stocks=len(symbols), rows=len(rows))
    if rows and not dry_run:
        counts["written"] = repo.upsert_quarterly_filings(rows)
    logger.info("US results: %s%s", counts, " (dry run, nothing written)" if dry_run else "")
    return counts


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--market", default="US", help="US (the only market with no filing index)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from storage.dashboard_repository import DashboardRepository

    run(DashboardRepository.from_environment(args.market), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
