"""PostgREST adapter for the dashboard read model.

Kept separate from `SupabaseRepository`, which owns private transcript data.
The two touch disjoint tables and have different failure expectations: a
transcript write loss is a research-evidence loss, while a dashboard write loss
only means the site serves the previous run behind a staleness banner.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import requests

from screener.markets import DEFAULT_MARKET
from screener.markets import resolve as resolve_market
from storage.object_store import ObjectStore

logger = logging.getLogger(__name__)

# A snapshot row is ~150 typed columns, so a batch of rows is large in bytes
# even though the row count is modest. Chunks are sized for request-body
# limits rather than row count.
DEFAULT_CHUNK_SIZE = 200

# A price-series row carries three encoded arrays and runs 20-30 KB, so the
# snapshot chunk size would produce a ~6 MB request body.
PRICE_SERIES_CHUNK_SIZE = 25

#: Parallel object transfers. One series is one object, so a full publish is a
#: few thousand small requests; sixteen at a time keeps it to about a minute.
STORAGE_WORKERS = 16

#: Snapshot rows deleted per statement when pruning. A row was ~27 KB while it
#: carried its payload, and a whole run (~2,300 rows) in one statement outran
#: the database's statement timeout; 250 stays well inside it.
PRUNE_BATCH_SIZE = 250

#: Pause before each retry of an idempotent write that hit a transient network
#: error. Doubles each time: 5, 10, 20 seconds.
RETRY_BACKOFF_SECONDS = 5

#: Gateway answers that mean the database was briefly unreachable, not that
#: the request was wrong: Cloudflare's 520-524 in front of Supabase, and the
#: proxy's own 502-504. Retried like a timeout (NSE publish, 26 Oct 2026: one
#: 520 on a snapshot chunk failed the run).
TRANSIENT_STATUS_CODES = frozenset({502, 503, 504, 520, 521, 522, 523, 524})


def chunked(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


class DashboardRepository:
    """Read-model writer for one market.

    The repository is market-scoped rather than taking a market argument on
    every method: a publisher process loads exactly one market's run, so
    binding it once at construction removes a dozen chances to forget the
    filter. Every read is narrowed to ``self.market`` and every write is
    stamped with it.
    """

    def __init__(
        self,
        url: str,
        service_role_key: str,
        timeout_seconds: int = 60,
        market: str = DEFAULT_MARKET,
    ):
        if not url or not service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self.base_url = f"{url.rstrip('/')}/rest/v1"
        self._objects = ObjectStore(url, service_role_key, timeout_seconds)
        # Raises on an unknown code, so a typo cannot publish a US run into the
        # NSE market.
        self.market = resolve_market(market).code
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }

    @classmethod
    def from_environment(cls, market: str | None = None) -> DashboardRepository:
        return cls(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            int(os.getenv("SUPABASE_TIMEOUT_SECONDS", "60")),
            market or os.getenv("MARKET", DEFAULT_MARKET),
        )

    # -- market scoping -----------------------------------------------------

    def _scoped(self, params: dict[str, Any]) -> dict[str, Any]:
        """Narrow a PostgREST query to this repository's market."""
        return {**params, "market": f"eq.{self.market}"}

    def _stamped(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Stamp rows with this repository's market before a write."""
        return [{**row, "market": self.market} for row in rows]

    def _request(self, method: str, path: str, *, retries: int = 0, **kwargs: Any) -> Any:
        """One PostgREST call.

        ``retries`` re-sends after a connection error, a timeout or a gateway
        error (``TRANSIENT_STATUS_CODES``). Pass it only for idempotent calls --
        an upsert on a conflict key, a delete -- since a write that timed out
        may still have landed.
        """
        headers = {**self.headers, **kwargs.pop("headers", {})}
        for attempt in range(retries + 1):
            try:
                response = self.session.request(
                    method,
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers=headers,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
                if response.status_code not in TRANSIENT_STATUS_CODES or attempt == retries:
                    break
                failure: object = f"HTTP {response.status_code}"
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == retries:
                    raise
                failure = exc
            pause = RETRY_BACKOFF_SECONDS * 2**attempt
            logger.warning(
                "%s %s failed (%s); retry %d of %d in %ds",
                method, path, failure, attempt + 1, retries, pause,
            )
            time.sleep(pause)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # PostgREST reports the offending column and constraint in the body.
            # Without it a schema mismatch surfaces only as "400 Bad Request",
            # which is not enough to diagnose a wide upsert.
            detail = (response.text or "").strip()[:800]
            raise requests.HTTPError(
                f"{exc} | {method} {path} | {detail}", response=response
            ) from exc
        if not response.content:
            return None
        return response.json()

    # -- runs ---------------------------------------------------------------

    def upsert_run(self, run: dict[str, Any]) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "screener_runs?on_conflict=market,run_date",
            json={**run, "market": self.market},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        return rows[0] if rows else {}

    def latest_run(self) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "screener_runs",
            params=self._scoped(
                {"select": "*", "order": "run_date.desc", "limit": "1"}
            ),
        )
        return rows[0] if rows else None

    def previous_completed_run_date(self, before: str) -> str | None:
        """The completed run published immediately before ``before``.

        One published run corresponds to one completed NSE session, because the
        scheduled session guard refuses to publish a weekend, a holiday, or an
        already-published session. So the previous run is normally the previous
        session -- but not if a scheduled run was missed, which is why callers
        that care about adjacency must check the gap themselves.

        Read from ``screener_history`` rather than ``screener_runs``: runs are
        pruned to the latest one, while history keeps every published day, and
        rank 1 appears exactly once per published run.
        """
        rows = self._request(
            "GET",
            "screener_history",
            params=self._scoped({
                "select": "observed_on",
                "observed_on": f"lt.{before}",
                "investment_rank": "eq.1",
                "order": "observed_on.desc",
                "limit": "1",
            }),
        )
        return str(rows[0]["observed_on"]) if rows else None

    def latest_completed_run(self) -> dict[str, Any] | None:
        """Return the newest published run, ignoring in-flight reservations."""
        rows = self._request(
            "GET",
            "screener_runs",
            params=self._scoped({
                "select": "*",
                "row_count": "gt.0",
                "order": "run_date.desc",
                "limit": "1",
            }),
        )
        return rows[0] if rows else None

    # -- snapshot -----------------------------------------------------------

    def replace_snapshot_rows(
        self,
        run_date: str,
        rows: list[dict[str, Any]],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> int:
        """Upsert every row of one run.

        Rows are merged rather than deleted-then-inserted so a partially failed
        load leaves the previous run's data intact and readable, instead of
        emptying the table the dashboard is serving from.
        """
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "screener_snapshot?on_conflict=market,run_date,symbol",
                json=self._stamped(chunk),
                headers={
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
                retries=2,
            )
            written += len(chunk)
        return written

    def snapshot_logo_candidates(
        self,
        run_date: str,
        *,
        only_missing: bool = True,
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read the small set of fields needed for a logo-domain backfill."""
        rows: list[dict[str, Any]] = []
        for offset in range(0, 1_000_000, page_size):
            params: dict[str, Any] = self._scoped({
                "select": "symbol,company,logo_domain",
                "run_date": f"eq.{run_date}",
                "order": "symbol.asc",
                "limit": str(page_size),
                "offset": str(offset),
            })
            if only_missing:
                params["logo_domain"] = "is.null"
            page = self._request(
                "GET",
                "screener_snapshot",
                params=params,
            ) or []
            rows.extend(page)
            if len(page) < page_size:
                break
        return rows

    def upsert_snapshot_logo_domains(
        self,
        run_date: str,
        domains: list[dict[str, Any]],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> int:
        """Patch logo domains without replacing any other snapshot fields."""
        written = 0
        rows = [
            {
                "run_date": run_date,
                "symbol": row["symbol"],
                "logo_domain": row["logo_domain"],
            }
            for row in domains
        ]
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "screener_snapshot?on_conflict=market,run_date,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    def snapshot_session_change_state(
        self,
        run_date: str,
        page_size: int = 1000,
    ) -> dict[str, Any]:
        """Symbol -> current ``pct_change_1d`` for one snapshot.

        Reads the one field it sets: the session change is written with PATCH,
        so nothing else of the row has to make the round trip.
        """
        state: dict[str, Any] = {}
        for offset in range(0, 1_000_000, page_size):
            page = self._request(
                "GET",
                "screener_snapshot",
                params=self._scoped({
                    "select": "symbol,pct_change_1d",
                    "run_date": f"eq.{run_date}",
                    "order": "symbol.asc",
                    "limit": str(page_size),
                    "offset": str(offset),
                }),
            ) or []
            for row in page:
                state[str(row.get("symbol") or "")] = row.get("pct_change_1d")
            if len(page) < page_size:
                break
        state.pop("", None)
        return state

    def history_closes(
        self,
        observed_on: str,
        page_size: int = 1000,
    ) -> dict[str, float]:
        """Symbol -> raw close recorded for one observation date.

        `screener_history.current_price` is the *unadjusted* close, which is
        what makes a difference of two of these a raw-basis return.
        """
        closes: dict[str, float] = {}
        for offset in range(0, 1_000_000, page_size):
            page = self._request(
                "GET",
                "screener_history",
                params=self._scoped({
                    "select": "symbol,current_price",
                    "observed_on": f"eq.{observed_on}",
                    "order": "symbol.asc",
                    "limit": str(page_size),
                    "offset": str(offset),
                }),
            ) or []
            for row in page:
                symbol = str(row.get("symbol") or "").strip().upper()
                price = row.get("current_price")
                if not symbol or price is None:
                    continue
                try:
                    closes[symbol] = float(price)
                except (TypeError, ValueError):
                    continue
            if len(page) < page_size:
                break
        return closes

    def patch_snapshot_row(
        self,
        run_date: str,
        symbol: str,
        values: dict[str, Any],
    ) -> None:
        """Update named fields on one snapshot row.

        A real UPDATE, not an upsert. PostgREST applies one request body to
        every matching row, so a per-row value needs a per-row request -- which
        is the deliberate trade here. It touches exactly the columns named,
        where an upsert of 2,370 rows would put every column of the run in the
        blast radius to set one nullable number.
        """
        self._request(
            "PATCH",
            "screener_snapshot",
            params=self._scoped({"run_date": f"eq.{run_date}", "symbol": f"eq.{symbol}"}),
            json=values,
            headers={"Prefer": "return=minimal"},
        )

    # -- price series (Supabase Storage) ------------------------------------
    #
    # One gzip JSON object per symbol, plus one calendar object per market,
    # each holding exactly the fields the price_series / price_calendar rows
    # held, so the readers decode them unchanged.

    def _price_path(self, name: str) -> str:
        return f"price-series/{self.market}/{name}.json.gz"

    def _series_path(self, symbol: str) -> str:
        return self._price_path(f"symbols/{symbol}")

    def _storage(self, method: str, path: str, body: bytes | None = None) -> bytes | None:
        """One object transfer. Returns the body of a read; None when absent."""
        if method == "GET":
            return self._objects.get(path)
        self._objects.put(path, body or b"")
        return None

    def _put_json(self, path: str, payload: dict[str, Any]) -> None:
        # mtime=0 keeps an unchanged payload byte-identical across publishes.
        body = gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)
        self._storage("POST", path, body)

    def _get_json(self, path: str) -> dict[str, Any] | None:
        body = self._storage("GET", path)
        return None if body is None else json.loads(gzip.decompress(body))

    def upsert_price_calendar(self, calendar: dict[str, Any]) -> None:
        """Replace this market's trading calendar.

        One per market: NSE and NYSE sessions do not line up, so a shared
        calendar would misindex every US series.
        """
        self._put_json(self._price_path("calendar"), {**calendar, "market": self.market})

    def read_price_calendar(self) -> dict[str, Any] | None:
        """This market's calendar object, or None if none is published."""
        return self._get_json(self._price_path("calendar"))

    def published_calendar_size(self) -> int | None:
        """Session count of the live calendar, or None if none is published."""
        calendar = self.read_price_calendar()
        if not calendar:
            return None
        return int(calendar.get("session_count") or 0) or None

    def upsert_price_series(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = PRICE_SERIES_CHUNK_SIZE,
    ) -> int:
        """Write each encoded series as its own object; returns the count.

        ``chunk_size`` is kept for the old signature; objects are written one
        per request, sixteen at a time.
        """
        del chunk_size

        def write(row: dict[str, Any]) -> None:
            self._put_json(self._series_path(row["symbol"]), {**row, "market": self.market})

        with ThreadPoolExecutor(STORAGE_WORKERS) as pool:
            list(pool.map(write, rows))
        return len(rows)

    def read_price_series(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Symbol -> series object, for the symbols that have one."""
        symbols = list(dict.fromkeys(symbols))
        with ThreadPoolExecutor(STORAGE_WORKERS) as pool:
            found = pool.map(lambda symbol: self._get_json(self._series_path(symbol)), symbols)
        return {symbol: row for symbol, row in zip(symbols, found) if row is not None}

    # -- snapshot payloads (Supabase Storage) --------------------------------
    #
    # Each snapshot row's complete source record, one gzip JSON object per
    # symbol in its run's folder. At ~20 KB a row it was nine-tenths of
    # screener_snapshot and a third of the free database for a single day
    # (Oct 2026), and only the stock page reads it, one symbol at a time.

    def _payload_folder(self, run_date: str | None = None) -> str:
        folder = f"snapshot-payload/{self.market}"
        return f"{folder}/{run_date}" if run_date else folder

    def _payload_path(self, run_date: str, symbol: str) -> str:
        return f"{self._payload_folder(run_date)}/{symbol}.json.gz"

    def upsert_snapshot_payloads(self, run_date: str, payloads: dict[str, dict[str, Any]]) -> int:
        """Write each symbol's payload as its own object; returns the count."""

        def write(item: tuple[str, dict[str, Any]]) -> None:
            symbol, payload = item
            self._put_json(self._payload_path(run_date, symbol), payload)

        with ThreadPoolExecutor(STORAGE_WORKERS) as pool:
            list(pool.map(write, payloads.items()))
        return len(payloads)

    def prune_snapshot_payloads(self) -> int:
        """Delete the payload folders of runs this market no longer holds.

        Swept against ``screener_runs`` rather than the runs a prune just
        removed, so a folder left behind by a failed publish -- whose
        reservation the compensation deleted -- goes on the next prune too.
        Returns the number of objects deleted.
        """
        runs = self._request(
            "GET", "screener_runs", params=self._scoped({"select": "run_date"})
        ) or []
        held = {str(row["run_date"]) for row in runs}
        removed = 0
        for run_date in self._objects.folders(self._payload_folder()):
            if run_date not in held:
                removed += self._objects.remove(self._objects.list(self._payload_folder(run_date)))
        return removed

    # -- financial statements -----------------------------------------------

    def _paged(self, path: str, params: dict[str, Any], page: int = 1000) -> list[dict[str, Any]]:
        """Read every row of a filtered query, past PostgREST's row cap."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            batch = self._request(
                "GET",
                path,
                params=self._scoped({**params, "limit": str(page), "offset": str(offset)}),
            ) or []
            rows.extend(batch)
            if len(batch) < page:
                return rows
            offset += page

    def latest_snapshot_symbols(self) -> list[str]:
        """Symbols in this market's newest published run, in rank order."""
        run = self.latest_completed_run()
        if not run:
            return []
        rows = self._paged(
            "screener_snapshot",
            {
                "select": "symbol",
                "run_date": f"eq.{run['run_date']}",
                "order": "investment_rank.asc.nullslast,symbol.asc",
            },
        )
        return [str(row["symbol"]) for row in rows if row.get("symbol")]

    def financial_statement_state(self) -> dict[str, dict[str, Any]]:
        """Per-symbol refresh state: when it was fetched, its latest quarter and whether it had data."""
        rows = self._paged(
            "financial_statements",
            {"select": "symbol,fetched_at,latest_quarter,has_data", "order": "symbol.asc"},
        )
        return {str(row["symbol"]): row for row in rows}

    def upsert_financial_statements(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = 50,
    ) -> int:
        """Upsert per-symbol statement payloads (a few KB each)."""
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "financial_statements?on_conflict=market,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    def financial_statement_rows(
        self, symbols: Iterable[str], chunk_size: int = 100
    ) -> list[dict[str, Any]]:
        """Whole stored rows for ``symbols``, the ones that have one."""
        rows: list[dict[str, Any]] = []
        for chunk in chunked(list(dict.fromkeys(symbols)), chunk_size):
            symbols_csv = ",".join(f'"{symbol}"' for symbol in chunk)
            rows += self._paged(
                "financial_statements",
                {
                    "select": (
                        "symbol,statements,has_data,currency,source,"
                        "latest_annual,latest_quarter,fetched_at"
                    ),
                    "symbol": f"in.({symbols_csv})",
                    "order": "symbol.asc",
                },
                page=200,
            )
        return rows

    # -- quarterly filings ----------------------------------------------------

    def quarterly_filing_state(self) -> dict[tuple[str, str, bool], dict[str, Any]]:
        """What is stored for each (symbol, quarter, basis), to tell what is new."""
        rows = self._paged(
            "quarterly_filings",
            {
                "select": "symbol,period_end,is_consolidated,seq_id,parser_version,broadcast_at",
                "order": "symbol.asc,period_end.asc,is_consolidated.asc",
            },
        )
        return {
            (str(row["symbol"]), str(row["period_end"])[:10], bool(row["is_consolidated"])): row
            for row in rows
        }

    def upsert_quarterly_filings(self, rows: list[dict[str, Any]], chunk_size: int = 100) -> int:
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "quarterly_filings?on_conflict=market,symbol,period_end,is_consolidated",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                retries=2,
            )
            written += len(chunk)
        return written

    def quarterly_filings(
        self, symbols: Iterable[str], chunk_size: int = 100
    ) -> dict[str, list[dict[str, Any]]]:
        """Symbol -> its stored filings, each with its parsed ``lines``."""
        found: dict[str, list[dict[str, Any]]] = {}
        for chunk in chunked(list(dict.fromkeys(symbols)), chunk_size):
            symbols_csv = ",".join(f'"{symbol}"' for symbol in chunk)
            for row in self._paged(
                "quarterly_filings",
                {
                    "select": "symbol,period_end,is_consolidated,filed_at,taxonomy,lines",
                    "symbol": f"in.({symbols_csv})",
                    "order": "symbol.asc,period_end.asc,is_consolidated.asc",
                },
            ):
                found.setdefault(str(row["symbol"]), []).append(row)
        return found

    def recent_filed_results(self, since: str) -> list[dict[str, Any]]:
        """Stored filings of quarters first announced at or after ``since``."""
        return self._paged(
            "quarterly_filings",
            {
                "select": (
                    "symbol,period_end,broadcast_at,"
                    "revenue:lines->revenue,net_profit:lines->net_profit"
                ),
                "broadcast_at": f"gte.{since}",
                "order": "broadcast_at.asc,symbol.asc",
            },
        )

    # -- shareholding ---------------------------------------------------------

    def shareholding_state(self) -> dict[tuple[str, str], dict[str, Any]]:
        """What is stored for each (symbol, quarter end), to tell what is new."""
        rows = self._paged(
            "shareholding_patterns",
            {
                "select": "symbol,period_end,record_id,parser_version",
                "order": "symbol.asc,period_end.asc",
            },
        )
        return {(str(row["symbol"]), str(row["period_end"])[:10]): row for row in rows}

    def upsert_shareholding_patterns(self, rows: list[dict[str, Any]], chunk_size: int = 100) -> int:
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "shareholding_patterns?on_conflict=market,symbol,period_end",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                retries=2,
            )
            written += len(chunk)
        return written

    def upsert_bulk_block_deals(self, rows: list[dict[str, Any]], chunk_size: int = 1000) -> int:
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "bulk_block_deals?on_conflict="
                "market,kind,deal_date,symbol,client_name,side,quantity,price",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                retries=2,
            )
            written += len(chunk)
        return written

    # -- market breadth ---------------------------------------------------

    def latest_snapshot_classification(self) -> dict[str, tuple[str | None, str | None]]:
        """Symbol -> (sector, industry) for this market's newest published run."""
        run = self.latest_completed_run()
        if not run:
            return {}
        rows = self._paged(
            "screener_snapshot",
            {
                "select": "symbol,sector,industry",
                "run_date": f"eq.{run['run_date']}",
                "order": "symbol.asc",
            },
        )
        return {
            str(row["symbol"]): (row.get("sector") or None, row.get("industry") or None)
            for row in rows
            if row.get("symbol")
        }

    def replace_market_breadth(self, rows: list[dict[str, Any]], chunk_size: int = 5) -> int:
        """Make this market's breadth rows exactly ``rows``.

        Upsert first, then delete the difference, as ``replace_new_listings``
        does. A row runs ~90 KB, so chunks are small, and each is retried: the
        US publish of 30 Sept 2026 died eight minutes in on one ~900 KB chunk
        whose upload timed out, leaving the page on the previous session.
        """
        written = 0
        # A merge-duplicates upsert does not run the column's default on a row
        # that exists, so without this updated_at stayed at its first write.
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "market_breadth?on_conflict=market,scope,name",
                retries=3,
                json=self._stamped([{**row, "updated_at": stamp} for row in chunk]),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        keep = {(row["scope"], row["name"]) for row in rows}
        stored = self._paged("market_breadth", {"select": "scope,name", "order": "scope,name"})
        for row in stored:
            if (row["scope"], row["name"]) in keep:
                continue
            self._request(
                "DELETE",
                "market_breadth",
                params=self._scoped({"scope": f"eq.{row['scope']}", "name": f"eq.{row['name']}"}),
                headers={"Prefer": "return=minimal"},
            )
        return written

    def replace_breadth_members(
        self,
        members: dict[str, list[str]],
        session: str,
        chunk_size: int = 1000,
    ) -> int:
        """Make this market's latest-session breadth lists exactly ``members``.

        Every written row is stamped with this call's time, and one DELETE then
        removes anything older. A stock that dropped out of a list since the
        last publish goes with it, and a failure between the two steps leaves
        yesterday's extras for a day rather than empty lists.
        """
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        rows = [
            {"metric": metric, "symbol": symbol, "session": session, "published_at": stamp}
            for metric, symbols in sorted(members.items())
            for symbol in symbols
        ]
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "market_breadth_members?on_conflict=market,metric,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        self._request(
            "DELETE",
            "market_breadth_members",
            params=self._scoped({"published_at": f"lt.{stamp}"}),
            headers={"Prefer": "return=minimal"},
        )
        return written

    def replace_breadth_levels(self, rows: list[dict[str, Any]], chunk_size: int = 1000) -> int:
        """Make this market's live-breadth levels exactly ``rows``.

        As ``replace_breadth_members``: every row is stamped with this call's
        time and one DELETE removes anything older, so a stock that left the
        universe goes with it, and a failure between the steps leaves
        yesterday's levels -- which ``live_breadth`` ignores once they are
        not the newest -- rather than none.
        """
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        written = 0
        for chunk in chunked([{**row, "published_at": stamp} for row in rows], chunk_size):
            self._request(
                "POST",
                "market_breadth_levels?on_conflict=market,symbol",
                retries=3,
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        self._request(
            "DELETE",
            "market_breadth_levels",
            params=self._scoped({"published_at": f"lt.{stamp}"}),
            headers={"Prefer": "return=minimal"},
        )
        return written

    # -- new listings -----------------------------------------------------

    def new_listing_symbols(self) -> list[str]:
        """Recent listings not yet rated, newest listing first."""
        rows = self._paged(
            "new_listings", {"select": "symbol", "order": "listed_on.desc,symbol.asc"}
        )
        return [str(row["symbol"]) for row in rows if row.get("symbol")]

    def replace_new_listings(self, rows: list[dict[str, Any]], chunk_size: int = 200) -> int:
        """Make this market's new_listings exactly ``rows``.

        Upsert first, then delete the difference, so a listing that entered the
        scored universe since the last run leaves the table -- and so a failure
        between the two steps leaves stale extras rather than an empty table.
        """
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "new_listings?on_conflict=market,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        keep = {str(row["symbol"]) for row in rows}
        obsolete = sorted(set(self.new_listing_symbols()) - keep)
        for chunk in chunked(obsolete, 100):
            symbols_csv = ",".join(f'"{symbol}"' for symbol in chunk)
            self._request(
                "DELETE",
                "new_listings",
                params=self._scoped({"symbol": f"in.({symbols_csv})"}),
                headers={"Prefer": "return=minimal"},
            )
        return written

    # -- live quotes ------------------------------------------------------

    def upsert_live_quotes(self, rows: list[dict[str, Any]], chunk_size: int = 1000) -> int:
        """Overwrite this market's latest quote for each row's symbol.

        One row per symbol, replaced in place every run, so the table stays
        the size of the universe however long it runs. Retried: an upsert on
        the primary key is idempotent.
        """
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "live_quotes?on_conflict=market,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                retries=2,
            )
            written += len(chunk)
        return written

    def prune_live_quotes(self, before: str) -> None:
        """Drop quotes no run has refreshed since ``before`` (a delisted symbol)."""
        self._request(
            "DELETE",
            "live_quotes",
            params=self._scoped({"fetched_at": f"lt.{before}"}),
            headers={"Prefer": "return=minimal"},
        )

    def index_members_refreshed_at(self) -> str | None:
        """When this market's constituent lists were last replaced, or None."""
        rows = self._request(
            "GET",
            "index_members",
            params=self._scoped(
                {"select": "refreshed_at", "order": "refreshed_at.desc", "limit": "1"}
            ),
        ) or []
        return rows[0]["refreshed_at"] if rows else None

    def index_member_symbols(self) -> list[str]:
        """Every symbol in any of this market's tracked indices."""
        rows = self._paged("index_members", {"select": "symbol", "order": "symbol.asc"})
        return sorted({str(row["symbol"]) for row in rows if row.get("symbol")})

    def replace_index_members(self, rows: list[dict[str, Any]], chunk_size: int = 1000) -> int:
        """Make this market's constituent lists exactly ``rows``.

        Stamped and upserted, then everything older deleted -- as for the
        breadth lists -- so a stock that left an index leaves its list, and a
        failure between the two steps leaves yesterday's extras, never an
        empty list.
        """
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        stamped = [{**row, "refreshed_at": stamp} for row in rows]
        written = 0
        for chunk in chunked(stamped, chunk_size):
            self._request(
                "POST",
                "index_members?on_conflict=market,index_name,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        self._request(
            "DELETE",
            "index_members",
            params=self._scoped({"refreshed_at": f"lt.{stamp}"}),
            headers={"Prefer": "return=minimal"},
        )
        return written

    # -- notifications ----------------------------------------------------

    def snapshot_companies(self) -> dict[str, str | None]:
        """Symbol -> company name for this market's newest published run."""
        run = self.latest_completed_run()
        if not run:
            return {}
        rows = self._paged(
            "screener_snapshot",
            {
                "select": "symbol,company",
                "run_date": f"eq.{run['run_date']}",
                "order": "symbol.asc",
            },
        )
        return {str(row["symbol"]): row.get("company") for row in rows if row.get("symbol")}

    def recorded_event_keys(self, kind: str) -> dict[str, str]:
        """Each symbol's latest recorded event key of ``kind``, baselines included."""
        rows = self._paged(
            "market_events",
            {"select": "symbol,event_key", "kind": f"eq.{kind}", "order": "id.asc"},
        )
        latest: dict[str, str] = {}
        for row in rows:
            symbol, key = str(row["symbol"]), str(row["event_key"])
            if key > latest.get(symbol, ""):
                latest[symbol] = key
        return latest

    def recent_transcripts(self, since: str) -> list[dict[str, Any]]:
        """Call transcripts stored at or after ``since`` (an ISO timestamp)."""
        return self._paged(
            "transcripts",
            {
                "select": "symbol,quarter,call_date,created_at",
                "created_at": f"gte.{since}",
                "order": "created_at.asc",
            },
        )

    # -- concall feed ----------------------------------------------------------

    def calls_since(self, since: str) -> list[dict[str, Any]]:
        """Stored calls held on or after ``since``, with their scores and no text."""
        return self._paged(
            "transcripts",
            {
                "select": (
                    "id,symbol,quarter,call_date,"
                    "transcript_documents(extraction_method),"
                    "transcript_sentiments(overall_score,guidance_direction,created_at),"
                    "transcript_outlooks(outlook_score,verified_fields,extraction,analysis_version,created_at)"
                ),
                "call_date": f"gte.{since}",
                "order": "call_date.desc,id.asc",
            },
            page=200,
        )

    def concall_call_dates(self) -> dict[tuple[str, str], str]:
        """The call date each feed row carries, keyed by (symbol, quarter)."""
        rows = self._paged(
            "concall_feed", {"select": "symbol,quarter,call_date", "order": "symbol.asc,quarter.asc"}
        )
        return {(str(row["symbol"]), str(row["quarter"])[:10]): str(row["call_date"])[:10] for row in rows}

    def replace_concall_feed(self, rows: list[dict[str, Any]], since: str, chunk_size: int = 200) -> int:
        """Write the feed's rows and drop calls older than ``since``."""
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "concall_feed?on_conflict=market,symbol,quarter",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                retries=2,
            )
        self._request(
            "DELETE",
            "concall_feed",
            params=self._scoped({"call_date": f"lt.{since}"}),
            headers={"Prefer": "return=minimal"},
            retries=2,
        )
        return len(rows)

    def insert_market_events(
        self, rows: list[dict[str, Any]], chunk_size: int = 200
    ) -> int:
        """Record events not already recorded; returns how many were new.

        Idempotent on (market, kind, symbol, event_key): a worker that sees the
        same filing on its next run writes nothing, and the first sighting
        keeps its ``detected_at``.
        """
        written = 0
        for chunk in chunked(rows, chunk_size):
            inserted = self._request(
                "POST",
                "market_events?on_conflict=market,kind,symbol,event_key&select=id",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
                retries=2,
            )
            written += len(inserted or [])
        return written

    # -- upcoming events -------------------------------------------------------

    def upcoming_events(self) -> dict[str, dict[str, Any]]:
        """Every stored upcoming-events row, by symbol."""
        rows = self._paged("upcoming_events", {"select": "*", "order": "symbol.asc"})
        return {str(row["symbol"]): row for row in rows}

    def upsert_upcoming_events(self, rows: list[dict[str, Any]], chunk_size: int = 200) -> int:
        """Write whole rows, replacing a stock's earlier one."""
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "upcoming_events?on_conflict=market,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                retries=2,
            )
        return len(rows)

    def prune_market_events(self, before: str) -> None:
        """Drop events first seen before ``before`` (an ISO timestamp)."""
        self._request(
            "DELETE",
            "market_events",
            params=self._scoped({"detected_at": f"lt.{before}"}),
            headers={"Prefer": "return=minimal"},
        )

    def delete_stale_snapshot_rows(self, run_date: str, symbols: Iterable[str]) -> None:
        """Remove rows for a re-ingested date that the new run no longer covers.

        A merge-only upsert cannot express a shrinking universe: if a symbol is
        delisted between two loads of the same date, its old row would survive
        and the dashboard would keep showing a stock the run did not evaluate.
        """
        keep = sorted({str(symbol) for symbol in symbols if symbol})
        if not keep:
            return
        # PostgREST puts filters in the URL, so an ~2,400-symbol `not.in` list
        # would exceed practical URL limits. Read the stored symbols back and
        # delete only the difference, which is empty on the normal path.
        stored = self._request(
            "GET",
            "screener_snapshot",
            params=self._scoped({"select": "symbol", "run_date": f"eq.{run_date}"}),
        ) or []
        obsolete = sorted({row["symbol"] for row in stored} - set(keep))
        for chunk in chunked([{"symbol": s} for s in obsolete], 100):
            symbols_csv = ",".join(f'"{row["symbol"]}"' for row in chunk)
            self._request(
                "DELETE",
                "screener_snapshot",
                params=self._scoped({
                    "run_date": f"eq.{run_date}",
                    "symbol": f"in.({symbols_csv})",
                }),
                headers={"Prefer": "return=minimal"},
            )

    # -- history ------------------------------------------------------------

    def upsert_history_rows(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = 500,
    ) -> int:
        written = 0
        # History rows are narrow, so they chunk larger than snapshot rows.
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "screener_history?on_conflict=market,observed_on,symbol",
                json=self._stamped(chunk),
                retries=2,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    def upsert_estimate_rows(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = 500,
    ) -> int:
        """Record analyst-estimate observations, first sighting wins.

        Keyed on the vendor fetch, and ignore-duplicates rather than merge: a
        cached fetch reaches several daily runs, and the row must keep the
        run date it was first published under.
        """
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "estimate_history?on_conflict=market,symbol,fetched_at",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    def upsert_simulated_rankings(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = 1000,
    ) -> int:
        """Backtest rankings for the Returns page; written only by the backfill tool."""
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "simulated_rankings?on_conflict=market,observed_on,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    def delete_simulated_rankings(self, before: str) -> None:
        """Drop this market's backtest rankings dated before ``before``.

        A rebuild under different weights ranks different symbols, and the
        upsert key includes the symbol, so writing the new top 50 over the old
        would leave every name that dropped out sitting beside its replacement.
        """
        self._request(
            "DELETE",
            "simulated_rankings",
            params=self._scoped({"observed_on": f"lt.{before}"}),
            headers={"Prefer": "return=minimal"},
            retries=2,
        )

    def delete_simulated_states(self, before: str) -> None:
        """Drop this market's weekly hold-rule sets dated before ``before``.

        A rebuild that ends on a different day signals on different dates, so a
        week the old build had and the new one does not would otherwise stay.
        """
        self._request(
            "DELETE",
            "simulated_states",
            params=self._scoped({"observed_on": f"lt.{before}"}),
            headers={"Prefer": "return=minimal"},
            retries=2,
        )

    def upsert_simulated_states(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = 50,
    ) -> int:
        """Weekly hold-rule sets for the Returns page; a few KB a row, so small chunks."""
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "simulated_states?on_conflict=market,observed_on",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    def upsert_universe_index(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = 1000,
    ) -> int:
        """Daily equal-weight universe returns, one row per session."""
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "universe_index?on_conflict=market,observed_on",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    def valuation_basis_periods(
        self, symbols: Iterable[str], chunk_size: int = 100
    ) -> dict[str, str | None]:
        """Symbol -> the quarter its stored basis runs to (None: unknown)."""
        found: dict[str, str | None] = {}
        for chunk in chunked(list(dict.fromkeys(symbols)), chunk_size):
            symbols_csv = ",".join(f'"{symbol}"' for symbol in chunk)
            for row in self._paged(
                "valuation_basis",
                {"select": "symbol,period_end", "symbol": f"in.({symbols_csv})"},
            ):
                found[str(row["symbol"])] = row.get("period_end")
        return found

    def upsert_valuation_basis(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = 1000,
    ) -> int:
        """Each symbol's valuation basis, replacing the one it had.

        One row per symbol; see storage/valuation_basis_schema.sql.
        """
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "valuation_basis?on_conflict=market,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                retries=2,
            )
            written += len(chunk)
        return written

    # -- retention ----------------------------------------------------------

    def prune_snapshots(self, keep_runs: int = 2, batch_size: int = PRUNE_BATCH_SIZE) -> int:
        """Drop all but this market's newest ``keep_runs`` snapshots.

        The snapshot rows of each doomed run are deleted first, a batch at a
        time, and only then the run itself through ``prune_screener_snapshots``.
        Left to the function alone, deleting a run cascades to its ~2,300
        snapshot rows of ~27 KB each in one statement, which outran the
        database's statement timeout on every publish (October 2026) and left
        three runs per market behind. With the rows gone first the cascade is
        empty and the function's delete is instant.
        """
        runs = self._request(
            "GET",
            "screener_runs",
            params=self._scoped({"select": "run_date", "order": "run_date.desc"}),
        ) or []
        doomed = [str(row["run_date"]) for row in runs[max(1, int(keep_runs)) :]]
        for run_date in doomed:
            self._delete_snapshot_rows(run_date, batch_size)
        removed = self._request(
            "POST",
            "rpc/prune_screener_snapshots",
            json={"keep_runs": int(keep_runs), "p_market": self.market},
        )
        return int(removed or 0)

    def _delete_snapshot_rows(self, run_date: str, batch_size: int) -> int:
        """Delete one run's snapshot rows, ``batch_size`` symbols per statement."""
        deleted = 0
        previous: list[str] = []
        while True:
            rows = self._request(
                "GET",
                "screener_snapshot",
                params=self._scoped(
                    {
                        "select": "symbol",
                        "run_date": f"eq.{run_date}",
                        "order": "symbol.asc",
                        "limit": str(batch_size),
                    }
                ),
            ) or []
            symbols = [str(row["symbol"]) for row in rows if row.get("symbol")]
            if not symbols:
                return deleted
            if symbols == previous:
                # The last delete removed nothing; looping would never end.
                raise RuntimeError(f"Snapshot rows of {self.market} {run_date} were not deleted")
            previous = symbols
            symbols_csv = ",".join(f'"{symbol}"' for symbol in symbols)
            self._request(
                "DELETE",
                "screener_snapshot",
                params=self._scoped(
                    {"run_date": f"eq.{run_date}", "symbol": f"in.({symbols_csv})"}
                ),
                headers={"Prefer": "return=minimal"},
                retries=2,
            )
            deleted += len(symbols)
            logger.info("Pruned %d snapshot rows of %s %s", deleted, self.market, run_date)

    # -- access control -----------------------------------------------------

    def grant_access(self, email: str, role: str = "viewer") -> dict[str, Any]:
        rows = self._request(
            "POST",
            "dashboard_allowlist?on_conflict=email",
            json={"email": email.strip().lower(), "role": role},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        return rows[0] if rows else {}

    def revoke_access(self, email: str) -> None:
        self._request(
            "DELETE",
            "dashboard_allowlist",
            params={"email": f"eq.{email.strip().lower()}"},
            headers={"Prefer": "return=minimal"},
        )

    def list_access(self) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "dashboard_allowlist",
            params={"select": "*", "order": "email.asc"},
        ) or []
