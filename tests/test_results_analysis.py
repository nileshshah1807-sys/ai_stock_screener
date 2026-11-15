"""The Results analysis object: the page's own code, run by the filings worker."""

import shutil
import unittest
from datetime import date

from workers import results_analysis


def filed(symbol, period_end, revenue, net_profit=10):
    return {"symbol": symbol, "period_end": period_end, "is_consolidated": True,
            "lines": {"revenue": revenue, "operating_profit": None, "net_profit": net_profit}}


class FakeRepo:
    market = "NSE"

    def __init__(self, filings):
        self.filings, self.written, self.after = filings, None, None

    def quarter_lines_since(self, after):
        self.after = after
        return self.filings

    def put_results_analysis(self, analysis):
        self.written = analysis
        return True


@unittest.skipUnless(shutil.which("node"), "node runs the page's code")
class ResultsAnalysisTests(unittest.TestCase):
    def test_each_company_is_stored_once_with_its_rates_by_quarter(self):
        repo = FakeRepo([filed("A", "2026-09-30", 120), filed("A", "2025-09-30", 100), filed("B", "2026-09-30", 50)])
        self.assertTrue(results_analysis.publish(repo, date(2026, 11, 14)))
        stored = repo.written
        self.assertEqual(stored["symbols"], ["A", "B"])
        self.assertEqual(len(stored["rates"]), 8)
        newest = stored["rates"][-1]
        self.assertEqual(newest["quarter"], "2026-09-30")
        # A: +20% revenue, no operating profit, flat PAT; B reported with no year-ago base.
        self.assertEqual(newest["companies"], [[0, 20, None, 0], [1, None, None, None]])
        self.assertLessEqual(repo.after, "2023-11-14")  # before the oldest year-ago quarter's US window (2023-12-31, 45 days each side)

    def test_a_failure_is_logged_never_raised(self):
        class Broken(FakeRepo):
            def quarter_lines_since(self, after):
                raise RuntimeError("down")

        with self.assertLogs("workers.results_analysis", "WARNING"):
            self.assertFalse(results_analysis.publish(Broken([]), date(2026, 11, 14)))


if __name__ == "__main__":
    unittest.main()
