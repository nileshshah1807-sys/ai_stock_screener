"""Skip scheduled research rebuilds when the trading session is published.

The workflow runs on calendar days, while the model is a completed-session
snapshot. Rebuilding a Friday cross-section on Saturday/Sunday can introduce
vendor revisions and partial-download drift without adding a new market bar.
This guard compares the latest expected NSE session with the latest completed
Supabase run before the expensive screener starts.
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from screener.market_data import latest_expected_completed_nse_session
from screener.runtime import Config
from storage.dashboard_repository import DashboardRepository

logger = logging.getLogger("scheduled_session_guard")


@dataclass(frozen=True)
class GuardDecision:
    skip: bool
    expected_session: date
    published_session: date | None
    reason: str


def _parse_cutoff(value: str | time) -> time:
    if isinstance(value, time):
        return value
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), pattern).time()
        except ValueError:
            continue
    raise ValueError(f"Invalid market completion cutoff: {value!r}")


def decide(
    repository: DashboardRepository,
    *,
    now: datetime,
    completion_cutoff: str | time,
    market_holidays=(),
) -> GuardDecision:
    cutoff = _parse_cutoff(completion_cutoff)
    expected = latest_expected_completed_nse_session(
        now.date(), now.time().replace(tzinfo=None), cutoff, market_holidays
    )
    latest = repository.latest_completed_run()
    published = None
    if latest and latest.get("run_date"):
        published = pd.Timestamp(latest["run_date"]).date()
    skip = published is not None and published >= expected
    reason = (
        f"completed NSE session {expected.isoformat()} is already published"
        if skip
        else f"NSE session {expected.isoformat()} still needs publication"
    )
    return GuardDecision(skip, expected, published, reason)


def _write_github_outputs(path: str | None, decision: GuardDecision) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as output:
        output.write(f"skip={'true' if decision.skip else 'false'}\n")
        output.write(f"expected_session={decision.expected_session.isoformat()}\n")
        output.write(
            "published_session="
            f"{decision.published_session.isoformat() if decision.published_session else ''}\n"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    timezone = ZoneInfo(str(Config.ANALYSIS_TIMEZONE))
    now = datetime.now(timezone)
    try:
        decision = decide(
            DashboardRepository.from_environment(),
            now=now,
            completion_cutoff=Config.MARKET_BAR_COMPLETE_AFTER_IST,
            market_holidays=Config.NSE_MARKET_HOLIDAYS,
        )
    except Exception as exc:
        # Availability checks fail open: a temporary Supabase read problem must
        # not prevent a genuinely new session from being researched.
        logger.warning("Session guard unavailable; running screener: %s", exc)
        expected = latest_expected_completed_nse_session(
            now.date(),
            now.time().replace(tzinfo=None),
            _parse_cutoff(Config.MARKET_BAR_COMPLETE_AFTER_IST),
            Config.NSE_MARKET_HOLIDAYS,
        )
        decision = GuardDecision(False, expected, None, "guard unavailable")

    _write_github_outputs(args.github_output, decision)
    logger.info(decision.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
