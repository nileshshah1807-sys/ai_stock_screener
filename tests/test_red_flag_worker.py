import unittest
from datetime import date
from unittest.mock import patch

from red_flags.vigil import VIGIL_TABLES
from workers.red_flag_worker import RedFlagSettings, RedFlagWorker


class FakeClient:
    def freshness(self):
        return {
            table: {
                "table_name": table,
                "latest_date": str(date.today()),
                "row_count": 1 if table == "pledge_data" else 0,
            }
            for table in VIGIL_TABLES
        }

    def download_table_records(self, table):
        if table == "pledge_data":
            return [{"nse_symbol": "TEST", "perc_encumbered_promoter": 0, "sync_date": str(date.today())}]
        return []


class FakeRepository:
    def __init__(self):
        self.snapshots = []
        self.history = []

    def upsert_red_flag_snapshots(self, snapshots):
        self.snapshots = snapshots
        return len(snapshots)

    def upsert_red_flag_snapshot_history(self, snapshots, observed_on):
        self.history = [(snapshot, observed_on) for snapshot in snapshots]
        return len(snapshots)


class RedFlagWorkerTests(unittest.TestCase):
    def test_worker_fetches_required_tables_and_saves_snapshots(self):
        repository = FakeRepository()
        result = RedFlagWorker(repository, RedFlagSettings(), FakeClient()).run()

        self.assertEqual(result["tables"], 4)
        self.assertEqual(result["raw_rows"], 1)
        self.assertEqual(result["snapshots"], 1)
        self.assertEqual(result["saved"], 1)
        self.assertEqual(result["history_saved"], 1)
        self.assertEqual(result["policy"], "shadow-v2")
        self.assertEqual(result["severity_0"], 1)
        self.assertEqual(result["issuer_severity_3"], 0)
        self.assertEqual(result["trading_severity_3"], 0)
        self.assertEqual(repository.snapshots[0]["symbol"], "TEST")
        self.assertEqual(repository.history[0][0]["symbol"], "TEST")
        self.assertEqual(repository.history[0][1], str(date.today()))

    def test_worker_fails_closed_when_required_freshness_is_missing(self):
        client = FakeClient()
        client.freshness = lambda: {"pledge_data": {"latest_date": str(date.today())}}

        with self.assertRaisesRegex(ValueError, "missing required tables"):
            RedFlagWorker(FakeRepository(), RedFlagSettings(), client).run()

    def test_dry_run_normalizes_without_repository_write(self):
        result = RedFlagWorker(None, RedFlagSettings(), FakeClient()).run()

        self.assertEqual(result["snapshots"], 1)
        self.assertEqual(result["saved"], 0)
        self.assertEqual(result["history_saved"], 0)

    def test_worker_rejects_download_manifest_count_mismatch(self):
        client = FakeClient()
        original = client.freshness

        def mismatched_freshness():
            result = original()
            result["pledge_data"]["row_count"] = 2
            return result

        client.freshness = mismatched_freshness
        with self.assertRaisesRegex(ValueError, "row-count mismatch"):
            RedFlagWorker(FakeRepository(), RedFlagSettings(), client).run()


if __name__ == "__main__":
    unittest.main()
