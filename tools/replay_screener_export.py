#!/usr/bin/env python3
"""Replay candidate logic over a frozen screener CSV without network access."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from screener.runtime import Config
from validation.replay import (
    MODEL_PROVENANCE_COLUMNS,
    REPLAY_LIMITATIONS,
    replay_export_frame,
    replay_source_provenance,
    technical_price_source_counts,
)
from validation.reproducibility import (
    build_run_manifest,
    sha256_file,
    write_run_manifest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_csv", type=Path)
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("--analysis-date", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Manifest destination (default: <candidate>.manifest.json)",
    )
    return parser.parse_args()


def replay_csv(
    source_csv: str | Path,
    candidate_csv: str | Path,
    *,
    analysis_date: date,
    manifest_path: str | Path | None = None,
    config: Any | None = None,
) -> tuple[pd.DataFrame, Path, Path]:
    """Replay one frozen export and write candidate plus evidence manifest."""

    source_path = Path(source_csv)
    candidate_path = Path(candidate_csv)
    if source_path.resolve() == candidate_path.resolve():
        raise ValueError("candidate CSV must not overwrite the frozen source CSV")
    manifest_destination = (
        Path(manifest_path)
        if manifest_path is not None
        else candidate_path.with_suffix(".manifest.json")
    )
    if manifest_destination.resolve() in {
        source_path.resolve(),
        candidate_path.resolve(),
    }:
        raise ValueError("manifest path must differ from source and candidate CSV")

    effective_config = config or Config()
    source = pd.read_csv(source_path, low_memory=False)
    source_provenance = replay_source_provenance(source)
    candidate = replay_export_frame(
        source,
        effective_config,
        analysis_date=analysis_date,
    )

    manifest = build_run_manifest(
        effective_config,
        input_files=[source_path],
        cwd=REPOSITORY_ROOT,
        extra={"run_kind": "frozen_export_replay"},
    )
    source_artifact = dict(manifest["inputs"][0])
    candidate["Run_Git_SHA"] = manifest["git_sha"]
    candidate["Run_Git_Dirty"] = manifest["git_dirty"]
    candidate["Run_Manifest_Schema_Version"] = manifest["schema_version"]
    candidate["Run_Manifest_Path"] = manifest_destination.name
    candidate["Run_Source_CSV_SHA256"] = source_artifact["sha256"]

    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate.to_csv(candidate_path, index=False)
    output_artifact = {
        "path": candidate_path.as_posix(),
        "sha256": sha256_file(candidate_path),
        "size_bytes": candidate_path.stat().st_size,
        "rows": len(candidate),
        "columns": len(candidate.columns),
    }
    manifest["replay"] = {
        "analysis_date": analysis_date.isoformat(),
        "source_csv": source_artifact,
        "candidate_csv": output_artifact,
        "candidate_metadata": {
            column: str(candidate[column].iloc[0])
            for column in MODEL_PROVENANCE_COLUMNS
        },
        "technical_price_sources": technical_price_source_counts(candidate),
        "limitations": list(REPLAY_LIMITATIONS),
        **source_provenance,
    }
    write_run_manifest(manifest_destination, manifest)
    return candidate, candidate_path, manifest_destination


def main() -> int:
    args = parse_args()
    candidate, candidate_path, manifest_path = replay_csv(
        args.source_csv,
        args.candidate_csv,
        analysis_date=args.analysis_date,
        manifest_path=args.manifest,
    )
    print(
        f"replayed {len(candidate)} frozen rows -> {candidate_path}; "
        f"manifest -> {manifest_path}; market-bar and historical-universe "
        "defects in the source remain frozen"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
