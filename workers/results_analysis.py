"""The Results analysis page's per-company rates, written once where the filings are.

The page took the median growth of a whole quarter's filings on every render
(~1 MB parsed, 400-660 ms of Worker CPU). This writes each company's rate per
quarter to ``live/{MARKET}/results-analysis.json`` after the filings worker
stores filings; the page filters it to the viewer's companies and takes the
medians. The rates are worked out by the page's own code
(``dashboard/scripts/results-analysis.mjs`` over ``dashboard/lib/results.mjs``),
run under node, so there is no second copy of the math. No rating or rank.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPT = Path(__file__).resolve().parent.parent / "dashboard" / "scripts" / "results-analysis.mjs"
#: Eight quarters and their year-ago ones, plus the US window's 45 days: a superset the script narrows.
LOOKBACK_DAYS = 3 * 366 + 60


def compute(market: str, today: date, filings: list[dict]) -> dict:
    """Run the page's code over ``filings``; raises if node fails."""
    payload = json.dumps({"market": market, "today": today.isoformat(), "filings": filings})
    done = subprocess.run(["node", str(SCRIPT)], input=payload, capture_output=True, text=True, timeout=300, check=False)
    if done.returncode:
        raise RuntimeError(f"results-analysis.mjs failed: {done.stderr.strip()[-500:]}")
    return json.loads(done.stdout)


def publish(repo, today: date) -> bool:
    """Write the market's object. An error is logged, never raised: the page computes without it."""
    try:
        analysis = compute(repo.market, today, repo.quarter_lines_since((today - timedelta(days=LOOKBACK_DAYS)).isoformat()))
        written = repo.put_results_analysis(analysis)
    except Exception as exc:  # noqa: BLE001 -- the stored filings stand; the next run writes it
        logger.warning("Results analysis object not written: %s", exc)
        return False
    if written:
        logger.info("Results analysis object written: %d quarters", len(analysis["rows"]))
    return written
