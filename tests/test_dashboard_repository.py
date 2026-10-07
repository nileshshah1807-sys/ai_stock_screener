import gzip
import json
import unittest
from unittest import mock

import requests

from storage.dashboard_repository import DashboardRepository


class RecordingDashboardRepository(DashboardRepository):
    def __init__(self, responses=None, market="NSE"):
        self.responses = list(responses or [])
        self.calls = []
        # The real __init__ needs Supabase credentials, so it is bypassed here.
        # The market scope is what the queries below read, so it is set
        # explicitly rather than inherited.
        self.market = market

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.responses.pop(0) if self.responses else None


class StorageRecordingRepository(RecordingDashboardRepository):
    """Keeps uploaded objects in memory instead of Supabase Storage."""

    def __init__(self, market="NSE"):
        super().__init__(market=market)
        self.objects = {}
        self.transfers = []

    def _storage(self, method, path, body=None):
        self.transfers.append((method, path, body))
        if method == "POST":
            self.objects[path] = body
            return None
        return self.objects.get(path)


class SimulatedRankingTests(unittest.TestCase):
    def test_a_rebuild_clears_this_markets_backtest_before_the_live_date(self):
        repository = RecordingDashboardRepository(market="NSE")

        repository.delete_simulated_rankings("2026-10-08")

        method, path, kwargs = repository.calls[0]
        self.assertEqual((method, path), ("DELETE", "simulated_rankings"))
        # Scoped to the market and bounded by date: a US row, or a ranking
        # published on or after the live date, must never be removed.
        self.assertEqual(
            kwargs["params"], {"observed_on": "lt.2026-10-08", "market": "eq.NSE"}
        )


    def test_a_rebuild_clears_this_markets_weekly_states_too(self):
        repository = RecordingDashboardRepository(market="NSE")

        repository.delete_simulated_states("2026-10-08")

        method, path, kwargs = repository.calls[0]
        self.assertEqual((method, path), ("DELETE", "simulated_states"))
        self.assertEqual(
            kwargs["params"], {"observed_on": "lt.2026-10-08", "market": "eq.NSE"}
        )


class DashboardRepositoryLogoTests(unittest.TestCase):
    def test_latest_completed_run_ignores_reservations(self):
        repository = RecordingDashboardRepository(
            [[{"run_date": "2026-08-14", "row_count": 2368}]]
        )

        run = repository.latest_completed_run()

        self.assertEqual(run["run_date"], "2026-08-14")
        params = repository.calls[0][2]["params"]
        self.assertEqual(params["row_count"], "gt.0")
        self.assertEqual(params["order"], "run_date.desc")

    def test_logo_candidates_page_without_mutating_the_filter(self):
        first_page = [
            {"symbol": f"S{index}", "company": None, "logo_domain": None}
            for index in range(2)
        ]
        repository = RecordingDashboardRepository([first_page, []])

        rows = repository.snapshot_logo_candidates(
            "2026-08-14",
            only_missing=True,
            page_size=2,
        )

        self.assertEqual(len(rows), 2)
        first_params = repository.calls[0][2]["params"]
        second_params = repository.calls[1][2]["params"]
        self.assertEqual(first_params["logo_domain"], "is.null")
        self.assertIn("payload", first_params["select"])
        self.assertEqual(first_params["offset"], "0")
        self.assertEqual(second_params["offset"], "2")

    def test_logo_upsert_sends_only_identity_and_domain(self):
        repository = RecordingDashboardRepository()

        written = repository.upsert_snapshot_logo_domains(
            "2026-08-14",
            [
                {
                    "symbol": "RELIANCE",
                    "logo_domain": "ril.com",
                    "payload": {"Symbol": "RELIANCE", "Decision_Score": 36.8},
                }
            ],
        )

        self.assertEqual(written, 1)
        method, path, kwargs = repository.calls[0]
        self.assertEqual(method, "POST")
        # Market joins the conflict target because it joins the primary key.
        self.assertEqual(
            path,
            "screener_snapshot?on_conflict=market,run_date,symbol",
        )
        self.assertEqual(
            kwargs["json"],
            [
                {
                    "run_date": "2026-08-14",
                    "symbol": "RELIANCE",
                    "logo_domain": "ril.com",
                    "payload": {"Symbol": "RELIANCE", "Decision_Score": 36.8},
                    "market": "NSE",
                }
            ],
        )


