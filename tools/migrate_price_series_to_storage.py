"""Copy the price_series / price_calendar tables into Supabase Storage, once.

Chart price series moved out of Postgres into the private ``market-data``
bucket (storage/market_data_storage.sql), because the free database stops
accepting writes at 500 MB and these rows were ~80 MB of it. The publisher now
writes objects directly; this copies what the tables already hold -- including
series for securities that have since left the universe, which the publisher
no longer refreshes but the Returns page still prices.

    python -m tools.migrate_price_series_to_storage --dry-run
    python -m tools.migrate_price_series_to_storage

Idempotent: objects are upserted, so a rerun rewrites the same bytes. After it
reports every market verified, the tables can be dropped (see the SQL file).
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.publish_price_series import load_env_file  # noqa: E402

logger = logging.getLogger("migrate_price_series_to_storage")

SERIES_FIELDS = ("symbol", "session_deltas", "closes", "volumes", "points", "first_session", "last_session")
CALENDAR_FIELDS = ("sessions", "session_count", "first_session", "last_session")


def migrate(market: str, *, dry_run: bool, sample: int = 8) -> dict:
    from storage.dashboard_repository import DashboardRepository

    repository = DashboardRepository.from_environment(market)
    calendars = repository._request(
        "GET", "price_calendar", params=repository._scoped({"select": ",".join(CALENDAR_FIELDS)})
    )
    rows = repository._paged(
        "price_series", {"select": ",".join(SERIES_FIELDS), "order": "symbol"}, page=100
    )
    logger.info("%s: %d calendar row(s), %d series rows", market, len(calendars or []), len(rows))
    if dry_run or not rows:
        return {"market": market, "series": len(rows), "written": 0, "verified": None}

    if calendars:
        repository.upsert_price_calendar(calendars[0])
    written = repository.upsert_price_series(rows)

    # Read a sample back and compare field by field: an upload that "succeeds"
    # with the wrong bytes is the failure this step exists to rule out.
    checked = random.Random(0).sample(rows, min(sample, len(rows)))
    stored = repository.read_price_series(row["symbol"] for row in checked)
    mismatched = [
        row["symbol"]
        for row in checked
        if any(stored.get(row["symbol"], {}).get(field) != row[field] for field in SERIES_FIELDS)
    ]
    calendar_ok = not calendars or repository.published_calendar_size() == calendars[0]["session_count"]
    verified = not mismatched and calendar_ok
    logger.info(
        "%s: wrote %d objects; sample of %d %s; calendar %s",
        market, written, len(checked),
        "matches" if not mismatched else f"MISMATCH {mismatched}",
        "matches" if calendar_ok else "MISMATCH",
    )
    return {"market": market, "series": len(rows), "written": written, "verified": verified}


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--markets", nargs="+", default=["NSE", "US"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    load_env_file()
    results = [migrate(market, dry_run=args.dry_run) for market in args.markets]
    return 0 if all(result["verified"] is not False for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
