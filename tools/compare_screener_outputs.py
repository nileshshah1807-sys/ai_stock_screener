#!/usr/bin/env python3
"""Compare baseline and candidate screener CSVs without collecting new data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from validation.comparator import compare_csv_files
from validation.reproducibility import canonical_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_csv", type=Path)
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument(
        "--rank-column",
        default="auto",
        help="Rank, Investment_Rank, Actionable_Rank, or auto (default)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary, attribution = compare_csv_files(
        args.baseline_csv,
        args.candidate_csv,
        top_n=args.top_n,
        rank_column=args.rank_column,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "comparison.json"
    attribution_path = args.output_dir / "symbol_attribution.csv"
    json_safe_summary = json.loads(canonical_json(summary))
    summary_path.write_text(
        json.dumps(json_safe_summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    attribution.to_csv(attribution_path, index=False)
    print(json.dumps({
        "summary": str(summary_path),
        "attribution": str(attribution_path),
        "top_overlap_count": summary["top_overlap_count"],
        "top_n": summary["top_n"],
        "top_jaccard": summary["top_jaccard"],
        "entrants": summary["entrants"],
        "exits": summary["exits"],
        "spearman_common_ranks": summary["spearman_common_ranks"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
