"""One-off copy of the Supabase ``market-data`` objects to the R2 bucket.

Dry run by default: lists the Supabase objects and reports how many R2 lacks.
``--apply`` downloads each object and uploads it when R2 lacks it or holds a
different number of bytes, so a stopped run resumes where it stopped. (A dry
run cannot see a same-size difference; ``--apply`` reads every body anyway.)
Keys are copied unchanged. Source access is read-only.

    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... R2_ACCOUNT_ID=... R2_BUCKET=... \\
    R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... python -m tools.copy_objects_to_r2 [--apply]
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

from storage.object_backend import r2_from_env
from storage.object_store import ObjectStore
from storage.r2_store import R2Store

#: Objects are small and the work is waiting on two servers: 16 in flight.
WORKERS = 16
PROGRESS_EVERY = 500
DEFAULT_PREFIXES = ("snapshot-payload", "price-series", "transcripts")


def walk(store: ObjectStore, prefix: str) -> Iterator[str]:
    """Every object key under ``prefix``, at any depth."""
    yield from store.list(prefix)
    for folder in store.folders(prefix):
        yield from walk(store, f"{prefix}/{folder}")


def _copy_one(source: ObjectStore, target: R2Store, key: str, held: dict[str, int]) -> tuple[str, int]:
    """Copy one object; returns ``(outcome, bytes)`` with outcome gone, same, new or resized."""
    body = source.get(key)
    if body is None:  # pruned while we copied
        return "gone", 0
    if key in held and held[key] == len(body):
        return "same", len(body)
    target.put(key, body)
    return ("resized" if key in held else "new"), len(body)


def copy_prefix(source: ObjectStore, target: R2Store, prefix: str, apply: bool,
                workers: int = WORKERS) -> dict[str, int]:
    """Counts for one prefix; ``supabase_bytes`` is read only when applying (it needs the bodies)."""
    held = target.sizes(prefix)
    keys = list(walk(source, prefix))
    counts = {"supabase_objects": len(keys), "supabase_bytes": 0,
              "missing_in_r2": sum(key not in held for key in keys), "copied": 0, "resized": 0}
    if apply:
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for outcome, size in pool.map(lambda key: _copy_one(source, target, key, held), keys):
                done += 1
                if outcome == "gone":
                    counts["supabase_objects"] -= 1
                    continue
                counts["supabase_bytes"] += size
                counts["copied"] += outcome in ("new", "resized")
                counts["resized"] += outcome == "resized"
                if done % PROGRESS_EVERY == 0:
                    print(f"{prefix}: {done}/{len(keys)} done, {counts['copied']} uploaded", flush=True)
    final = target.sizes(prefix)
    counts["r2_objects"] = len(final)
    counts["r2_bytes"] = sum(final.values())
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="upload; without it, only count")
    parser.add_argument("--prefix", action="append", help="a folder to copy (repeatable); default: all three")
    args = parser.parse_args(argv)
    source = ObjectStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"], read_only=True)
    target = r2_from_env(read_only=not args.apply)
    for prefix in args.prefix or DEFAULT_PREFIXES:
        counts = copy_prefix(source, target, prefix, args.apply)
        print(f"{prefix}: " + ", ".join(f"{name} {value}" for name, value in counts.items()))
    print("applied" if args.apply else "dry run: nothing written (use --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
