"""PostgREST adapter for the dashboard read model.

Kept separate from `SupabaseRepository`, which owns private transcript data.
The two touch disjoint tables and have different failure expectations: a
transcript write loss is a research-evidence loss, while a dashboard write loss
only means the site serves the previous run behind a staleness banner.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Iterator

import requests


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
    def __init__(
        self,
        url: str,
        service_role_key: str,
        timeout_seconds: int = 60,
    ):
        if not url or not service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self.base_url = f"{url.rstrip('/')}/rest/v1"
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }

    @classmethod
    def from_environment(cls) -> "DashboardRepository":
        return cls(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            int(os.getenv("SUPABASE_TIMEOUT_SECONDS", "60")),
        )

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
            "screener_runs?on_conflict=run_date",
            json=run,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        return rows[0] if rows else {}

    def latest_run(self) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "screener_runs",
            params={"select": "*", "order": "run_date.desc", "limit": "1"},
        )
        return rows[0] if rows else None

    def latest_completed_run(self) -> dict[str, Any] | None:
        """Return the newest published run, ignoring in-flight reservations."""
        rows = self._request(
            "GET",
            "screener_runs",
            params={
                "select": "*",
                "row_count": "gt.0",
                "order": "run_date.desc",
                "limit": "1",
            },
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
                "screener_snapshot?on_conflict=run_date,symbol",
                json=chunk,
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
            params: dict[str, Any] = {
                # `payload` is NOT NULL. The domain update uses an upsert so it
                # can batch distinct symbols; carrying the existing payload
                # satisfies the insert side without changing drill-down data.
                "select": "symbol,company,logo_domain,payload",
                "run_date": f"eq.{run_date}",
                "order": "symbol.asc",
                "limit": str(page_size),
                "offset": str(offset),
            }
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
                "screener_snapshot?on_conflict=run_date,symbol",
                json=chunk,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    def upsert_price_calendar(self, calendar: dict[str, Any]) -> None:
        """Replace the single shared trading calendar row."""
        self._request(
            "POST",
            "price_calendar?on_conflict=id",
            json=[{**calendar, "id": 1}],
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

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
                "price_series?on_conflict=symbol",
                json=chunk,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
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
            params={"select": "symbol", "run_date": f"eq.{run_date}"},
        ) or []
        obsolete = sorted({row["symbol"] for row in stored} - set(keep))
        for chunk in chunked([{"symbol": s} for s in obsolete], 100):
            symbols_csv = ",".join(f'"{row["symbol"]}"' for row in chunk)
            self._request(
                "DELETE",
                "screener_snapshot",
                params={
                    "run_date": f"eq.{run_date}",
                    "symbol": f"in.({symbols_csv})",
                },
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
                "screener_history?on_conflict=observed_on,symbol",
                json=chunk,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            written += len(chunk)
        return written

    # -- retention ----------------------------------------------------------

    def prune_snapshots(self, keep_runs: int = 2) -> int:
        removed = self._request(
            "POST",
            "rpc/prune_screener_snapshots",
            json={"keep_runs": int(keep_runs)},
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