class MarketScopingTests(unittest.TestCase):
    """Every read is narrowed and every write stamped with one market.

    Symbols collide across exchanges -- TCS is Tata Consultancy on the NSE and
    The Container Store in the US -- so an unscoped query would mix two
    companies into one row set.
    """

    def test_reads_are_narrowed_to_the_repositorys_market(self):
        repository = RecordingDashboardRepository([[]], market="US")

        repository.latest_completed_run()

        self.assertEqual(repository.calls[0][2]["params"]["market"], "eq.US")

    def test_snapshot_writes_are_stamped(self):
        repository = RecordingDashboardRepository(market="US")

        repository.replace_snapshot_rows(
            "2026-08-14",
            [{"run_date": "2026-08-14", "symbol": "TCS", "payload": {}}],
        )

        rows = repository.calls[0][2]["json"]
        self.assertEqual(rows[0]["market"], "US")

    def test_estimate_writes_keep_the_first_sighting(self):
        repository = RecordingDashboardRepository(market="US")

        written = repository.upsert_estimate_rows(
            [{"symbol": "NVDA", "fetched_at": "2026-09-24T07:08:35+00:00"}]
        )

        self.assertEqual(written, 1)
        method, path, kwargs = repository.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "estimate_history?on_conflict=market,symbol,fetched_at")
        self.assertIn("resolution=ignore-duplicates", kwargs["headers"]["Prefer"])
        self.assertEqual(kwargs["json"][0]["market"], "US")

    def test_no_estimate_rows_sends_nothing(self):
        repository = RecordingDashboardRepository()
        self.assertEqual(repository.upsert_estimate_rows([]), 0)
        self.assertEqual(repository.calls, [])

    def test_previous_run_is_read_from_history_which_is_never_pruned(self):
        repository = RecordingDashboardRepository([[{"observed_on": "2026-09-24"}]], market="US")

        previous = repository.previous_completed_run_date("2026-09-25")

        self.assertEqual(previous, "2026-09-24")
        method, path, kwargs = repository.calls[0]
        self.assertEqual(path, "screener_history")
        self.assertEqual(kwargs["params"]["observed_on"], "lt.2026-09-25")
        self.assertEqual(kwargs["params"]["investment_rank"], "eq.1")
        self.assertEqual(kwargs["params"]["market"], "eq.US")

    def test_history_writes_are_stamped(self):
        repository = RecordingDashboardRepository(market="US")

        repository.upsert_history_rows([{"observed_on": "2026-08-14", "symbol": "TCS"}])

        method, path, kwargs = repository.calls[0]
        self.assertEqual(path, "screener_history?on_conflict=market,observed_on,symbol")
        self.assertEqual(kwargs["json"][0]["market"], "US")

    def test_pruning_retains_runs_per_market(self):
        """Ranked globally, two markets would halve each other's retention."""
        repository = RecordingDashboardRepository([2], market="US")

        repository.prune_snapshots(keep_runs=2)

        self.assertEqual(repository.calls[0][2]["json"]["p_market"], "US")

    def test_the_calendar_is_one_object_per_market(self):
        repository = StorageRecordingRepository(market="US")

        repository.upsert_price_calendar({"sessions": "x", "session_count": 1})

        method, path, body = repository.transfers[0]
        self.assertEqual((method, path), ("POST", "price-series/US/calendar.json.gz"))
        self.assertEqual(json.loads(gzip.decompress(body))["market"], "US")

    def test_series_round_trip_through_storage_objects(self):
        repository = StorageRecordingRepository(market="NSE")
        row = {"symbol": "M&M", "session_deltas": "[0,1]", "closes": "[100,5]", "volumes": "[1,1]"}

        self.assertEqual(repository.upsert_price_series([row]), 1)
        self.assertEqual(repository.transfers[0][1], "price-series/NSE/symbols/M&M.json.gz")
        found = repository.read_price_series(["M&M", "MISSING"])

        self.assertEqual(list(found), ["M&M"])
        self.assertEqual(found["M&M"]["closes"], "[100,5]")
        self.assertEqual(repository.published_calendar_size(), None)

    def test_an_unknown_market_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            DashboardRepository("https://x.test", "key", market="LSE")


if __name__ == "__main__":
    unittest.main()


class _FlakySession:
    """requests.Session stand-in: raises the queued errors, then answers 204."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        response = requests.Response()
        response.status_code = 204
        response._content = b""
        return response


class RetryTests(unittest.TestCase):
    """The US breadth publish of 30 Sept 2026 died on one write timeout."""

    def repository(self, session):
        repository = DashboardRepository("https://x.test", "key", market="US")
        repository.session = session
        return repository

    def test_idempotent_write_survives_a_transient_timeout(self):
        session = _FlakySession(
            requests.ConnectionError("The write operation timed out"),
            requests.Timeout("read timed out"),
        )
        with mock.patch("storage.dashboard_repository.time.sleep") as sleep:
            self.repository(session)._request("POST", "t", retries=3, json=[])
        self.assertEqual(session.calls, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])

    def test_gives_up_after_the_last_retry(self):
        session = _FlakySession(*[requests.ConnectionError("down")] * 4)
        with mock.patch("storage.dashboard_repository.time.sleep"), self.assertRaises(requests.ConnectionError):
            self.repository(session)._request("POST", "t", retries=3, json=[])
        self.assertEqual(session.calls, 4)

    def test_calls_are_not_retried_unless_asked(self):
        session = _FlakySession(requests.ConnectionError("down"))
        with self.assertRaises(requests.ConnectionError):
            self.repository(session)._request("POST", "t", json=[])
        self.assertEqual(session.calls, 1)

    def test_breadth_upsert_asks_for_retries(self):
        session = _FlakySession(requests.ConnectionError("The write operation timed out"))
        repository = self.repository(session)
        with (
            mock.patch("storage.dashboard_repository.time.sleep"),
            mock.patch.object(repository, "_paged", return_value=[]),
        ):
            self.assertEqual(repository.replace_market_breadth([{"scope": "s", "name": "n"}]), 1)
        self.assertEqual(session.calls, 2)
