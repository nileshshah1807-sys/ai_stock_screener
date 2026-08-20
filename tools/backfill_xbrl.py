"""Concurrent, resumable download of NSE Ind-AS XBRL statement documents.

Separate from ``tools.backfill_backtest_archive`` because it has a different
shape: the bhavcopy stage is one sequential request per session against the
rate-sensitive NSE API, whereas this is ~20,500 independent static files on
``nsearchives.nseindia.com``, which parallelises cleanly.

Measured on a live sample: 0.66s mean per document, ~80KB each, plain HTTP with
no cookie or session handshake required. At six workers the full Ind-AS set takes
roughly 40 minutes against 3.8 hours serially.

Usage::

    python -m tools.backfill_xbrl                    # all Ind-AS filings
    python -m tools.backfill_xbrl --workers 8
    python -m tools.backfill_xbrl --max-docs 500     # bounded trial run
    python -m tools.backfill_xbrl --status

Resumable: a document already cached is never re-fetched, so interrupting this
and re-running it costs nothing. Documents are keyed by the exchange's own
``seqNumber``, which is unique per filing, so a re-filing is stored separately
from the original rather than overwriting it.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import logging
from pathlib import Path
import random
import sys
import threading
import time

import pandas as pd

logger = logging.getLogger("xbrl")

DEFAULT_ROOT = Path("reports_advanced/backtest")
DEFAULT_WORKERS = 6

# nsearchives serves static files but still rejects requests without a
# browser-shaped User-Agent and a matching Referer.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/118.0"
    ),
    "Accept": "application/xml,text/xml,*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
}


def document_path(root, seq_number, period_end):
    """Cache path for one filing, sharded by period year to bound directory size."""
    year = str(period_end)[:4] or "unknown"
    return Path(root) / "xbrl" / year / f"{seq_number}.xml.gz"


def load_targets(root, *, ind_as_only=True):
    """Filings that need an XBRL document, from the filing-metadata cache."""
    path = Path(root) / "filings_annual.csv"
    if not path.exists():
        raise SystemExit(
            f"No filing metadata at {path}. Run the filing stage first:\n"
            "  python -m tools.backfill_xbrl --fetch-metadata"
        )
    frame = pd.read_csv(path, dtype={"ISIN": str, "Seq_Number": str})
    frame = frame[frame["XBRL_URL"].astype(str).str.startswith("http")]
    if ind_as_only:
        # The pre-2018 Indian GAAP taxonomy needs a different parser and is out
        # of scope; downloading those documents would be wasted network time.
        frame = frame[frame["Is_Ind_AS"].astype(str).str.lower().isin({"true", "1"})]
    return frame.reset_index(drop=True)


def fetch_metadata(root, start_year, end_year):
    from backtest.filings import FilingStore

    store = FilingStore(Path(root) / "filings_annual.csv")
    frame = store.fetch(start_year, end_year, period="annual")
    logger.info(
        "Filing metadata: %d rows, %d Ind-AS, %d unique securities",
        len(frame),
        int(frame["Is_Ind_AS"].sum()) if len(frame) else 0,
        frame["ISIN"].nunique() if len(frame) else 0,
    )
    return frame


class Downloader:
    """Thread-pooled fetcher with per-thread sessions and bounded retries."""

    def __init__(self, root, *, workers=DEFAULT_WORKERS, timeout=60, retries=3):
        self.root = Path(root)
        self.workers = int(workers)
        self.timeout = int(timeout)
        self.retries = int(retries)
        self._local = threading.local()
        self._lock = threading.Lock()
        self.fetched = 0
        self.skipped = 0
        self.failed = 0
        self.bytes = 0
        self.failure_reasons = Counter()
        self.failure_examples = {}

    def _session(self):
        # One session per worker thread: requests.Session is not documented as
        # thread-safe, and sharing one across the pool is a known source of
        # intermittent connection errors.
        session = getattr(self._local, "session", None)
        if session is None:
            import requests

            session = requests.Session()
            session.headers.update(HEADERS)
            self._local.session = session
        return session

    def fetch_one(self, url, path):
        if path.exists():
            with self._lock:
                self.skipped += 1
            return "cached"

        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                # A short connect timeout prevents a dead NSE edge node from
                # occupying every worker for the full read timeout.  The CLI's
                # --timeout value remains the (more generous) read timeout.
                response = self._session().get(
                    url, timeout=(min(10, self.timeout), self.timeout)
                )
                content_type = response.headers.get("Content-Type", "").lower()
                body_start = response.content[:256].lstrip().lower()
                looks_like_html = (
                    "text/html" in content_type
                    or body_start.startswith(b"<!doctype html")
                    or body_start.startswith(b"<html")
                )
                if (
                    response.status_code == 200
                    and response.content
                    and not looks_like_html
                ):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Write to a temp name then rename, so an interrupted run
                    # cannot leave a truncated file that a later run treats as
                    # cached and never repairs.
                    staging = path.with_suffix(path.suffix + ".part")
                    with gzip.open(staging, "wb") as handle:
                        handle.write(response.content)
                    staging.replace(path)
                    with self._lock:
                        self.fetched += 1
                        self.bytes += len(response.content)
                    return "fetched"
                if response.status_code == 200:
                    last_error = "HTTP 200 returned HTML/non-document content"
                else:
                    last_error = f"HTTP {response.status_code}"

                # These client errors are permanent for a static archive URL.
                # Retrying them only adds backoff and cannot change the result.
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries:
                # Jittered backoff so a transient block does not turn into all
                # workers retrying in lockstep.
                time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))) * (0.5 + random.random()))

        with self._lock:
            self.failed += 1
            reason = (last_error or "unknown error").split(":", 1)[0]
            self.failure_reasons[reason] += 1
            self.failure_examples.setdefault(reason, (url, last_error))
        logger.debug("Failed %s: %s", url, last_error)
        return "failed"

    def failure_summary(self):
        return ", ".join(
            f"{reason}={count}"
            for reason, count in self.failure_reasons.most_common()
        )

    def run(self, targets, *, on_progress=None):
        started = time.monotonic()
        jobs = []
        for record in targets:
            path = document_path(
                self.root, record["Seq_Number"], record["Period_End"]
            )
            jobs.append((record["XBRL_URL"], path))

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(self.fetch_one, url, path): url for url, path in jobs
            }
            for index, future in enumerate(as_completed(futures), start=1):
                future.result()
                if on_progress is not None and index % 250 == 0:
                    elapsed = time.monotonic() - started
                    on_progress(index, len(jobs), elapsed)
        return time.monotonic() - started


def run_status(root):
    root = Path(root)
    metadata = root / "filings_annual.csv"
    cached = list((root / "xbrl").glob("*/*.xml.gz")) if (root / "xbrl").exists() else []
    total_bytes = sum(path.stat().st_size for path in cached)
    print(f"archive root       : {root}")
    print(f"filing metadata    : {'present' if metadata.exists() else 'MISSING'}")
    if metadata.exists():
        targets = load_targets(root)
        target_paths = {
            document_path(root, row["Seq_Number"], row["Period_End"])
            for row in targets.to_dict("records")
        }
        cached_targets = sum(path.exists() for path in target_paths)
        print(f"Ind-AS filings     : {len(targets)}")
        print(f"documents cached   : {cached_targets}")
        remaining = len(target_paths) - cached_targets
        print(f"remaining          : {remaining}")
        if remaining:
            print(f"  est. at 6 workers: {remaining * 0.66 / 6 / 60:.0f} min")
    print(f"cache size         : {total_bytes / 1024 / 1024:.0f} MB")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--max-docs", type=int, default=None,
                        help="cap downloads this run (for a bounded trial)")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--fetch-metadata", action="store_true",
                        help="refresh the filing-metadata cache first")
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--include-non-ind-as", action="store_true",
                        help="also download pre-Ind-AS documents (no parser yet)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    if args.status:
        return run_status(args.root)

    if args.fetch_metadata:
        fetch_metadata(args.root, args.start_year, args.end_year)

    targets = load_targets(args.root, ind_as_only=not args.include_non_ind_as)
    records = targets.to_dict("records")

    root = Path(args.root)
    pending = [
        record
        for record in records
        if not document_path(root, record["Seq_Number"], record["Period_End"]).exists()
    ]
    logger.info(
        "%d Ind-AS filings, %d already cached, %d to download",
        len(records),
        len(records) - len(pending),
        len(pending),
    )
    if args.max_docs:
        pending = pending[: args.max_docs]
        logger.info("Capped to %d documents this run", len(pending))

    if not pending:
        logger.info("Nothing to download; cache is complete")
        return 0

    estimate = len(pending) * 0.66 / max(1, args.workers) / 60
    logger.info(
        "Starting %d workers; estimated %.0f min at the measured 0.66s/doc",
        args.workers,
        estimate,
    )

    downloader = Downloader(
        args.root, workers=args.workers, timeout=args.timeout, retries=args.retries
    )

    def on_progress(done, total, elapsed):
        rate = done / elapsed if elapsed else 0.0
        remaining = (total - done) / rate / 60 if rate else 0.0
        logger.info(
            "  %d/%d | %.1f docs/s | %.0f MB | %d failed | ~%.0f min left",
            done,
            total,
            rate,
            downloader.bytes / 1024 / 1024,
            downloader.failed,
            remaining,
        )
        if downloader.failed:
            logger.info("  failure reasons: %s", downloader.failure_summary())

    elapsed = downloader.run(pending, on_progress=on_progress)
    logger.info(
        "Done in %.1f min: %d fetched, %d cached, %d failed, %.0f MB",
        elapsed / 60,
        downloader.fetched,
        downloader.skipped,
        downloader.failed,
        downloader.bytes / 1024 / 1024,
    )
    if downloader.failed:
        # Not fatal: re-running picks up only the failures, since successes are
        # cached. Said explicitly so a partial run is not mistaken for a complete
        # one when the parser later finds gaps.
        logger.warning(
            "%d documents failed after %d retries. Re-run this command to retry "
            "only those; cached documents are skipped.",
            downloader.failed,
            args.retries,
        )
        logger.warning("Failure reasons: %s", downloader.failure_summary())
        for reason, (url, detail) in downloader.failure_examples.items():
            logger.warning("Example %s: %s (%s)", reason, url, detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
