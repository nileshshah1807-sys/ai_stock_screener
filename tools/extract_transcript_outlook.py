"""Extract the outlook from stored earnings-call transcripts with a language model.

Reads every transcript that has no outlook yet for the chosen model and
`sentiment.outlook.OUTLOOK_VERSION`, sends each to the model, keeps only the
items whose quoted sentence is found in the transcript, scores them and writes
one row to ``transcript_outlooks``. The daily screener reads that table: the
outlook of a company's latest call shares the transcript weight with its tone
score (``TRANSCRIPT_OUTLOOK_SHARE``), so a run here moves the next published
scores.

Resumable -- a transcript already extracted is skipped -- and bounded: the run
stops submitting once ``--max-cost`` is spent, so a small credit balance ends in
a partial run rather than a wall of payment errors.

Where the request goes is `sentiment.llm_provider`'s choice: OpenRouter
(paid) in the scheduled workflows, Token Harbor (free) on a developer's
machine. A Token Harbor reading is a trial of the prompt, not production's
reading, so it is reported and not written unless ``--write`` is given; pass
``--provider openrouter`` to write locally what production would.

Usage::

    python -m tools.extract_transcript_outlook --dry-run        # count and estimate, no API calls
    python -m tools.extract_transcript_outlook --limit 5        # a first look
    python -m tools.extract_transcript_outlook --latest-only     # each company's newest call
    python -m tools.extract_transcript_outlook --max-cost 4.5   # everything pending, capped
    python -m tools.extract_transcript_outlook --refresh-since 2026-10-01   # read this season's calls again
    python -m tools.extract_transcript_outlook --refresh-since 2026-10-01 --stance-only   # ... for the stance alone
    python -m tools.extract_transcript_outlook --limit 60       # locally: read 60 calls free, report, write nothing
    python -m tools.extract_transcript_outlook --list-models    # Token Harbor's model ids

Needs ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY``, and
``OPENROUTER_API_KEY`` or ``TOKENHARBOR_API_KEY`` for the provider in use, from
the environment or ``.env``, and the ``transcript_outlooks`` table from
``storage/supabase_schema.sql``.
"""

from __future__ import annotations

import argparse
import collections
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentiment.llm_provider import (  # noqa: E402
    TOKENHARBOR,
    TOKENHARBOR_MODELS_URL,
    ProviderError,
    resolve_provider,
)
from sentiment.outlook import (  # noqa: E402
    DEFAULT_MODEL,
    MAX_PRICE_PER_MILLION,
    OUTLOOK_VERSION,
    STANCES,
    QuotaSpentError,
    analyse_stance,
    analyse_transcript,
)
from tools.publish_price_series import load_env_file  # noqa: E402

logger = logging.getLogger("extract_transcript_outlook")

# USD per million tokens, for the dry-run estimate only; a real run records the
# cost the API reports. The price depends on which provider serves the call, so
# the estimate uses the most a request is allowed to pay: it is a ceiling.
ESTIMATE_PRICES = {DEFAULT_MODEL: MAX_PRICE_PER_MILLION}
FREE_PROVIDERS = (TOKENHARBOR,)
# `transcripts.token_count` is a whitespace-based estimate; a model tokenizer
# produces somewhat more, and each request adds the instructions.
TOKEN_INFLATION = 1.25
PROMPT_OVERHEAD_TOKENS = 1000
ESTIMATED_OUTPUT_TOKENS = 800
# The stance is a second request over the same transcript, answered after the
# model thinks: 1,000-6,000 tokens a call on the 9 calls it was measured on.
ESTIMATED_STANCE_OUTPUT_TOKENS = 5000


def estimate_cost(transcripts, model, provider=None, stance_only=False):
    """Rough USD cost of extracting ``transcripts``, or None for an unpriced model."""
    if provider in FREE_PROVIDERS:
        return 0.0
    prices = ESTIMATE_PRICES.get(model)
    if prices is None:
        return None
    requests_per_call = 1 if stance_only else 2
    prompt = requests_per_call * sum(
        int(row.get("token_count") or 0) * TOKEN_INFLATION + PROMPT_OVERHEAD_TOKENS
        for row in transcripts
    )
    output = len(transcripts) * (
        ESTIMATED_STANCE_OUTPUT_TOKENS + (0 if stance_only else ESTIMATED_OUTPUT_TOKENS)
    )
    return (prompt * prices[0] + output * prices[1]) / 1_000_000


