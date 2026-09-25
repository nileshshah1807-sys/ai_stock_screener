import datetime as dt
import unittest

import pandas as pd

from tools.backfill_returns_history import (
    equal_weight_index,
    next_session,
    top_rankings,
    weekly_signal_dates,
)

D = dt.date


class WeeklySignalDateTests(unittest.TestCase):
    def test_last_session_of_each_week(self):
        sessions = [D(2026, 8, 3), D(2026, 8, 5), D(2026, 8, 7), D(2026, 8, 10), D(2026, 8, 13)]
        self.assertEqual(
            weekly_signal_dates(sessions, D(2026, 8, 1), D(2026, 8, 31)),
            [D(2026, 8, 7), D(2026, 8, 13)],
        )

    def test_a_holiday_friday_falls_back_to_the_last_real_session(self):
        sessions = [D(2026, 8, 3), D(2026, 8, 6)]  # Friday 7th closed
        self.assertEqual(weekly_signal_dates(sessions, D(2026, 8, 1), D(2026, 8, 9)), [D(2026, 8, 6)])

    def test_next_session_is_strictly_after(self):
        sessions = [D(2026, 8, 7), D(2026, 8, 10)]
        self.assertEqual(next_session(sessions, D(2026, 8, 7)), D(2026, 8, 10))
        self.assertIsNone(next_session(sessions, D(2026, 8, 10)))


class TopRankingTests(unittest.TestCase):
    def test_ranks_by_score_under_the_current_ticker(self):
        fills = pd.DataFrame(
            {
                "Signal_Date": ["2026-08-07"] * 3,
                "Security_ID": ["A1", "B1", "C1"],
                "Research_Score": [70.0, 99.5, 88.2],
                "Stage": ["Stage 2", "Stage 3", None],
            }
        )
        rows = top_rankings(fills, {"A1": "ETERNAL", "B1": "TMPV", "C1": "INFY"}, top_n=2)
        self.assertEqual([row["symbol"] for row in rows], ["TMPV", "INFY"])
        self.assertEqual([row["investment_rank"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["stage"], "Stage 3")
        self.assertIsNone(rows[1]["stage"])

    def test_an_unmappable_security_is_skipped_not_published_stale(self):
        fills = pd.DataFrame(
            {
                "Signal_Date": ["2026-08-07"] * 2,
                "Security_ID": ["GONE", "B1"],
                "Research_Score": [99.0, 50.0],
            }
        )
        rows = top_rankings(fills, {"B1": "TMPV"})
        self.assertEqual([(row["symbol"], row["investment_rank"]) for row in rows], [("TMPV", 1)])


class EqualWeightIndexTests(unittest.TestCase):
    sessions = [D(2026, 8, 3), D(2026, 8, 4), D(2026, 8, 5), D(2026, 8, 6)]

    def test_members_earn_from_the_session_after_they_are_bought(self):
        closes = {
            D(2026, 8, 3): {"A": 100.0, "B": 50.0},
            D(2026, 8, 4): {"A": 110.0, "B": 45.0},
            D(2026, 8, 5): {"A": 121.0, "B": 45.0},
        }
        rows = equal_weight_index(closes, [(D(2026, 8, 3), {"A", "B"})], self.sessions)
        # 08-04: (+10% - 10%) / 2 = 0; 08-05: (+10% + 0%) / 2 = +5%.
        self.assertEqual([row[0] for row in rows], [D(2026, 8, 4), D(2026, 8, 5)])
        self.assertAlmostEqual(rows[0][1], 0.0)
        self.assertAlmostEqual(rows[1][1], 5.0)

    def test_a_skipped_session_is_credited_when_the_stock_next_trades(self):
        closes = {
            D(2026, 8, 3): {"A": 100.0},
            D(2026, 8, 5): {"A": 120.0},
        }
        rows = equal_weight_index(closes, [(D(2026, 8, 3), {"A"})], self.sessions)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], D(2026, 8, 5))
        self.assertAlmostEqual(rows[0][1], 20.0)

    def test_membership_changes_after_the_next_entry(self):
        closes = {
            D(2026, 8, 3): {"A": 100.0, "B": 100.0},
            D(2026, 8, 4): {"A": 110.0, "B": 100.0},
            D(2026, 8, 5): {"A": 110.0, "B": 90.0},
        }
        memberships = [(D(2026, 8, 3), {"A"}), (D(2026, 8, 4), {"B"})]
        rows = equal_weight_index(closes, memberships, self.sessions)
        self.assertAlmostEqual(rows[0][1], 10.0)   # 08-04 still A
        self.assertAlmostEqual(rows[1][1], -10.0)  # 08-05 is B's first session


if __name__ == "__main__":
    unittest.main()
