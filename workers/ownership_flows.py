"""Who owns each stock and where foreign money is going, as snapshot columns.

The screener filters on columns of its snapshot, so the evening publisher
stamps these onto each NSE row from what other jobs already stored:

- ``promoter_pct``, ``fii_pct``, ``dii_pct``: the latest quarter's shareholding
  pattern (``shareholding_patterns``, workers/shareholding.py), in percent of
  shares; ``*_change_qoq`` the move from the quarter before, in percentage
  points, null unless that quarter is stored too; ``*_change_1y`` the move from
  the same quarter a year earlier. ``retail_pct`` is the public remainder.
- ``deals_net_cr_1m``, ``foreign_deals_net_cr_1m``: bulk and block deals in the
  last 30 days, bought less sold, rupees crore (``bulk_block_deals``); foreign
  is the client name rule of workers/fpi_flows.py. Null when there were none.
- ``sector_fpi_vs_avg_cr``: the stock's NSE sector's FPI net investment in
  NSDL's latest fortnight less its average over the 12 fortnights before it,
  rupees crore (``live/NSE/fpi-flows.json``, workers/fpi_flows.py); positive
  when foreign buying runs above its six-month pace. The sector is NSE's, as on
  the sector pages (workers/sectors.nse_sector_rows).

Display evidence for filters: nothing in ``screener/`` reads it, and a source
that cannot be read leaves its columns null rather than failing the publish.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from screener.numeric import round_half_up, safe_float
from workers.fpi_flows import DEAL_DAYS, is_foreign_investor
from workers.sectors import nse_sector_rows, sector_slug

logger = logging.getLogger(__name__)

COLUMNS = (
    "promoter_pct", "fii_pct", "dii_pct",
    "promoter_change_qoq", "fii_change_qoq", "dii_change_qoq",
    "sector_fpi_vs_avg_cr",
    "retail_pct", "promoter_change_1y", "fii_change_1y", "dii_change_1y",
    "deals_net_cr_1m", "foreign_deals_net_cr_1m",
)
GROUPS = ("promoter", "fii", "dii")

# A quarter's filing lands up to ~3 weeks after it ends; older than this, the company stopped filing.
MAX_HOLDING_AGE_DAYS = 200
# Consecutive quarter ends are 90-92 days apart.
QUARTER_GAP_DAYS = (85, 95)
# The same quarter a year earlier.
YEAR_GAP_DAYS = (360, 370)
# The fortnights the latest is measured against (six months), and the fewest that make an average.
FPI_HISTORY = 12
FPI_MIN_HISTORY = 6
# NSDL reports twice a month; a latest fortnight older than this is not "now".
MAX_FPI_AGE_DAYS = 45


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def holding_fields(patterns: list[dict[str, Any]], run_date: date) -> dict[str, dict[str, float | None]]:
    """``{symbol: {promoter_pct, ..., dii_change_qoq}}`` from stored quarters, in any order."""
    by_symbol: dict[str, list[tuple[date, dict[str, Any]]]] = {}
    for row in patterns:
        day = _day(row.get("period_end"))
        if day is not None and row.get("symbol"):
            by_symbol.setdefault(str(row["symbol"]), []).append((day, row))
    out: dict[str, dict[str, float | None]] = {}
    for symbol, quarters in by_symbol.items():
        quarters.sort(key=lambda item: item[0])
        latest_day, latest = quarters[-1]
        if (run_date - latest_day).days > MAX_HOLDING_AGE_DAYS:
            continue
        previous, year_ago = (
            next((row for day, row in quarters if low <= (latest_day - day).days <= high), None)
            for low, high in (QUARTER_GAP_DAYS, YEAR_GAP_DAYS)
        )
        retail = safe_float(latest.get("public"))
        fields: dict[str, float | None] = {"retail_pct": None if retail is None else round_half_up(retail, 2)}
        for group in GROUPS:
            now = safe_float(latest.get(group))
            fields[f"{group}_pct"] = None if now is None else round_half_up(now, 2)
            for suffix, then in (("qoq", previous), ("1y", year_ago)):
                before = safe_float(then.get(group)) if then else None
                fields[f"{group}_change_{suffix}"] = None if now is None or before is None else round_half_up(now - before, 2)
        out[symbol] = fields
    return out


def deal_fields(deals: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """``{symbol: {deals_net_cr_1m, foreign_deals_net_cr_1m?}}``: bought less sold, crore; foreign only where it dealt."""
    totals: dict[str, dict[str, float]] = {}
    for deal in deals:
        quantity, price = safe_float(deal.get("quantity")), safe_float(deal.get("price"))
        if not deal.get("symbol") or quantity is None or price is None:
            continue
        value = (1 if str(deal.get("side")).upper() == "BUY" else -1) * quantity * price / 1e7
        entry = totals.setdefault(str(deal["symbol"]), {"deals_net_cr_1m": 0.0})
        entry["deals_net_cr_1m"] += value
        if is_foreign_investor(str(deal.get("client_name") or "")):
            entry["foreign_deals_net_cr_1m"] = entry.get("foreign_deals_net_cr_1m", 0.0) + value
    return {symbol: {k: round_half_up(v, 2) for k, v in entry.items()} for symbol, entry in totals.items()}


def sector_flow_vs_average(fpi_rows: list[dict[str, Any]], run_date: date) -> dict[str, float]:
    """``{sector slug: latest fortnight's net less the mean of the FPI_HISTORY before it}``, crore."""
    periods = sorted(
        (row for row in fpi_rows or [] if _day(row.get("period_end")) and isinstance(row.get("sectors"), list)),
        key=lambda row: str(row["period_end"]),
    )
    if not periods:
        return {}
    latest = periods[-1]
    if (run_date - _day(latest["period_end"])).days > MAX_FPI_AGE_DAYS:
        logger.warning("FPI flows end %s: sector flow column left empty", latest["period_end"])
        return {}

    def nets(row: dict[str, Any]) -> dict[str, float]:
        return {
            sector_slug(str(entry.get("sector") or "")): value
            for entry in row["sectors"]
            if (value := safe_float(entry.get("net"))) is not None
        }

    now = nets(latest)
    history = [nets(row) for row in periods[-1 - FPI_HISTORY:-1]]
    out = {}
    for slug, net in now.items():
        past = [row[slug] for row in history if slug in row]
        if len(past) >= FPI_MIN_HISTORY:
            out[slug] = round_half_up(net - sum(past) / len(past), 2)
    return out


def snapshot_fields(repository: Any, rows: list[dict[str, Any]], run_date: str) -> dict[str, dict[str, Any]]:
    """Each NSE snapshot row's ownership and sector-flow columns, by symbol; the publisher writes them."""
    day = date.fromisoformat(run_date)
    out: dict[str, dict[str, Any]] = {}
    try:
        since = (day - timedelta(days=MAX_HOLDING_AGE_DAYS + max(YEAR_GAP_DAYS))).isoformat()
        for symbol, fields in holding_fields(repository.shareholding_since(since), day).items():
            out.setdefault(symbol, {}).update(fields)
    except Exception as exc:  # noqa: BLE001 -- display evidence: the run publishes without it
        logger.warning("Shareholding unreadable, ownership columns left empty: %s", exc)
    try:
        since = (day - timedelta(days=DEAL_DAYS)).isoformat()
        for symbol, fields in deal_fields(repository.bulk_block_deals_since(since)).items():
            out.setdefault(symbol, {}).update(fields)
    except Exception as exc:  # noqa: BLE001 -- display evidence: the run publishes without it
        logger.warning("Bulk/block deals unreadable, deal columns left empty: %s", exc)
    try:
        flows = sector_flow_vs_average((repository.fpi_flows_object() or {}).get("rows") or [], day)
        classified = ((repository.nse_sectors_object() or {}).get("rows") or []) if flows else []
        grouped = nse_sector_rows(rows, {r["symbol"]: r for r in classified if r.get("sector")}) if classified else []
        # Rows back unchanged (no nse_industry key) mean NSE's sectors do not cover the market yet: no
        # mapping then, since Yahoo's names would match NSDL's by accident ("Financial Services").
        for row in grouped:
            if "nse_industry" in row and row.get("sector"):
                value = flows.get(sector_slug(row["sector"]))
                if value is not None:
                    out.setdefault(row["symbol"], {})["sector_fpi_vs_avg_cr"] = value
    except Exception as exc:  # noqa: BLE001 -- display evidence: the run publishes without it
        logger.warning("FPI sector flows unreadable, sector flow column left empty: %s", exc)
    logger.info(
        "Ownership columns for %d symbols, sector flow for %d",
        sum(1 for f in out.values() if "fii_pct" in f), sum(1 for f in out.values() if "sector_fpi_vs_avg_cr" in f),
    )
    return out
