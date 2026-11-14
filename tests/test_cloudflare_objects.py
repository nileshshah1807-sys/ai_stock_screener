"""The R2 objects the Cloudflare dashboard reads in place of tables."""

import gzip
import json
import unittest

from tests.test_dashboard_repository import RecordingDashboardRepository


class MemoryStore:
    def __init__(self, fail=False):
        self.objects, self.fail = {}, fail

    def put(self, path, body, content_type="application/gzip"):
        if self.fail:
            raise RuntimeError("R2 down")
        self.objects[path] = body

    def get(self, path):
        return self.objects.get(path)


def repo(store):
    r = RecordingDashboardRepository()
    r._r2 = store
    return r


def rows_of(store, path):
    return json.loads(store.objects[path])["rows"]


class LiveObjectTests(unittest.TestCase):
    def test_quotes_keep_unquoted_symbols_and_drop_stale_ones(self):
        store = MemoryStore()
        r = repo(store)
        r.put_live_quotes_object(
            [{"symbol": "A", "price": 1, "fetched_at": "2026-11-01T00:00:00+00:00"},
             {"symbol": "B", "price": 2, "fetched_at": "2026-11-14T09:00:00+00:00"}],
            "2026-11-01T00:00:00+00:00",
        )
        r.put_live_quotes_object(
            [{"symbol": "C", "price": 3, "fetched_at": "2026-11-14T09:05:00+00:00"}],
            "2026-11-07T00:00:00+00:00",
        )
        self.assertEqual([q["symbol"] for q in rows_of(store, "live/NSE/quotes.json")], ["B", "C"])

    def test_a_replace_writes_its_whole_set(self):
        store = MemoryStore()
        repo(store).replace_index_members([{"index_name": "NIFTY 50", "position": 0, "symbol": "A", "company": "a"}])
        self.assertEqual([m["symbol"] for m in rows_of(store, "live/NSE/index-members.json")], ["A"])

    def test_an_r2_failure_never_fails_the_table_write(self):
        r = repo(MemoryStore(fail=True))
        self.assertEqual(r.replace_index_members([{"index_name": "X", "position": 0, "symbol": "A"}]), 1)
        self.assertFalse(r.put_live_quotes_object([{"symbol": "A"}], ""))

    def test_without_r2_nothing_is_attempted(self):
        self.assertFalse(repo(None).put_live_quotes_object([{"symbol": "A"}], ""))
        self.assertIsNone(repo(None).archive_history("2026-11-14", [{}]))


class RunObjectTests(unittest.TestCase):
    def test_search_index_is_largest_first_and_carries_no_rating(self):
        store = MemoryStore()
        repo(store).put_search_index("2026-11-14", [
            {"symbol": "S", "company": "s", "market_cap": 5, "rating": "BUY", "rank": 1},
            {"symbol": "N", "company": "n", "market_cap": None, "final_score": 9},
            {"symbol": "L", "company": "l", "market_cap": 50, "sector": "IT", "logo_domain": "l.com"},
        ])
        entries = rows_of(store, "search-index/NSE/2026-11-14.json")
        self.assertEqual([e["symbol"] for e in entries], ["L", "S", "N"])
        self.assertEqual({k for e in entries for k in e}, {"symbol", "company", "logo_domain", "sector"})

    def test_history_archive_reads_back_whole(self):
        store = MemoryStore()
        rows = [{"symbol": "A", "observed_on": "2026-11-14", "investment_rank": 3}]
        path = repo(store).archive_history("2026-11-14", rows)
        self.assertEqual(path, "archive/screener-history/NSE/2026-11-14.json.gz")
        self.assertEqual(json.loads(gzip.decompress(store.objects[path])), rows)

    def test_a_history_archive_that_differs_on_read_back_raises(self):
        store = MemoryStore()
        store.get = lambda path: b"other"
        with self.assertRaises(RuntimeError):
            repo(store).archive_history("2026-11-14", [{"symbol": "A"}])


if __name__ == "__main__":
    unittest.main()
