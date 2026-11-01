"""US upcoming results: universe stocks only, dates and timing only, never a failed step."""

import os
import unittest
from datetime import UTC, date, datetime
from unittest import mock

from workers.us_upcoming import KEY_ENV, parse_calendar, run

TODAY = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
CSV = (
    "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\n"
    "AAPL,Apple Inc,2026-11-06,2026-09-30,1.52,USD,post-market\n"
    "AAPL,Apple Inc,2026-12-01,2026-09-30,1.52,USD,\n"
    "MSFT,Microsoft,2026-10-30,2026-09-30,3.1,USD,pre-market\n"
    "BRK-B,Berkshire,2026-11-08,2026-09-30,,USD,\n"
    "ZZZZ,Not in universe,2026-11-05,2026-09-30,1,USD,\n"
)


class FakeRepo:
    market = "US"

    def __init__(self, stored=None):
        self.stored, self.written = stored or {}, []

    def snapshot_companies(self):
        return {"AAPL": "Apple", "MSFT": "Microsoft", "BRK.B": "Berkshire"}

    def upcoming_events(self):
        return self.stored

    def upsert_upcoming_events(self, rows):
        self.written += rows
        return len(rows)


class ParseTests(unittest.TestCase):
    def test_earliest_future_date_of_a_universe_stock_with_its_timing(self):
        found = parse_calendar(CSV, ["AAPL", "MSFT", "BRK.B"], today=TODAY)
        self.assertEqual(found["AAPL"], {"next_result_date": "2026-11-06", "result_purpose": "After market close"})
        self.assertNotIn("MSFT", found)  # already reported
        self.assertNotIn("ZZZZ", found)
        self.assertEqual(found["BRK.B"]["next_result_date"], "2026-11-08")  # the vendor's BRK-B is the universe's BRK.B
        self.assertIsNone(found["BRK.B"]["result_purpose"])

    def test_a_json_refusal_yields_nothing(self):
        self.assertEqual(parse_calendar('{"Information": "rate limit"}', ["AAPL"], today=TODAY), {})


class RunTests(unittest.TestCase):
    def go(self, repo, fetch, key="k"):
        env = {KEY_ENV: key} if key else {}
        with mock.patch.dict(os.environ, env, clear=False):
            if not key:
                os.environ.pop(KEY_ENV, None)
            return run(repo, now=NOW, fetch=fetch)

    def test_writes_dates_without_estimates(self):
        repo = FakeRepo()
        self.go(repo, lambda key: CSV)
        row = next(r for r in repo.written if r["symbol"] == "AAPL")
        self.assertEqual((row["next_result_date"], row["result_purpose"], row["company"]), ("2026-11-06", "After market close", "Apple"))
        self.assertNotIn("estimate", row)
        self.assertIsNone(row["next_call_at"])

    def test_no_key_or_a_refusal_writes_nothing_and_does_not_raise(self):
        repo = FakeRepo()
        self.go(repo, lambda key: CSV, key="")
        self.go(repo, lambda key: '{"Information": "limit"}')
        self.assertEqual(repo.written, [])

    def test_a_failed_request_does_not_leak_the_key(self):
        def boom(key):
            raise RuntimeError(f"403 for url: https://x/query?apikey={key}")

        with self.assertLogs("workers.us_upcoming", "WARNING") as logs:
            self.go(FakeRepo(), boom, key="SECRET")
        self.assertNotIn("SECRET", "".join(logs.output))

    def test_other_markets_are_not_written(self):
        repo = FakeRepo()
        repo.market = "NSE"
        self.go(repo, lambda key: CSV)
        self.assertEqual(repo.written, [])


if __name__ == "__main__":
    unittest.main()
