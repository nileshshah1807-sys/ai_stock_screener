"""Extract the outlook from stored earnings-call transcripts with a language model.

Reads every transcript that has no outlook yet for the chosen model and
`sentiment.outlook.OUTLOOK_VERSION`, sends each to OpenRouter, keeps only the
items whose quoted sentence is found in the transcript, scores them and writes
one row to ``transcript_outlooks``. The daily screener reads that table: the
outlook of a company's latest call shares the transcript weight with its tone
score (``TRANSCRIPT_OUTLOOK_SHARE``), so a run here moves the next published
scores.

Resumable -- a transcript already extracted is skipped -- and bounded: the run
stops submitting once ``--max-cost`` is spent, so a small credit balance ends in
a partial run rather than a wall of payment errors.

Usage::

    python -m tools.extract_transcript_outlook --dry-run        # count and estimate, no API calls
    python -m tools.extract_transcript_outlook --limit 5        # a first look
    python -m tools.extract_transcript_outlook --max-cost 4.5   # everything pending, capped

Needs ``OPENROUTER_API_KEY``, ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY``,
from the environment or ``.env``, and the ``transcript_outlooks`` table from
``storage/supabase_schema.sql``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentiment.outlook import (  # noqa: E402
    DEFAULT_MODEL,
    MAX_PRICE_PER_MILLION,
    OUTLOOK_VERSION,
    analyse_transcript,
)
from tools.publish_price_series import load_env_file  # noqa: E402

logger = logging.getLogger("extract_transcript_outlook")

# USD per million tokens, for the dry-run estimate only; a real run records the
# cost the API reports. The price depends on which provider serves the call, so
# the estimate uses the most a request is allowed to pay: it is a ceiling.
ESTIMATE_PRICES = {DEFAULT_MODEL: MAX_PRICE_PER_MILLION}
# `transcripts.token_count` is a whitespace-based estimate; a model tokenizer
# produces somewhat more, and each request adds the instructions.
TOKEN_INFLATION = 1.25
PROMPT_OVERHEAD_TOKENS = 1000
ESTIMATED_OUTPUT_TOKENS = 800


def estimate_cost(transcripts, model):
    """Rough USD cost of extracting ``transcripts``, or None for an unpriced model."""
    prices = ESTIMATE_PRICES.get(model)
    if prices is None:
        return None
    prompt = sum(
        int(row.get("token_count") or 0) * TOKEN_INFLATION + PROMPT_OVERHEAD_TOKENS
        for row in transcripts
    )
    output = len(transcripts) * ESTIMATED_OUTPUT_TOKENS
    return (prompt * prices[0] + output * prices[1]) / 1_000_000


def pending_transcripts(repository, model):
    done = repository.outlook_transcript_ids(model, OUTLOOK_VERSION)
    return [row for row in repository.transcripts_for_outlook() if row["id"] not in done]


class Budget:
    """Spend so far, shared by the worker threads."""

    def __init__(self, limit):
        self.limit = float(limit)
        self.spent = 0.0
        self._lock = threading.Lock()

    def exhausted(self):
        with self._lock:
            return self.spent >= self.limit

    def add(self, cost):
        with self._lock:
            self.spent += float(cost or 0.0)


def run(repository, transcripts, api_key, *, model, workers, budget):
    import requests

    local = threading.local()
    summary = {"extracted": 0, "failed": 0, "skipped_budget": 0, "verified": 0, "unverified": 0}
    lock = threading.Lock()

    def session():
        if getattr(local, "session", None) is None:
            local.session = requests.Session()
        return local.session

    def one(transcript):
        if budget.exhausted():
            with lock:
                summary["skipped_budget"] += 1
            return
        try:
            text = transcript.get("cleaned_text") or repository.restore_transcript_text(transcript)
            if not text:
                raise ValueError("transcript has no text in the column or in storage")
            row = analyse_transcript(session(), api_key, transcript, text, model=model)
            repository.save_outlook(row)
        except Exception as exc:  # noqa: BLE001 - one bad call must not stop the run
            # An unusable reply was still billed, and must count toward the cap.
            budget.add(getattr(exc, "cost_usd", 0.0))
            with lock:
                summary["failed"] += 1
            logger.warning("%s %s failed: %s", transcript.get("symbol"), transcript.get("call_date"), exc)
            return
        budget.add(row["cost_usd"])
        with lock:
            summary["extracted"] += 1
            summary["verified"] += row["verified_fields"]
            summary["unverified"] += row["unverified_fields"]
            done = summary["extracted"]
        if done % 50 == 0:
            logger.info("  %d extracted, $%.3f spent", done, budget.spent)

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        list(pool.map(one, transcripts))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None, help="newest N pending calls only")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-cost", type=float, default=4.5, help="stop submitting after this many USD")
    parser.add_argument("--dry-run", action="store_true", help="count and estimate; no API calls, no writes")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    load_env_file()
    import requests

    from storage.supabase_repository import SupabaseRepository

    repository = SupabaseRepository.from_environment(args.market)
    try:
        pending = pending_transcripts(repository, args.model)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise SystemExit(
                "The transcript_outlooks table does not exist yet. Apply the "
                "transcript_outlooks statements in storage/supabase_schema.sql "
                "(the whole file is safe to re-run), then run this again."
            ) from exc
        raise
    if args.limit:
        pending = pending[: args.limit]
    estimate = estimate_cost(pending, args.model)
    logger.info(
        "%d transcript(s) pending for %s / %s; estimated cost %s",
        len(pending),
        args.model,
        OUTLOOK_VERSION,
        "unknown (model not in the price table)" if estimate is None else f"at most ${estimate:.2f}",
    )
    if args.dry_run or not pending:
        return 0

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set (environment or .env)")

    names = repository.company_names_by_document_id(
        [row["document_id"] for row in pending if row.get("document_id")]
    )
    for row in pending:
        row["company_name"] = names.get(row.get("document_id"), "")

    budget = Budget(args.max_cost)
    summary = run(repository, pending, api_key, model=args.model, workers=args.workers, budget=budget)
    claimed = summary["verified"] + summary["unverified"]
    logger.info(
        "Extracted %d, failed %d, not started for budget %d; $%.3f spent; "
        "%d of %d claimed items had their quote found in the transcript (%.0f%%)",
        summary["extracted"],
        summary["failed"],
        summary["skipped_budget"],
        budget.spent,
        summary["verified"],
        claimed,
        100.0 * summary["verified"] / claimed if claimed else 0.0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
