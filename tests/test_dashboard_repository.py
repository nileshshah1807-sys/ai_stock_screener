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


class MemoryObjectStore:
    """Supabase Storage as a dict of path -> bytes, with its folder listing."""

    def __init__(self, paths=()):
        self.objects = dict.fromkeys(paths, b"")

    def put(self, path, body, content_type="application/gzip"):
        self.objects[path] = body

    def get(self, path):
        return self.objects.get(path)

    def _children(self, prefix):
        return {path[len(prefix) + 1 :].split("/")[0]: path for path in self.objects
                if path.startswith(prefix + "/")}

    def list(self, prefix):
        return [path for name, path in self._children(prefix).items()
                if path == f"{prefix}/{name}"]

    def folders(self, prefix):
        return [name for name, path in self._children(prefix).items()
                if path != f"{prefix}/{name}"]

    def remove(self, paths):
        paths = list(paths)
        for path in paths:
            del self.objects[path]
        return len(paths)


class SnapshotPayloadTests(unittest.TestCase):
    """The payload left Postgres for Storage: a third of the database in a day."""

    def repository(self, runs, paths=(), market="NSE"):
        repository = RecordingDashboardRepository([runs], market=market)
        repository._objects = MemoryObjectStore(paths)
        return repository

    def test_each_symbol_is_one_object_in_its_runs_folder(self):
        repository = self.repository([])

        written = repository.upsert_snapshot_payloads(
            "2026-10-28", {"A&B": {"Symbol": "A&B", "Decision_Score": 36.8}, "XYZ.BO": {}}
        )

        self.assertEqual(written, 2)
        stored = repository._objects.objects
        self.assertEqual(
            sorted(stored),
            [
                "snapshot-payload/NSE/2026-10-28/A&B.json.gz",
                "snapshot-payload/NSE/2026-10-28/XYZ.BO.json.gz",
            ],
        )
        body = stored["snapshot-payload/NSE/2026-10-28/A&B.json.gz"]
        self.assertEqual(json.loads(gzip.decompress(body)), {"Symbol": "A&B", "Decision_Score": 36.8})

    def test_prune_deletes_every_folder_whose_run_is_gone(self):
        # 10-27 was pruned; 10-26 was a failed publish whose reservation the
        # compensation removed. Neither is in screener_runs any more.
        repository = self.repository(
            [{"run_date": "2026-10-28"}],
            [
                "snapshot-payload/NSE/2026-10-28/AAA.json.gz",
                "snapshot-payload/NSE/2026-10-27/AAA.json.gz",
                "snapshot-payload/NSE/2026-10-27/BBB.json.gz",
                "snapshot-payload/NSE/2026-10-26/AAA.json.gz",
            ],
        )

        removed = repository.prune_snapshot_payloads()

        self.assertEqual(removed, 3)
        self.assertEqual(list(repository._objects.objects), ["snapshot-payload/NSE/2026-10-28/AAA.json.gz"])
        self.assertEqual(repository.calls[0][2]["params"]["market"], "eq.NSE")

    def test_prune_keeps_an_in_flight_reservation(self):
        repository = self.repository(
            [{"run_date": "2026-10-29"}, {"run_date": "2026-10-28"}],
            ["snapshot-payload/NSE/2026-10-29/AAA.json.gz", "snapshot-payload/NSE/2026-10-28/AAA.json.gz"],
        )

        self.assertEqual(repository.prune_snapshot_payloads(), 0)
        self.assertEqual(len(repository._objects.objects), 2)

    def test_prune_never_touches_the_other_markets_folders(self):
        repository = self.repository(
            [{"run_date": "2026-10-28"}],
            ["snapshot-payload/NSE/2026-10-27/AAA.json.gz"],
            market="US",
        )

        self.assertEqual(repository.prune_snapshot_payloads(), 0)
        self.assertIn("snapshot-payload/NSE/2026-10-27/AAA.json.gz", repository._objects.objects)


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
        self.assertNotIn("payload", first_params["select"])
        self.assertEqual(first_params["offset"], "0")
        self.assertEqual(second_params["offset"], "2")

    def test_logo_upsert_sends_only_identity_and_domain(self):
        repository = RecordingDashboardRepository()

        written = repository.upsert_snapshot_logo_domains(
            "2026-08-14",
            [
                {"symbol": "RELIANCE", "logo_domain": "ril.com"}
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

    def test_the_filings_readers_are_narrowed_too(self):
        # A US ticker can equal an NSE symbol; an unscoped read would mix two companies.
        for call in (
            lambda r: r.quarterly_filing_state(),
            lambda r: r.quarterly_filings(["TCS"]),
            lambda r: r.recent_filed_results("2026-10-01T00:00:00"),
            lambda r: r.result_first_seen(),
        ):
            repository = RecordingDashboardRepository([[]], market="US")
            call(repository)
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
        repository = RecordingDashboardRepository([[{"run_date": "2026-10-15"}], 0], market="US")

        repository.prune_snapshots(keep_runs=2)

        self.assertEqual(repository.calls[0][2]["params"]["market"], "eq.US")
        self.assertEqual(repository.calls[-1][1], "rpc/prune_screener_snapshots")
        self.assertEqual(repository.calls[-1][2]["json"]["p_market"], "US")

    def test_pruning_empties_old_runs_in_batches_before_the_run(self):
        """One cascade of a whole run outran the statement timeout."""
        runs = [{"run_date": day} for day in ("2026-10-15", "2026-10-14", "2026-10-13")]
        repository = RecordingDashboardRepository(
            [
                runs,
                [{"symbol": "AAA"}, {"symbol": "BBB"}], None,  # 10-14, first batch
                [{"symbol": "CCC"}], None,                      # 10-14, second batch
                [],                                             # 10-14 empty
                [{"symbol": "AAA"}], None, [],                  # 10-13
                2,                                              # runs removed
            ]
        )

        removed = repository.prune_snapshots(keep_runs=1, batch_size=2)

        self.assertEqual(removed, 2)
        deletes = [
            (kwargs["params"]["run_date"], kwargs["params"]["symbol"])
            for method, _path, kwargs in repository.calls
            if method == "DELETE"
        ]
        self.assertEqual(
            deletes,
            [
                ("eq.2026-10-14", 'in.("AAA","BBB")'),
                ("eq.2026-10-14", 'in.("CCC")'),
                ("eq.2026-10-13", 'in.("AAA")'),
            ],
        )
        # The newest run is never touched, and the runs go last.
        self.assertFalse(any("2026-10-15" in str(call) for call in repository.calls[1:]))
        self.assertEqual(repository.calls[-1][1], "rpc/prune_screener_snapshots")

    def test_pruning_stops_when_a_delete_removes_nothing(self):
        stuck = [{"symbol": "AAA"}]
        repository = RecordingDashboardRepository(
            [[{"run_date": "2026-10-15"}, {"run_date": "2026-10-14"}], stuck, None, stuck, None]
        )
        with self.assertRaises(RuntimeError):
            repository.prune_snapshots(keep_runs=1)

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
    """requests.Session stand-in: raises the queued errors, then answers 204.

    A queued integer is answered as that HTTP status instead of raised.
    """

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        error = self.errors.pop(0) if self.errors else 204
        if not isinstance(error, int):
            raise error
        response = requests.Response()
        response.status_code = error
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

    def test_gateway_errors_are_retried_like_timeouts(self):
        # The NSE publish of 26 Oct 2026 died on one Cloudflare 520.
        session = _FlakySession(520, 521)
        with mock.patch("storage.dashboard_repository.time.sleep") as sleep:
            self.repository(session)._request("POST", "t", retries=3, json=[])
        self.assertEqual(session.calls, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])

    def test_a_gateway_error_on_the_last_attempt_is_raised(self):
        session = _FlakySession(*[521] * 3)
        with mock.patch("storage.dashboard_repository.time.sleep"), self.assertRaises(requests.HTTPError):
            self.repository(session)._request("POST", "t", retries=2, json=[])
        self.assertEqual(session.calls, 3)

    def test_a_rejected_request_is_not_retried(self):
        session = _FlakySession(400)
        with self.assertRaises(requests.HTTPError):
            self.repository(session)._request("POST", "t", retries=3, json=[])
        self.assertEqual(session.calls, 1)

    def test_snapshot_and_history_upserts_ask_for_retries(self):
        session = _FlakySession(520, 520)
        repository = self.repository(session)
        with mock.patch("storage.dashboard_repository.time.sleep"):
            repository.replace_snapshot_rows("2026-10-26", [{"symbol": "A"}])
            repository.upsert_history_rows([{"symbol": "A"}])
        self.assertEqual(session.calls, 4)

    def test_breadth_upsert_asks_for_retries(self):
        session = _FlakySession(requests.ConnectionError("The write operation timed out"))
        repository = self.repository(session)
        with (
            mock.patch("storage.dashboard_repository.time.sleep"),
            mock.patch.object(repository, "_paged", return_value=[]),
        ):
            self.assertEqual(repository.replace_market_breadth([{"scope": "s", "name": "n"}]), 1)
        self.assertEqual(session.calls, 2)

    def test_breadth_upsert_stamps_updated_at(self):
        repository = self.repository(_FlakySession())
        with (
            mock.patch.object(repository, "_request") as request,
            mock.patch.object(repository, "_paged", return_value=[]),
        ):
            repository.replace_market_breadth([{"scope": "s", "name": "n"}])
        self.assertIn("updated_at", request.call_args.kwargs["json"][0])
