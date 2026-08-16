import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from workers.scheduled_session_guard import GuardDecision, _write_github_outputs, decide


IST = ZoneInfo("Asia/Kolkata")


class FakeRepository:
    def __init__(self, run_date):
        self.run_date = run_date

    def latest_completed_run(self):
        return {"run_date": self.run_date} if self.run_date else None


class ScheduledSessionGuardTests(unittest.TestCase):
    def test_weekend_skips_when_friday_session_is_published(self):
        result = decide(
            FakeRepository("2026-08-14"),
            now=datetime(2026, 8, 16, 16, 30, tzinfo=IST),
            completion_cutoff="16:15",
        )

        self.assertTrue(result.skip)
        self.assertEqual(result.expected_session.isoformat(), "2026-08-14")

    def test_new_completed_session_runs(self):
        result = decide(
            FakeRepository("2026-08-14"),
            now=datetime(2026, 8, 17, 16, 30, tzinfo=IST),
            completion_cutoff="16:15",
        )

        self.assertFalse(result.skip)
        self.assertEqual(result.expected_session.isoformat(), "2026-08-17")

    def test_configured_holiday_uses_previous_session(self):
        result = decide(
            FakeRepository("2026-08-17"),
            now=datetime(2026, 8, 18, 16, 30, tzinfo=IST),
            completion_cutoff="16:15",
            market_holidays=("2026-08-18",),
        )

        self.assertTrue(result.skip)
        self.assertEqual(result.expected_session.isoformat(), "2026-08-17")

    def test_writes_stable_workflow_outputs(self):
        decision = GuardDecision(
            True,
            expected_session=datetime(2026, 8, 14).date(),
            published_session=datetime(2026, 8, 14).date(),
            reason="already published",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-output.txt"
            _write_github_outputs(str(path), decision)
            output = path.read_text(encoding="utf-8")

        self.assertIn("skip=true", output)
        self.assertIn("expected_session=2026-08-14", output)
        self.assertIn("published_session=2026-08-14", output)


if __name__ == "__main__":
    unittest.main()
