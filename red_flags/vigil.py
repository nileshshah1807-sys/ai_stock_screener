"""Client and conservative normalizer for TigZig's free VIGIL API.

VIGIL republishes structured NSE/SEBI records.  Provider-derived flags are
kept as evidence in a shadow snapshot; this module deliberately does not
change an investment score.
"""

from __future__ import annotations

import csv
import gzip
import io
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable

import requests


VIGIL_TABLES = (
    "credit_ratings",
    "pledge_data",
    "encumbrance_events",
    "surveillance_flags",
)

_CREDIT_SEVERITY = {
    "default": 3,
    "default_grade": 3,
    "downgrade": 2,
    "negative_outlook": 2,
    "watch_negative": 2,
    "on_watch": 2,
    "watch_developing": 1,
    "watch_in_rating": 1,
    "speculative_grade": 1,
}


class VigilClient:
    """Small, bounded HTTP client with explicit pagination validation."""

    def __init__(
        self,
        base_url: str = "https://api.tigzig.com/vigil/v1",
        timeout_seconds: int = 60,
        page_size: int = 5000,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.page_size = max(1, min(5000, int(page_size)))
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "ai-stock-screener/1.0")

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params=params or None,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"VIGIL {path} returned a non-object response")
        return payload

    def freshness(self) -> dict[str, dict[str, Any]]:
        payload = self._get("freshness")
        rows = payload.get("tables")
        if not isinstance(rows, list):
            raise ValueError("VIGIL freshness response is missing tables")
        return {
            str(row.get("table_name")): row
            for row in rows
            if isinstance(row, dict) and row.get("table_name")
        }

    def table_records(self, table_name: str) -> list[dict[str, Any]]:
        if table_name not in VIGIL_TABLES:
            raise ValueError(f"unsupported VIGIL table: {table_name}")
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self._get(
                f"data/{table_name}",
                limit=self.page_size,
                offset=offset,
                format="json",
            )
            page = payload.get("data")
            if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
                raise ValueError(f"VIGIL {table_name} response is missing row data")
            records.extend(page)
            if not payload.get("has_more"):
                break
            next_offset = payload.get("next_offset")
            if not isinstance(next_offset, int) or next_offset <= offset:
                raise ValueError(f"VIGIL {table_name} returned invalid pagination")
            offset = next_offset
        return records

    def download_table_records(self, table_name: str) -> list[dict[str, Any]]:
        """Read VIGIL's pre-generated compressed CSV in one bounded request."""
        if table_name not in VIGIL_TABLES:
            raise ValueError(f"unsupported VIGIL table: {table_name}")
        response = self.session.get(
            f"{self.base_url}/download/{table_name}",
            params={"format": "csv.gz"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        compressed = response.content
        if not isinstance(compressed, bytes) or not compressed.startswith(b"\x1f\x8b"):
            raise ValueError(f"VIGIL {table_name} download is not gzip data")
        if len(compressed) > 50 * 1024 * 1024:
            raise ValueError(f"VIGIL {table_name} compressed download exceeds 50 MB")
        try:
            raw = gzip.decompress(compressed)
        except (OSError, EOFError) as exc:
            raise ValueError(f"VIGIL {table_name} gzip data is corrupt") from exc
        if len(raw) > 250 * 1024 * 1024:
            raise ValueError(f"VIGIL {table_name} expanded download exceeds 250 MB")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        rows = list(reader)
        if not reader.fieldnames:
            raise ValueError(f"VIGIL {table_name} CSV is missing a header")
        return rows


def build_red_flag_snapshots(
    datasets: dict[str, list[dict[str, Any]]],
    freshness: dict[str, dict[str, Any]],
    *,
    today: date | None = None,
    lookback_days: int = 365,
    stale_after_days: int = 7,
) -> list[dict[str, Any]]:
    """Aggregate raw VIGIL rows into one evidence-bearing snapshot per symbol."""
    current_date = today or date.today()
    flags: dict[str, list[dict[str, Any]]] = defaultdict(list)
    coverage: dict[str, set[str]] = defaultdict(set)
    pledge_pct: dict[str, float] = {}

    _add_credit_flags(
        datasets.get("credit_ratings", []), flags, coverage, current_date, lookback_days
    )
    _add_pledge_flags(datasets.get("pledge_data", []), flags, coverage, pledge_pct)
    _add_encumbrance_flags(
        datasets.get("encumbrance_events", []), flags, coverage, current_date, lookback_days
    )
    _add_surveillance_flags(datasets.get("surveillance_flags", []), flags, coverage)

    table_freshness = {
        table: _freshness_state(freshness.get(table), current_date, stale_after_days)
        for table in VIGIL_TABLES
    }
    stale_tables = sorted(
        table for table, state in table_freshness.items() if state["status"] != "current"
    )
    source_dates = [
        parsed
        for state in table_freshness.values()
        if (parsed := _date_value(state.get("latest_date"))) is not None
    ]
    source_as_of = min(source_dates).isoformat() if source_dates else current_date.isoformat()
    snapshots: list[dict[str, Any]] = []
    for symbol in sorted(coverage):
        symbol_flags = _dedupe_flags(flags.get(symbol, []))
        symbol_flags.sort(key=lambda item: (item["severity"], item.get("date") or ""), reverse=True)
        symbol_flags = symbol_flags[:20]
        severity = max((int(item["severity"]) for item in symbol_flags), default=0)
        summary = "; ".join(str(item["summary"]) for item in symbol_flags[:3])
        if not summary:
            summary = "No observed flags in covered VIGIL datasets"
        snapshots.append({
            "source": "VIGIL",
            "symbol": symbol,
            "severity": severity,
            "flag_count": len(symbol_flags),
            "summary": summary,
            "source_status": "partial_stale" if stale_tables else "current",
            # The combined snapshot is only as current as its oldest required
            # feed. fetched_at in Supabase separately records ingestion time.
            "source_as_of": source_as_of,
            "snapshot": {
                "flags": symbol_flags,
                "tables_present": sorted(coverage[symbol]),
                "table_freshness": {table: state for table, state in table_freshness.items()},
                "stale_tables": stale_tables,
                "promoter_encumbered_pct": pledge_pct.get(symbol),
                "policy": "shadow-v1",
            },
        })
    return snapshots


def _add_credit_flags(rows, flags, coverage, today, lookback_days):
    for row in rows:
        symbol = _symbol(row.get("nse_symbol"))
        if not symbol:
            continue
        coverage[symbol].add("credit_ratings")
        reason = str(row.get("red_flag_reason") or "").strip().lower()
        severity = _CREDIT_SEVERITY.get(reason)
        event_date = _date_value(row.get("date_of_rating") or row.get("broadcast_datetime"))
        if severity is None or not _within_lookback(event_date, today, lookback_days):
            continue
        rating = str(row.get("credit_rating") or "unknown rating").strip()
        agency = str(row.get("rating_agency") or "rating agency").strip()
        flags[symbol].append({
            "type": "credit_rating",
            "severity": severity,
            "date": event_date.isoformat() if event_date else None,
            "summary": f"{reason.replace('_', ' ')}: {agency} {rating}",
            "source_url": row.get("xbrl_url"),
            "provider_reason": reason,
            "dedupe_key": row.get("xbrl_url") or row.get("app_id") or row.get("record_id"),
        })


def _add_pledge_flags(rows, flags, coverage, pledge_pct):
    for row in rows:
        symbol = _symbol(row.get("nse_symbol"))
        if not symbol:
            continue
        coverage[symbol].add("pledge_data")
        value = _number(row.get("perc_encumbered_promoter"))
        if value is None:
            continue
        pledge_pct[symbol] = value
        severity = 3 if value >= 50 else 2 if value >= 25 else 1 if value >= 10 else 0
        if not severity:
            continue
        flags[symbol].append({
            "type": "promoter_pledge",
            "severity": severity,
            "date": _date_text(row.get("sync_date") or row.get("shp_quarter")),
            "summary": f"promoter shares encumbered: {value:.1f}%",
            "source_url": None,
            "provider_reason": "promoter_encumbrance",
            "dedupe_key": f"pledge:{symbol}",
        })


def _add_encumbrance_flags(rows, flags, coverage, today, lookback_days):
    for row in rows:
        symbol = _symbol(row.get("symbol"))
        if not symbol:
            continue
        coverage[symbol].add("encumbrance_events")
        event_type = str(row.get("event_type") or "").strip().lower()
        event_date = _date_value(
            row.get("event_date_to") or row.get("reporting_date") or row.get("broadcast_datetime")
        )
        if not _within_lookback(event_date, today, lookback_days):
            continue
        event_pct = _number(row.get("event_pct")) or 0.0
        if event_type == "invocation":
            severity = 3
        elif event_type == "creation" and event_pct >= 5:
            severity = 2
        elif event_type == "creation" and event_pct >= 1:
            severity = 1
        else:
            continue
        flags[symbol].append({
            "type": "encumbrance_event",
            "severity": severity,
            "date": event_date.isoformat() if event_date else None,
            "summary": f"pledge {event_type}: {event_pct:.2f}% of shares",
            "source_url": row.get("filing_url"),
            "provider_reason": event_type,
            "dedupe_key": row.get("seq_id") or row.get("id"),
        })


def _add_surveillance_flags(rows, flags, coverage):
    for row in rows:
        symbol = _symbol(row.get("symbol"))
        if not symbol:
            continue
        coverage[symbol].add("surveillance_flags")
        observations: list[tuple[int, str]] = []
        for key, label, severity in (
            ("gsm_stage", "GSM", 3),
            ("esm_stage", "ESM", 3),
            ("long_term_asm_stage", "long-term ASM", 2),
            ("short_term_asm_stage", "short-term ASM", 2),
        ):
            value = row.get(key)
            if value not in (None, "", 0, "0"):
                observations.append((severity, f"{label} stage {value}"))
        for key, label, severity in (
            ("is_irp", "insolvency resolution process", 3),
            ("is_listing_fee_default", "listing-fee default", 3),
            ("is_ica", "inter-creditor agreement", 2),
            ("is_encumbered_50pct", "promoter encumbrance at least 50%", 3),
            ("is_pledge_flagged", "exchange pledge flag", 2),
            ("is_bz_sz", "BZ/SZ series", 2),
            ("is_loss_making", "exchange loss-making flag", 1),
        ):
            if _truthy(row.get(key)):
                observations.append((severity, label))
        if not observations:
            continue
        severity = max(item[0] for item in observations)
        flags[symbol].append({
            "type": "exchange_surveillance",
            "severity": severity,
            "date": _date_text(row.get("sync_date")),
            "summary": ", ".join(item[1] for item in observations),
            "source_url": None,
            "provider_reason": "exchange_snapshot",
            "dedupe_key": f"surveillance:{symbol}",
        })


def _freshness_state(row: dict[str, Any] | None, today: date, stale_after_days: int) -> dict[str, Any]:
    latest_text = row.get("latest_date") if isinstance(row, dict) else None
    latest = _date_value(latest_text)
    age_days = (today - latest).days if latest else None
    status = (
        "current"
        if age_days is not None and 0 <= age_days <= stale_after_days
        else "stale"
    )
    return {
        "status": status,
        "latest_date": latest.isoformat() if latest else str(latest_text or ""),
        "age_days": age_days,
        "row_count": row.get("row_count") if isinstance(row, dict) else None,
    }


def _dedupe_flags(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("dedupe_key") or "|").strip()
        existing = best.get(key)
        if existing is None or int(item["severity"]) > int(existing["severity"]):
            best[key] = item
    output = []
    for item in best.values():
        clean = dict(item)
        clean.pop("dedupe_key", None)
        output.append(clean)
    return output


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(text[:19] if "%S" in pattern else text[:11], pattern).date()
        except ValueError:
            continue
    return None


def _date_text(value: Any) -> str | None:
    parsed = _date_value(value)
    return parsed.isoformat() if parsed else None


def _within_lookback(value: date | None, today: date, lookback_days: int) -> bool:
    if value is None:
        return False
    age = (today - value).days
    return 0 <= age <= lookback_days
