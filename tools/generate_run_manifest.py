#!/usr/bin/env python3
"""Write a canonical, non-secret validation run manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from screener.runtime import Config, load_local_config
from validation.reproducibility import build_run_manifest, write_run_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", dest="inputs", type=Path, action="append", default=[])
    parser.add_argument("--git-sha")
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Non-secret metadata to include; may be repeated",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_local_config(Config, REPOSITORY_ROOT / "config_local.py")
    extra: dict[str, str] = {}
    for item in args.extra:
        if "=" not in item:
            raise ValueError(f"--extra must be KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        extra[key] = value
    manifest = build_run_manifest(
        Config,
        input_files=args.inputs,
        git_sha=args.git_sha,
        cwd=REPOSITORY_ROOT,
        extra=extra,
    )
    write_run_manifest(args.output, manifest)
    print(json.dumps({
        "manifest": str(args.output),
        "config_sha256": manifest["config_sha256"],
        "git_sha": manifest["git_sha"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
