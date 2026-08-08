"""Fetch free filing-derived risk signals and save compact shadow snapshots."""

from __future__ import annotations

import argparse
import logging
import os
from collections import Counter
from dataclasses import dataclass
from datetime import date

from red_flags.vigil import POLICY_VERSION, VIGIL_TABLES, VigilClient, build_red_flag_snapshots
from storage.supabase_repository import SupabaseRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedFlagSettings:
    base_url: str = "https://api.tigzig.com/vigil/v1"
    timeout_seconds: int = 60
    lookback_days: int = 365
    stale_after_days: int = 7

    @classmethod
    def from_environment(cls):
        return cls(
            base_url=os.getenv("VIGIL_BASE_URL", cls.base_url),
            timeout_seconds=int(os.getenv("VIGIL_TIMEOUT_SECONDS", "60")),
            lookback_days=int(os.getenv("RED_FLAG_LOOKBACK_DAYS", "365")),
            stale_after_days=int(os.getenv("RED_FLAG_STALE_AFTER_DAYS", "7")),
        )


class RedFlagWorker:
    def __init__(self, repository, settings: RedFlagSettings, client=None):
        self.repository = repository
        self.settings = settings
        self.client = client or VigilClient(
            settings.base_url,
            settings.timeout_seconds,
        )

    def run(self) -> dict[str, int | str]:
        freshness = self.client.freshness()
        missing = sorted(set(VIGIL_TABLES) - set(freshness))
        if missing:
            raise ValueError(f"VIGIL freshness is missing required tables: {', '.join(missing)}")
        datasets = {}
        for table in VIGIL_TABLES:
            datasets[table] = self.client.download_table_records(table)
            expected_count = freshness[table].get("row_count")
            if expected_count is not None and int(expected_count) != len(datasets[table]):
                raise ValueError(
                    f"VIGIL {table} row-count mismatch: "
                    f"manifest={expected_count}, download={len(datasets[table])}"
                )
            logger.info("Fetched %s VIGIL row(s) from %s", len(datasets[table]), table)
        snapshots = build_red_flag_snapshots(
            datasets,
            freshness,
            today=date.today(),
            lookback_days=self.settings.lookback_days,
            stale_after_days=self.settings.stale_after_days,
        )
        observed_on = date.today().isoformat()
        saved = self.repository.upsert_red_flag_snapshots(snapshots) if self.repository is not None else 0
        history_saved = (
            self.repository.upsert_red_flag_snapshot_history(snapshots, observed_on)
            if self.repository is not None
            else 0
        )
        severity_counts = Counter(int(item["severity"]) for item in snapshots)
        issuer_counts = Counter(
            int(item["snapshot"].get("issuer_severity", 0)) for item in snapshots
        )
        trading_counts = Counter(
            int(item["snapshot"].get("trading_severity", 0)) for item in snapshots
        )
        return {
            "policy": POLICY_VERSION,
            "tables": len(datasets),
            "raw_rows": sum(len(rows) for rows in datasets.values()),
            "snapshots": len(snapshots),
            "saved": saved,
            "history_saved": history_saved,
            "flags": sum(int(item["flag_count"]) for item in snapshots),
            "severity_0": severity_counts[0],
            "severity_1": severity_counts[1],
            "severity_2": severity_counts[2],
            "severity_3": severity_counts[3],
            "issuer_severity_1": issuer_counts[1],
            "issuer_severity_2": issuer_counts[2],
            "issuer_severity_3": issuer_counts[3],
            "trading_severity_1": trading_counts[1],
            "trading_severity_2": trading_counts[2],
            "trading_severity_3": trading_counts[3],
            "partial_stale": sum(item["source_status"] != "current" for item in snapshots),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh free VIGIL red-flag snapshots")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and normalize live data without requiring or writing Supabase",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repository = None if args.dry_run else SupabaseRepository.from_environment()
    worker = RedFlagWorker(repository, RedFlagSettings.from_environment())
    result = worker.run()
    logger.info("Red-flag worker completed%s: %s", " (dry run)" if args.dry_run else "", result)


if __name__ == "__main__":
    main()
