"""Supabase Storage objects in the private ``market-data`` bucket.

Bulky, file-shaped data lives here rather than in Postgres: the free database
stops accepting writes at 500 MB, while Storage has its own 1 GB under the same
auth (storage/market_data_storage.sql). Chart price series, each snapshot
row's complete source record and archived earnings-call text all use it.

Transfers are one object per request and run on thread pools, so each call uses
a fresh request rather than a shared ``requests.Session``, which is not
thread-safe.
"""

from __future__ import annotations

import gzip
import logging
import time
from collections.abc import Iterable
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

MARKET_DATA_BUCKET = "market-data"

#: A transfer that hits a connection error or timeout is re-sent this many
#: times, pausing 5, 10, then 20 seconds. Both operations are idempotent -- a
#: put is an upsert of the whole object -- and a chart publish is ~3,000 of
#: them, so without this one slow response fails the lot (NSE, 30 Sept 2026).
TRANSFER_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

#: Entries per list request and paths per delete request; Storage caps both.
LIST_PAGE_SIZE = 1000
REMOVE_BATCH_SIZE = 1000


class ObjectStore:
    def __init__(self, url: str, service_role_key: str, timeout_seconds: int = 60,
                 bucket: str = MARKET_DATA_BUCKET, read_only: bool = False):
        self.base_url = f"{url.rstrip('/')}/storage/v1/object/{bucket}"
        self.list_url = f"{url.rstrip('/')}/storage/v1/object/list/{bucket}"
        self.timeout_seconds = timeout_seconds
        self.read_only = read_only
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{quote(path, safe='/')}"

    def _send(self, method: str, path: str, *, url: str | None = None, **kwargs) -> requests.Response:
        for attempt in range(TRANSFER_RETRIES + 1):
            try:
                return requests.request(
                    method, url or self._url(path), timeout=self.timeout_seconds, **kwargs
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == TRANSFER_RETRIES:
                    raise
                pause = RETRY_BACKOFF_SECONDS * 2**attempt
                logger.warning(
                    "%s storage:%s failed (%s); retry %d of %d in %ds",
                    method, path, exc, attempt + 1, TRANSFER_RETRIES, pause,
                )
                time.sleep(pause)
        raise AssertionError("unreachable")

    def put(self, path: str, body: bytes, content_type: str = "application/gzip") -> None:
        """Create or replace one object."""
        if self.read_only:
            raise PermissionError(f"storage write to {path} blocked: this client is read-only")
        response = self._send(
            "POST",
            path,
            headers={**self.headers, "Content-Type": content_type, "x-upsert": "true"},
            data=body,
        )
        _raise_with_detail(response, "POST", path)

    def get(self, path: str) -> bytes | None:
        """One object's bytes, or None when it does not exist."""
        response = self._send("GET", path, headers=self.headers)
        # Storage answers a missing object with 400 or 404 and a not_found body.
        if response.status_code in (400, 404) and "not_found" in response.text.lower().replace(" ", "_"):
            return None
        _raise_with_detail(response, "GET", path)
        return response.content

    def _entries(self, prefix: str) -> list[dict]:
        """Every entry directly under the folder ``prefix``, page by page."""
        entries: list[dict] = []
        while True:
            response = self._send(
                "POST",
                prefix,
                url=self.list_url,
                headers=self.headers,
                json={"prefix": prefix, "limit": LIST_PAGE_SIZE, "offset": len(entries)},
            )
            _raise_with_detail(response, "LIST", prefix)
            page = response.json() or []
            entries.extend(page)
            if len(page) < LIST_PAGE_SIZE:
                return entries

    def list(self, prefix: str) -> list[str]:
        """Paths of the objects directly under the folder ``prefix``."""
        # Storage lists a folder as an entry without an id.
        return [f"{prefix}/{entry['name']}" for entry in self._entries(prefix) if entry.get("id")]

    def folders(self, prefix: str) -> list[str]:
        """Names of the folders directly under the folder ``prefix``."""
        return [entry["name"] for entry in self._entries(prefix) if not entry.get("id")]

    def remove(self, paths: Iterable[str]) -> int:
        """Delete objects by path; returns how many were asked for."""
        paths = list(paths)
        if paths and self.read_only:
            raise PermissionError(f"storage delete of {paths[0]} blocked: this client is read-only")
        for start in range(0, len(paths), REMOVE_BATCH_SIZE):
            batch = paths[start : start + REMOVE_BATCH_SIZE]
            response = self._send(
                "DELETE", batch[0], url=self.base_url, headers=self.headers, json={"prefixes": batch}
            )
            _raise_with_detail(response, "DELETE", batch[0])
        return len(paths)

    def put_gzip_text(self, path: str, text: str) -> None:
        # mtime=0 keeps identical content byte-identical across writes.
        self.put(path, gzip.compress(text.encode("utf-8"), mtime=0))

    def get_gzip_text(self, path: str) -> str | None:
        body = self.get(path)
        return None if body is None else gzip.decompress(body).decode("utf-8")


def _raise_with_detail(response: requests.Response, method: str, path: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise requests.HTTPError(
            f"{exc} | {method} storage:{path} | {(response.text or '').strip()[:400]}",
            response=response,
        ) from exc
