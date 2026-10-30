"""Read-only look at the private ``market-data`` Storage bucket, as the audit account.

Signs in as the dashboard viewer (``creed.audit@example.com``) with the anon
key and reads through the bucket's own select policy
(``storage/market_data_storage.sql``): no service-role key, and Storage
refuses a write from a viewer. Only ``ls`` and ``cat`` exist.

    md-secret run CREED_DASHBOARD_PASSWORD NEXT_PUBLIC_SUPABASE_ANON_KEY -- \\
        env NEXT_PUBLIC_SUPABASE_URL=<project url> \\
        python -m tools.storage_peek ls price-series/NSE
    ... python -m tools.storage_peek cat <path>.json.gz     # gunzipped to stdout

``ls`` prints the objects and folders directly under a prefix.
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys

import requests

from storage.object_store import ObjectStore


def sign_in(url: str, anon_key: str, email: str, password: str) -> str:
    """The viewer's access token."""
    response = requests.post(
        f"{url.rstrip('/')}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": anon_key},
        json={"email": email, "password": password},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def viewer_store(url: str, anon_key: str, token: str) -> ObjectStore:
    store = ObjectStore(url, anon_key, read_only=True)
    store.headers = {"apikey": anon_key, "Authorization": f"Bearer {token}"}
    return store


def readable(body: bytes) -> bytes:
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["ls", "cat"])
    parser.add_argument("path", help="a folder prefix (ls) or an object path (cat)")
    args = parser.parse_args(argv)
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ["SUPABASE_URL"]
    anon_key = os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
    token = sign_in(
        url,
        anon_key,
        os.environ.get("CREED_DASHBOARD_EMAIL", "creed.audit@example.com"),
        os.environ["CREED_DASHBOARD_PASSWORD"],
    )
    store = viewer_store(url, anon_key, token)
    path = args.path.strip("/")
    if args.command == "ls":
        for folder in store.folders(path):
            print("/".join(part for part in (path, folder) if part) + "/")
        for name in store.list(path):
            print(name.lstrip("/"))
        return 0
    body = store.get(path)
    if body is None:
        print(f"{path}: not found", file=sys.stderr)
        return 1
    sys.stdout.write(readable(body).decode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