def pending_transcripts(repository, model, latest_only=False, refresh_since=None):
    """Transcripts with no outlook yet, newest call first.

    ``latest_only`` keeps each company's most recent call, which is the only
    one the screener reads; earlier calls matter for testing the score against
    the returns that followed them.

    ``refresh_since`` (an ISO date) also returns calls held on or after it that
    already have an outlook, to be read again and overwritten -- how a question
    added to the extraction reaches calls read before it was asked. A second
    reading can differ from the first, so their outlook scores can move --
    unless the run keeps only the second reading's stance (`run`).
    """
    done = repository.outlook_transcript_ids(model, OUTLOOK_VERSION)
    transcripts = repository.transcripts_for_outlook()
    if refresh_since:
        done = {
            row["id"] for row in transcripts
            if row["id"] in done and str(row.get("call_date") or "") < refresh_since
        }
    if latest_only:
        latest = {}
        for row in transcripts:
            latest.setdefault(row["symbol"], row)
        transcripts = list(latest.values())
    return [row for row in transcripts if row["id"] not in done]


class Budget:
    """Spend so far, shared by the worker threads."""

    def __init__(self, limit):
        self.limit = float(limit)
        self.spent = 0.0
        self.stopped = False
        self._lock = threading.Lock()

    def exhausted(self):
        with self._lock:
            return self.stopped or self.spent >= self.limit

    def stop(self):
        """No more requests: the provider will serve none this period."""
        with self._lock:
            self.stopped = True

    def add(self, cost):
        with self._lock:
            self.spent += float(cost or 0.0)


def run(repository, transcripts, provider, *, workers, budget, stance_only=False, write=True):
    """Extract and store each transcript's outlook.

    ``stance_only`` is for reading again calls that already have an outlook:
    only the stance is asked for, it replaces the stored one, and the scored
    items stay as they were. The stored outlook is production's (``DEFAULT_MODEL``)
    whoever reads the stance, and the stance records who did (``read_by``). A
    call with no stored outlook is stored whole by production and skipped by
    any other provider, whose scored items must not reach the screener.

    ``write=False`` stores nothing; the readings are returned in
    ``summary["rows"]`` for `stance_report`.
    """
    import requests

    local = threading.local()
    summary = {
        "extracted": 0, "failed": 0, "skipped_budget": 0, "skipped_no_outlook": 0,
        "verified": 0, "unverified": 0, "rows": [],
    }
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
            analyse = analyse_stance if stance_only else analyse_transcript
            row = analyse(session(), provider, transcript, text)
            if write and stance_only:
                stance = row["extraction"]["stance"] | {"read_by": row["model_name"]}
                stored = repository.save_outlook_stance(row["transcript_id"], DEFAULT_MODEL, OUTLOOK_VERSION, stance)
                if not stored and provider.is_production:
                    repository.save_outlook(row)
                elif not stored:
                    with lock:
                        summary["skipped_no_outlook"] += 1
            elif write:
                repository.save_outlook(row)
        except QuotaSpentError as exc:
            # Every later request would be refused the same way: stop
            # submitting, and leave the rest for the next period.
            budget.stop()
            with lock:
                summary["skipped_budget"] += 1
            logger.warning("%s %s not read, allowance spent: %s", transcript.get("symbol"), transcript.get("call_date"), exc)
            return
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
            if not write:
                summary["rows"].append(row)
            done = summary["extracted"]
        if done % 50 == 0:
            logger.info("  %d extracted, $%.3f spent", done, budget.spent)

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        list(pool.map(one, transcripts))
    return summary


def _rank_correlation(first, second):
    """Spearman's rho of two equal-length sequences, or None if either is constant."""
    import pandas as pd

    frame = pd.DataFrame({"a": first, "b": second})
    if len(frame) < 3 or frame["a"].nunique() < 2 or frame["b"].nunique() < 2:
        return None
    return float(frame["a"].rank().corr(frame["b"].rank()))


