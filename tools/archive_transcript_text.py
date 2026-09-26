"""Move the text of already-scored earnings calls from Postgres to Storage, once.

The transcript worker now archives each call's text right after scoring it; this
catches up the calls scored before that. A call's text is needed again only if
the analysis is re-run under a new model or version, and the worker then reads
it back from Storage (``transcripts/{MARKET}/{id}.txt.gz``).

    python -m tools.archive_transcript_text --dry-run
    python -m tools.archive_transcript_text

Lossless: each upload is read back and checked against the row's text_hash
before the column is emptied. Rerunning skips rows already emptied.
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.publish_price_series import load_env_file  # noqa: E402

logger = logging.getLogger("archive_transcript_text")

PAGE = 200
WORKERS = 8


def scored_with_text(repository) -> list[dict]:
    """Transcripts that still hold their text and have at least one score."""
    rows, offset = [], 0
    while True:
        batch = repository._request(
            "GET",
            "transcripts",
            params={
                # The inner join keeps only transcripts with a sentiment row.
                "select": "id,market,cleaned_text,text_hash,transcript_sentiments!inner(id)",
                "cleaned_text": "neq.",
                "order": "id",
                "limit": str(PAGE),
                "offset": str(offset),
            },
        ) or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    load_env_file()

    from storage.supabase_repository import SupabaseRepository

    repository = SupabaseRepository.from_environment()
    rows = scored_with_text(repository)
    text_bytes = sum(len((row.get("cleaned_text") or "").encode("utf-8")) for row in rows)
    logger.info("%d scored transcripts still hold text: %.1f MB", len(rows), text_bytes / 1e6)
    if args.dry_run or not rows:
        return 0

    failures = []

    def archive(row):
        try:
            repository.archive_transcript_text(row)
        except Exception as exc:  # noqa: BLE001 - report every failure, archive the rest
            failures.append((row["id"], str(exc)[:200]))

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(archive, rows))
    logger.info("Archived %d of %d transcripts", len(rows) - len(failures), len(rows))
    for transcript_id, error in failures[:10]:
        logger.warning("Not archived %s: %s", transcript_id, error)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
