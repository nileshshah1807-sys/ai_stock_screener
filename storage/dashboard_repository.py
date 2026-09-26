"""PostgREST adapter for the dashboard read model.

Kept separate from `SupabaseRepository`, which owns private transcript data.
The two touch disjoint tables and have different failure expectations: a
transcript write loss is a research-evidence loss, while a dashboard write loss
only means the site serves the previous run behind a staleness banner.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

import requests

from screener.markets import DEFAULT_MARKET
from screener.markets import resolve as resolve_market

# The snapshot row carries the full source record in `payload`, so a batch of
# rows is large in bytes even though the row count is modest. Chunks are sized
# for request-body limits rather than row count.
DEFAULT_CHUNK_SIZE = 200

# A price-series row carries three encoded arrays and runs 20-30 KB, so the
# snapshot chunk size would produce a ~6 MB request body.
PRICE_SERIES_CHUNK_SIZE = 25


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

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        response = self.session.request(
            method,
            f"{self.base_url}/{path.lstrip('/')}",
            headers=headers,
            timeout=self.timeout_seconds,
            **kwargs,
        )
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
                # `payload` is NOT NULL. The domain update uses an upsert so it
                # can batch distinct symbols; carrying the existing payload
                # satisfies the insert side without changing drill-down data.
                "select": "symbol,company,logo_domain,payload",
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
                "payload": row["payload"],
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

        Deliberately excludes `payload`: unlike the logo backfill, the session
        change is written with PATCH rather than upsert, so there is no NOT NULL
        column to satisfy and no reason to move ~12 MB of payload over the wire
        and back to set one numeric field.
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
        is the deliberate trade here. It touches exactly the columns named and
        cannot rewrite `payload`, where an upsert of 2,370 rows would put the
        entire drill-down record of the run in the blast radius to set one
        nullable number.
        """
        self._request(
            "PATCH",
            "screener_snapshot",
            params=self._scoped({"run_date": f"eq.{run_date}", "symbol": f"eq.{symbol}"}),
            json=values,
            headers={"Prefer": "return=minimal"},
        )

    def upsert_price_calendar(self, calendar: dict[str, Any]) -> None:
        """Replace this market's trading calendar row.

        One row per market rather than one row overall: NSE and NYSE sessions
        do not line up, so a shared calendar would misindex every US series.
        """
        self._request(
            "POST",
            "price_calendar?on_conflict=market",
            json=[{**calendar, "market": self.market}],
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    def published_calendar_size(self) -> int | None:
        """Session count of the live calendar, or None if none is published."""
        rows = self._request(
            "GET",
            "price_calendar",
            params=self._scoped({"select": "session_count"}),
        )
        if not rows:
            return None
        return int(rows[0].get("session_count") or 0) or None

    def upsert_price_series(
        self,
        rows: list[dict[str, Any]],
        chunk_size: int = PRICE_SERIES_CHUNK_SIZE,
    ) -> int:
        """Upsert encoded per-symbol series.

        Chunked far smaller than the snapshot writer: a snapshot row is a few
        hundred bytes, while a series row carries three encoded arrays and runs
        20-30 KB, so 200 of them would be a ~6 MB request body.
        """
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "price_series?on_conflict=market,symbol",
                json=self._stamped(chunk),
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

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
        """Per-symbol refresh state: when it was fetched and its latest quarter."""
        rows = self._paged(
            "financial_statements",
            {"select": "symbol,fetched_at,latest_quarter", "order": "symbol.asc"},
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

    def replace_market_breadth(self, rows: list[dict[str, Any]], chunk_size: int = 10) -> int:
        """Make this market's breadth rows exactly ``rows``.

        Upsert first, then delete the difference, as ``replace_new_listings``
        does. A row runs ~90 KB, so chunks are small.
        """
        written = 0
        for chunk in chunked(rows, chunk_size):
            self._request(
                "POST",
                "market_breadth?on_conflict=market,scope,name",
                json=self._stamped(chunk),
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

    # -- retention ----------------------------------------------------------

    def prune_snapshots(self, keep_runs: int = 2) -> int:
        removed = self._request(
            "POST",
            "rpc/prune_screener_snapshots",
            json={"keep_runs": int(keep_runs), "p_market": self.market},
        )
        return int(removed or 0)

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
