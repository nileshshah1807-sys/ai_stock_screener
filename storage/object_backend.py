"""Which object store a run talks to, chosen by ``OBJECT_STORE_BACKEND``.

``supabase`` (also unset or empty -- a workflow passes an unset repository
variable as ""): Supabase Storage only, as before R2.
``dual``: every write goes to Supabase, then to R2; reads stay on Supabase and
an R2 failure is logged, not raised, so a half-set-up bucket cannot fail a
publish. ``r2``: R2 only.
"""

from __future__ import annotations

import atexit
import logging
import os
import time
from collections.abc import Iterable

from storage.object_store import GzipText, ObjectStore
from storage.r2_store import R2Store

logger = logging.getLogger(__name__)

R2_ENV = ("R2_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
#: A dual-mode run logs its running upload time per backend every this many puts.
SUMMARY_EVERY = 500


class DualStore(GzipText):
    """Supabase is the source of truth; R2 is written alongside and timed."""

    def __init__(self, primary: ObjectStore, secondary: R2Store):
        self.primary = primary
        self.secondary = secondary
        self.puts = 0
        self.seconds = {"supabase": 0.0, "r2": 0.0}
        self.r2_failures = 0
        atexit.register(self.log_summary)

    def log_summary(self) -> None:
        if self.puts or self.r2_failures:
            logger.info(
                "dual store: %d puts, upload time supabase %.1fs r2 %.1fs, %d r2 failures",
                self.puts, self.seconds["supabase"], self.seconds["r2"], self.r2_failures,
            )

    def _timed(self, backend: str, call, *args):
        started = time.monotonic()
        try:
            return call(*args)
        finally:
            self.seconds[backend] += time.monotonic() - started

    def _mirror(self, what: str, call, *args) -> None:
        try:
            self._timed("r2", call, *args)
        except Exception as exc:  # noqa: BLE001 - R2 must not fail a run Supabase served
            self.r2_failures += 1
            logger.warning("r2 %s failed (%s); Supabase has it", what, exc)

    def put(self, path: str, body: bytes, content_type: str = "application/gzip") -> None:
        self._timed("supabase", self.primary.put, path, body, content_type)
        self._mirror(f"put {path}", self.secondary.put, path, body, content_type)
        self.puts += 1
        if self.puts % SUMMARY_EVERY == 0:
            self.log_summary()

    def get(self, path: str) -> bytes | None:
        return self.primary.get(path)

    def list(self, prefix: str) -> list[str]:
        return self.primary.list(prefix)

    def folders(self, prefix: str) -> list[str]:
        return self.primary.folders(prefix)

    def remove(self, paths: Iterable[str]) -> int:
        paths = list(paths)
        removed = self.primary.remove(paths)
        self._mirror("remove", self.secondary.remove, paths)
        return removed


def r2_from_env(read_only: bool = False, timeout_seconds: int = 60) -> R2Store:
    missing = [name for name in R2_ENV if not os.environ.get(name)]
    if missing:
        raise ValueError(f"{', '.join(missing)} required for an R2 object store")
    return R2Store(*(os.environ[name] for name in R2_ENV), timeout_seconds=timeout_seconds, read_only=read_only)


def open_object_store(url: str, service_role_key: str, timeout_seconds: int = 60, read_only: bool = False):
    backend = (os.environ.get("OBJECT_STORE_BACKEND") or "supabase").strip().lower()
    if backend == "supabase":
        return ObjectStore(url, service_role_key, timeout_seconds, read_only=read_only)
    if backend == "r2":
        return r2_from_env(read_only, timeout_seconds)
    if backend == "dual":
        return DualStore(
            ObjectStore(url, service_role_key, timeout_seconds, read_only=read_only),
            r2_from_env(read_only, timeout_seconds),
        )
    raise ValueError(f"OBJECT_STORE_BACKEND must be supabase, dual or r2, not {backend!r}")
