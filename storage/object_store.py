"""Supabase Storage objects in the private ``market-data`` bucket.

Bulky, file-shaped data lives here rather than in Postgres: the free database
stops accepting writes at 500 MB, while Storage has its own 1 GB under the same
auth (storage/market_data_storage.sql). Chart price series and archived
earnings-call text both use it.

Transfers are one object per request and run on thread pools, so each call uses
a fresh request rather than a shared ``requests.Session``, which is not
thread-safe.
"""

from __future__ import annotations

import gzip
from urllib.parse import quote

import requests

MARKET_DATA_BUCKET = "market-data"


class ObjectStore:
    def __init__(self, url: str, service_role_key: str, timeout_seconds: int = 60,
                 bucket: str = MARKET_DATA_BUCKET, read_only: bool = False):
        self.base_url = f"{url.rstrip('/')}/storage/v1/object/{bucket}"
        self.timeout_seconds = timeout_seconds
        self.read_only = read_only
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{quote(path, safe='/')}"

    def put(self, path: str, body: bytes, content_type: str = "application/gzip") -> None:
        """Create or replace one object."""
        if self.read_only:
            raise PermissionError(f"storage write to {path} blocked: this client is read-only")
        response = requests.post(
            self._url(path),
            headers={**self.headers, "Content-Type": content_type, "x-upsert": "true"},
            data=body,
            timeout=self.timeout_seconds,
        )
        _raise_with_detail(response, "POST", path)

    def get(self, path: str) -> bytes | None:
        """One object's bytes, or None when it does not exist."""
        response = requests.get(self._url(path), headers=self.headers, timeout=self.timeout_seconds)
        # Storage answers a missing object with 400 or 404 and a not_found body.
        if response.status_code in (400, 404) and "not_found" in response.text.lower().replace(" ", "_"):
            return None
        _raise_with_detail(response, "GET", path)
        return response.content

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