def stance_report(rows):
    """Lines describing a set of readings: each call, the spread, and the agreement.

    The agreement is the stance's rank order against the call's own outlook
    score -- the one reference stored for every call. It is not the whole
    test: a stance that only restated the score would agree perfectly.
    """
    order = {view: rank for rank, view in enumerate(reversed(STANCES[:-1]))}
    lines = []
    read = []
    for row in sorted(rows, key=lambda row: (str(row.get("call_date") or ""), str(row.get("symbol"))), reverse=True):
        stance = (row.get("extraction") or {}).get("stance") or {}
        view = stance.get("view") or "unknown"
        score = row.get("outlook_score")
        # A stance-only reading has no outlook score of its own.
        shown = "    -" if score is None else f"{float(score):5.1f}"
        lines.append(
            f"  {row.get('call_date') or '?':10} {str(row.get('symbol')):12} "
            f"outlook {shown}  {view:10} {str(stance.get('quote') or '')[:90]}"
        )
        if view in order and score is not None:
            read.append((order[view], float(score)))
    counts = collections.Counter(
        ((row.get("extraction") or {}).get("stance") or {}).get("view") or "unknown" for row in rows
    )
    lines.append("  " + ", ".join(f"{view} {counts.get(view, 0)}" for view in STANCES))
    rho = _rank_correlation([view for view, _ in read], [score for _, score in read])
    lines.append(
        f"  stance against outlook score: Spearman {rho:.2f} over {len(read)} calls"
        if rho is not None else "  stance against outlook score: too few distinct readings to rank"
    )
    return lines


def list_models(provider):
    """Token Harbor's callable model ids."""
    import requests

    response = requests.get(
        TOKENHARBOR_MODELS_URL, headers={"Authorization": f"Bearer {provider.api_key}"}, timeout=30
    )
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("data", payload) if isinstance(payload, dict) else payload
    return sorted(str(entry.get("id", entry)) if isinstance(entry, dict) else str(entry) for entry in entries)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--market", default="NSE")
    parser.add_argument(
        "--provider", default=None, choices=("openrouter", "tokenharbor"),
        help="default: openrouter in GitHub Actions, tokenharbor elsewhere (or OUTLOOK_PROVIDER)",
    )
    parser.add_argument("--model", default=None, help="default: the provider's DeepSeek model")
    parser.add_argument(
        "--write", action="store_true",
        help="store a Token Harbor reading (an OpenRouter reading is always stored)",
    )
    parser.add_argument("--list-models", action="store_true", help="print Token Harbor's model ids and stop")
    parser.add_argument("--limit", type=int, default=None, help="newest N pending calls only")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-cost", type=float, default=4.5, help="stop submitting after this many USD")
    parser.add_argument(
        "--latest-only", action="store_true",
        help="each company's most recent call only (what the screener reads)",
    )
    parser.add_argument(
        "--refresh-since", default=None, metavar="YYYY-MM-DD",
        help="also read again calls held on or after this date that already have an outlook",
    )
    parser.add_argument(
        "--stance-only", action="store_true",
        help="for a call that already has an outlook, replace its stance and keep its scored items",
    )
    parser.add_argument("--dry-run", action="store_true", help="count and estimate; no API calls, no writes")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    load_env_file()
    import requests

    try:
        provider = resolve_provider(
            TOKENHARBOR if args.list_models else args.provider, args.model
        )
    except ProviderError as exc:
        raise SystemExit(str(exc)) from exc
    if args.list_models:
        print("\n".join(list_models(provider)))
        return 0
    write = provider.is_production or args.write
    if write and not provider.is_production and not args.stance_only:
        # The screener reads the latest outlook of any model: a whole reading
        # stored from here would move published scores.
        raise SystemExit("--write with a development provider stores the stance only: add --stance-only")

    from storage.supabase_repository import SupabaseRepository

    repository = SupabaseRepository.from_environment(args.market)
    try:
        pending = pending_transcripts(
            repository, DEFAULT_MODEL if args.stance_only else provider.stored_model_name,
            latest_only=args.latest_only, refresh_since=args.refresh_since,
        )
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
    estimate = estimate_cost(pending, provider.model, provider.name, args.stance_only)
    logger.info(
        "%d transcript(s) pending for %s via %s / %s; estimated cost %s; %s",
        len(pending),
        provider.model,
        provider.name,
        OUTLOOK_VERSION,
        "unknown (model not in the price table)" if estimate is None else f"at most ${estimate:.2f}",
        "readings will be stored" if write else "nothing will be stored (pass --write to store)",
    )
    if args.dry_run or not pending:
        return 0

    names = repository.company_names_by_document_id(
        [row["document_id"] for row in pending if row.get("document_id")]
    )
    for row in pending:
        row["company_name"] = names.get(row.get("document_id"), "")

    budget = Budget(args.max_cost)
    summary = run(
        repository, pending, provider,
        workers=args.workers, budget=budget, stance_only=args.stance_only, write=write,
    )
    if not write:
        print("\n".join(stance_report(summary["rows"])))
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
