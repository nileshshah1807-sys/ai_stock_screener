import unittest

from storage.dashboard_repository import DashboardRepository


class RecordingDashboardRepository(DashboardRepository):
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.responses.pop(0) if self.responses else None


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
        self.assertEqual(first_params["offset"], "0")
        self.assertEqual(second_params["offset"], "2")

    def test_logo_upsert_sends_only_identity_and_domain(self):
        repository = RecordingDashboardRepository()

        written = repository.upsert_snapshot_logo_domains(
            "2026-08-14",
            [{"symbol": "RELIANCE", "logo_domain": "ril.com"}],
        )

        self.assertEqual(written, 1)
        method, path, kwargs = repository.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            path,
            "screener_snapshot?on_conflict=run_date,symbol",
        )
        self.assertEqual(
            kwargs["json"],
            [
                {
                    "run_date": "2026-08-14",
                    "symbol": "RELIANCE",
                    "logo_domain": "ril.com",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
