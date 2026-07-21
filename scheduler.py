"""
scheduler.py - Keeps the Stock Screener running on a daily schedule.

Usage:
    python scheduler.py                  # run every day at 09:00 Asia/Kolkata
    python scheduler.py --time 08:30     # run every day at a custom HH:MM time
    python scheduler.py --timezone UTC   # run using a custom IANA timezone
    python scheduler.py --now            # run once immediately, then schedule

The script never exits on its own; use Ctrl+C to stop.
"""

import argparse
import logging
import os
import time as _time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import run_daily_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scheduler.log", encoding="utf-8", errors="replace"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

DAILY_RUN_TIME = os.getenv("SCHEDULE_TIME", "09:00")
DAILY_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "Asia/Kolkata")


def job():
    logger.info("Scheduler: triggering run_daily_analysis()")
    try:
        run_daily_analysis()
        logger.info("Scheduler: run completed successfully")
    except Exception as e:
        logger.error(f"Scheduler: run failed: {e}", exc_info=True)


def next_run_at(run_time, timezone_name):
    tz = ZoneInfo(timezone_name)
    hour, minute = [int(part) for part in run_time.split(":", 1)]
    now = datetime.now(tz)
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--time", default=DAILY_RUN_TIME,
        help="Daily run time in HH:MM format. Default: env SCHEDULE_TIME or 09:00"
    )
    parser.add_argument(
        "--timezone", default=DAILY_TIMEZONE,
        help="IANA timezone name. Default: env SCHEDULE_TIMEZONE or Asia/Kolkata"
    )
    parser.add_argument(
        "--now", action="store_true",
        help="Run once immediately before entering the schedule loop"
    )
    args = parser.parse_args()

    run_time = args.time
    timezone_name = args.timezone
    logger.info(f"Scheduler started. Daily run time: {run_time} ({timezone_name}).")
    logger.info("Press Ctrl+C to stop.")

    if args.now:
        logger.info("--now flag set: running immediately...")
        job()

    next_run = next_run_at(run_time, timezone_name)
    logger.info(f"Next run scheduled at {next_run.isoformat()}")

    while True:
        now = datetime.now(ZoneInfo(timezone_name))
        if now >= next_run:
            job()
            next_run = next_run_at(run_time, timezone_name)
            logger.info(f"Next run scheduled at {next_run.isoformat()}")
        _time.sleep(30)


if __name__ == "__main__":
    main()
