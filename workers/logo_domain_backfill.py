"""Backfill company website domains for an already-published dashboard run.

This is intentionally independent of the daily publisher. It patches only the
nullable ``logo_domain`` field, checkpoints successful lookups in small
batches, and skips populated rows on every rerun.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Callable
from urllib.parse import urlparse

import yfinance as yf

from storage.dashboard_repository import DashboardRepository

logger = logging.getLogger("logo_domain_backfill")


@dataclass
class BackfillSummary:
    run_date: str
    candidates: int = 0
    resolved: int = 0
    no_website: int = 0
    failed: int = 0
    written: int = 0


def normalize_domain(website: Any) -> str | None:
    """Normalize an issuer website into the identifier Brandfetch expects."""
    if website is None or not str(website).strip():
        return None
    candidate = str(website).strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        hostname = urlparse(candidate).hostname
    except ValueError:
        return None
    if not hostname:
        return None
    domain = hostname.lower().rstrip(".")
    return domain[4:] if domain.startswith("www.") else domain


def resolve_yahoo_domain(symbol: str) -> str | None:
    """Resolve one NSE symbol through Yahoo's issuer website metadata."""
    info = yf.Ticker(f"{symbol}.NS").info
    if not isinstance(info, dict) or len(info) < 5:
        return None
    return normalize_domain(info.get("website"))


class RequestPacer:
    """Space Yahoo metadata calls evenly to avoid burst rate limits."""

    def __init__(
        self,
        requests_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute must be at least 1")
        self.interval = 60.0 / requests_per_minute
        self.clock = clock
        self.sleep = sleep
        self.next_request_at: float | None = None

    def __call__(self) -> None:
        now = self.clock()
        if self.next_request_at is not None and now < self.next_request_at:
            self.sleep(self.next_request_at - now)
            now = self.clock()
        self.next_request_at = now + self.interval


def resolve_run_date(
    repository: DashboardRepository,
    requested: str | None,
) -> str:
    if requested:
        return date.fromisoformat(requested).isoformat()
    latest = repository.latest_completed_run()
    if not latest or not latest.get("run_date"):
        raise RuntimeError("Supabase has no completed dashboard run to backfill")
    return date.fromisoformat(str(latest["run_date"])).isoformat()


def backfill_logo_domains(
    repository: DashboardRepository,
    *,
    run_date: str | None = None,
    limit: int = 0,
    batch_size: int = 25,
    resolver: Callable[[str], str | None] = resolve_yahoo_domain,
    pace: Callable[[], None] | None = None,
) -> BackfillSummary:
    """Resolve and patch every missing logo domain in one snapshot."""
    target_date = resolve_run_date(repository, run_date)
    candidates = repository.snapshot_logo_candidates(target_date, only_missing=True)
    if limit > 0:
        candidates = candidates[:limit]

    summary = BackfillSummary(run_date=target_date, candidates=len(candidates))
    pending: list[dict[str, str]] = []

    def flush() -> None:
        if not pending:
            return
        summary.written += repository.upsert_snapshot_logo_domains(
            target_date,
            pending,
        )
        pending.clear()

    for index, row in enumerate(candidates, start=1):
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            summary.failed += 1
            continue
        if pace is not None:
            pace()
        try:
            domain = normalize_domain(resolver(symbol))
        except Exception as exc:  # one bad Yahoo response must not lose progress
            summary.failed += 1
            logger.warning("%s lookup failed: %s", symbol, exc)
            continue

        if domain:
            summary.resolved += 1
            pending.append({"symbol": symbol, "logo_domain": domain})
            if len(pending) >= batch_size:
                flush()
        else:
            summary.no_website += 1

        if index % 25 == 0 or index == len(candidates):
            logger.info(
                "Progress %s/%s: resolved=%s no_website=%s failed=%s written=%s",
                index,
                len(candidates),
                summary.resolved,
                summary.no_website,
                summary.failed,
                summary.written,
            )

    flush()
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill missing company logo domains in a dashboard snapshot."
    )
    parser.add_argument(
        "--run-date",
        help="Snapshot date in YYYY-MM-DD format; defaults to latest completed run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum rows to inspect; 0 means every missing row.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Successful domains checkpointed per Supabase write.",
    )
    parser.add_argument(
        "--requests-per-minute",
        type=int,
        default=int(os.getenv("LOGO_BACKFILL_REQUESTS_PER_MINUTE", "40")),
        help="Yahoo metadata request rate (default: 40).",
    )
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if args.requests_per_minute < 1:
        parser.error("--requests-per-minute must be at least 1")
    if args.run_date:
        try:
            date.fromisoformat(args.run_date)
        except ValueError:
            parser.error("--run-date must use YYYY-MM-DD")
    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = parse_args(argv)
    repository = DashboardRepository.from_environment()
    summary = backfill_logo_domains(
        repository,
        run_date=args.run_date,
        limit=args.limit,
        batch_size=args.batch_size,
        pace=RequestPacer(args.requests_per_minute),
    )
    print(json.dumps(asdict(summary), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
