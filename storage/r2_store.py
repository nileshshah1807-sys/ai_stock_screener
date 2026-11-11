"""Cloudflare R2 behind the same six methods as ``ObjectStore``.

R2 speaks the S3 protocol, so this signs plain ``requests`` calls with AWS
Signature V4 (stdlib ``hashlib``/``hmac``) rather than lock ``boto3`` and its
install weight into every runner. Keys are the Supabase bucket's keys, unchanged.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from urllib.parse import quote
from xml.sax.saxutils import escape

import requests

from storage.object_store import REMOVE_BATCH_SIZE, GzipText, _raise_with_detail, send_with_retries

logger = logging.getLogger(__name__)

REGION = "auto"  # R2's only region name
LIST_PAGE_SIZE = 1000


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def encode_query(params: dict[str, str]) -> str:
    """Query string in SigV4's canonical form: sorted, every byte but unreserved escaped."""
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params.items()))


def sigv4_signature(method: str, uri: str, query: str, headers: dict[str, str], payload_hash: str,
                    amz_date: str, region: str, secret_key: str, service: str = "s3") -> tuple[str, str]:
    """``(signature, signed_headers)`` for a request; ``headers`` must hold ``host``."""
    names = sorted(name.lower() for name in headers)
    lowered = {name.lower(): " ".join(value.split()) for name, value in headers.items()}
    canonical = "\n".join([
        method, uri, query,
        "".join(f"{name}:{lowered[name]}\n" for name in names),
        ";".join(names), payload_hash,
    ])
    day = amz_date[:8]
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, sha256_hex(canonical.encode("utf-8"))])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode("utf-8"), day), region), service), "aws4_request")
    return hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest(), ";".join(names)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class R2Store(GzipText):
    def __init__(self, account_id: str, bucket: str, access_key_id: str, secret_access_key: str,
                 timeout_seconds: int = 60, read_only: bool = False):
        self.host = f"{account_id}.r2.cloudflarestorage.com"
        self.bucket = bucket
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.timeout_seconds = timeout_seconds
        self.read_only = read_only

    def _request(self, method: str, key: str, *, params: dict[str, str] | None = None, body: bytes = b"",
                 headers: dict[str, str] | None = None) -> requests.Response:
        # Path-style: /bucket/key, each segment escaped once (S3 does not double-encode).
        uri = f"/{self.bucket}/{quote(key, safe='/')}" if key else f"/{self.bucket}"
        query = encode_query(params or {})
        amz_date = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        payload_hash = sha256_hex(body)
        signed = {**(headers or {}), "host": self.host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        signature, signed_names = sigv4_signature(
            method, uri, query, signed, payload_hash, amz_date, REGION, self.secret_access_key
        )
        signed["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{amz_date[:8]}/{REGION}/s3/aws4_request,"
            f"SignedHeaders={signed_names},Signature={signature}"
        )
        url = f"https://{self.host}{uri}" + (f"?{query}" if query else "")
        return send_with_retries(method, key, url, self.timeout_seconds, headers=signed, data=body)

    def put(self, path: str, body: bytes, content_type: str = "application/gzip") -> None:
        """Create or replace one object."""
        if self.read_only:
            raise PermissionError(f"storage write to {path} blocked: this client is read-only")
        _raise_with_detail(self._request("PUT", path, body=body, headers={"content-type": content_type}), "PUT", path)

    def get(self, path: str) -> bytes | None:
        """One object's bytes, or None when it does not exist."""
        response = self._request("GET", path)
        if response.status_code == 404:
            return None
        _raise_with_detail(response, "GET", path)
        return response.content

    def _page(self, prefix: str, delimiter: str | None) -> tuple[list[tuple[str, int]], list[str]]:
        """Every ``(key, size)`` and common prefix under the folder, page by page."""
        objects: list[tuple[str, int]] = []
        folders: list[str] = []
        token = ""
        while True:
            params = {"list-type": "2", "prefix": f"{prefix}/" if prefix else "", "max-keys": str(LIST_PAGE_SIZE)}
            if delimiter:
                params["delimiter"] = delimiter
            if token:
                params["continuation-token"] = token
            response = self._request("GET", "", params=params)
            _raise_with_detail(response, "LIST", prefix)
            root = ET.fromstring(response.content)
            token = ""
            for node in root:
                tag = _local(node.tag)
                fields = {_local(child.tag): child.text or "" for child in node}
                if tag == "Contents" and not fields["Key"].endswith("/"):
                    objects.append((fields["Key"], int(fields.get("Size", 0))))
                elif tag == "CommonPrefixes":
                    folders.append(fields["Prefix"])
                elif tag == "NextContinuationToken":
                    token = node.text or ""
            if not token:
                return objects, folders

    def list(self, prefix: str) -> list[str]:
        """Keys of the objects directly under the folder ``prefix``."""
        return [key for key, _ in self._page(prefix, "/")[0]]

    def sizes(self, prefix: str) -> dict[str, int]:
        """Key -> bytes of every object under ``prefix``, at any depth."""
        return dict(self._page(prefix, None)[0])

    def folders(self, prefix: str) -> list[str]:
        """Names of the folders directly under the folder ``prefix``."""
        return [folder.rstrip("/").rsplit("/", 1)[-1] for folder in self._page(prefix, "/")[1]]

    def remove(self, paths: Iterable[str]) -> int:
        """Delete objects by path; returns how many were asked for."""
        paths = list(paths)
        if paths and self.read_only:
            raise PermissionError(f"storage delete of {paths[0]} blocked: this client is read-only")
        for start in range(0, len(paths), REMOVE_BATCH_SIZE):
            batch = paths[start : start + REMOVE_BATCH_SIZE]
            keys = "".join(f"<Object><Key>{escape(key)}</Key></Object>" for key in batch)
            body = f"<Delete><Quiet>true</Quiet>{keys}</Delete>".encode()
            md5 = base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()
            response = self._request("POST", "", params={"delete": ""}, body=body, headers={"content-md5": md5})
            _raise_with_detail(response, "DELETE", batch[0])
            # A 200 can still carry per-key failures.
            errors = [n for n in ET.fromstring(response.content) if _local(n.tag) == "Error"]
            if errors:
                raise requests.HTTPError(f"R2 refused {len(errors)} of {len(batch)} deletes near {batch[0]}")
        return len(paths)
