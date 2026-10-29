"""Score every stored outlook again with today's point weights.

The weights in `sentiment.outlook.outlook_items` score a reading; they are not
part of it. When they change, the readings already stored keep the score of
the weights they were read under, and the screener -- which measures each
call against the median call in the run -- would compare calls scored two
ways. This scores them all again from their stored extraction. No model is
asked anything and nothing is read again: the extraction's sections are kept,
only its ``points`` list and the row's ``outlook_score`` change.

Run it once after a change to the weights, before the next screener run.

Usage::

    python -m tools.rescore_transcript_outlooks --dry-run    # how many would change
    python -m tools.rescore_transcript_outlooks              # write them
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentiment.outlook import OUTLOOK_VERSION, outlook_points, outlook_score  # noqa: E402
from tools.publish_price_series import load_env_file  # noqa: E402

logger = logging.getLogger("rescore_transcript_outlooks")


def rescored(row: dict[str, Any]) -> tuple[float, dict[str, Any]] | None:
    """``(score, extraction)`` under today's weights, or None if nothing would change.

    A stored extraction this version cannot score is left as it is.
    """
    extraction = row.get("extraction")
    if not isinstance(extraction, dict):
        return None
    call_date = str(row.get("call_date") or "")[:10] or None
    try:
        score = outlook_score(extraction, call_date)
        points = [{"reason": reason, "points": value} for reason, value in outlook_points(extraction, call_date)]
    except (KeyError, TypeError, AttributeError):
        return None
    if extraction.get("points") == points and float(row.get("outlook_score") or 0.0) == score:
        return None
    return score, {**extraction, "points": points}


def run(repository, *, dry_run: bool = False) -> dict[str, int]:
    counts = {"stored": 0, "changed": 0, "written": 0}
    for row in repository.stored_outlooks(OUTLOOK_VERSION):
        counts["stored"] += 1
        change = rescored(row)
        if change is None:
            continue
        counts["changed"] += 1
        if not dry_run:
            repository.update_outlook_score(row["id"], *change)
            counts["written"] += 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--dry-run", action="store_true", help="count the changes; write nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    load_env_file()
    from storage.supabase_repository import SupabaseRepository

    counts = run(SupabaseRepository.from_environment(args.market), dry_run=args.dry_run)
    logger.info("%s outlooks: %s%s", args.market, counts, " (dry run, nothing written)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
