import datetime as dt
import unittest

import pandas as pd

from tools.backfill_returns_history import (
    equal_weight_index,
    next_session,
    top_rankings,
    weekly_signal_dates,
    weekly_states,
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
        overall = [row for row in rows if row["investment_rank"] <= 2]
        self.assertEqual([row["symbol"] for row in overall], ["TMPV", "INFY"])
        # ETERNAL is third overall but the top Stage 2 name, so it is kept.
        self.assertEqual(rows[-1]["symbol"], "ETERNAL")
        self.assertEqual(rows[-1]["rank_stage2"], 1)
        self.assertEqual([row["investment_rank"] for row in overall], [1, 2])
        self.assertEqual(overall[0]["stage"], "Stage 3")
        self.assertIsNone(overall[1]["stage"])

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


class PickRankTests(unittest.TestCase):
    def fills(self):
        return pd.DataFrame(
            {
                "Signal_Date": ["2026-08-07"] * 5,
                "Security_ID": ["A", "B", "C", "D", "E"],
                "Research_Score": [99.0, 95.0, 90.0, 85.0, 80.0],
                "Stage": ["Stage 3", "Stage 2", "Stage 2", "S2 Candidate", "Stage 2"],
                "Advance_Age_Days": [None, 200, 12, 40, 30],
            }
        )

    def test_each_pick_is_ranked_inside_itself(self):
        ratings = {"A": "HOLD", "B": "BUY", "C": "STRONG BUY", "D": "BUY", "E": "STRONG BUY"}
        rows = top_rankings(
            self.fills(),
            {key: key for key in "ABCDE"},
            top_n=2,
            rate=lambda row, day: ratings[row["Security_ID"]],
        )
        by = {row["symbol"]: row for row in rows}
        # Overall top 2 is A, B; every pick's own top 2 is kept too. D is the
        # third BUY and in no pick's top 2, so it is left out.
        self.assertEqual(sorted(by), ["A", "B", "C", "E"])
        self.assertEqual([by[s]["rank_buy"] for s in "BC"], [1, 2])
        self.assertEqual(by["C"]["rank_strong_buy"], 1)
        self.assertEqual(by["E"]["rank_strong_buy"], 2)
        self.assertEqual([by[s]["rank_stage2"] for s in "BC"], [1, 2])
        # Fresh: Stage 2 and an advance at most 30 days old -- C (12d), E (30d).
        self.assertIsNone(by["B"]["rank_fresh_stage2"])
        self.assertEqual(by["C"]["rank_fresh_stage2"], 1)
        self.assertEqual(by["E"]["rank_fresh_stage2"], 2)
        self.assertEqual(by["E"]["investment_rank"], 5)

    def test_a_week_without_quality_coverage_is_not_rated(self):
        fills = self.fills().assign(Quality_Coverage_Sufficient=[False, False, False, True, False])
        rows = top_rankings(fills, {key: key for key in "ABCDE"}, top_n=5, rate=lambda row, day: "BUY")
        self.assertTrue(all(row["rating"] is None and row["rank_buy"] is None for row in rows))

    def test_without_ratings_the_rating_picks_stay_empty(self):
        rows = top_rankings(self.fills(), {key: key for key in "ABCDE"}, top_n=5)
        self.assertTrue(all(row["rank_buy"] is None for row in rows))
        self.assertTrue(any(row["rank_stage2"] for row in rows))


class WeeklyStateTests(unittest.TestCase):
    def test_advancing_and_buy_plus_sets(self):
        fills = PickRankTests().fills()
        ratings = {"A": "HOLD", "B": "BUY", "C": "STRONG BUY", "D": "SELL", "E": "BUY"}
        [state] = weekly_states(
            fills, {key: key for key in "ABCDE"}, rate=lambda row, day: ratings[row["Security_ID"]]
        )
        self.assertEqual(state["observed_on"], "2026-08-07")
        # Stage 2 and S2 Candidate both count as advancing; Stage 3 does not.
        self.assertEqual(state["advancing"], ["B", "C", "D", "E"])
        self.assertEqual(state["buy_plus"], ["B", "C", "E"])

    def test_an_unrated_week_has_no_buy_plus_set(self):
        fills = PickRankTests().fills().assign(Quality_Coverage_Sufficient=False)
        [state] = weekly_states(fills, {key: key for key in "ABCDE"}, rate=lambda row, day: "BUY")
        self.assertIsNone(state["buy_plus"])


class GatedRatingTests(unittest.TestCase):
    def test_a_clean_row_rates_by_its_score(self):
        from backtest.gates import GateConfig
        from tools.backfill_returns_history import gated_rating

        row = pd.Series(
            {
                "Close": 120.0, "MA200": 100.0, "MA200_Slope_Pct": 1.5, "MA50_To_MA200_Pct": 10.0,
                "Below_MA200_Streak": 0.0, "RS_Market_6M_Pct": 5.0, "RS_Market_12M_Pct": 8.0,
                "Quality_Percentile": 85.0, "Growth_Percentile": 75.0, "Momentum_Percentile": 80.0,
                "Quality_Coverage_Sufficient": True, "Growth_Coverage_Sufficient": True,
                "Value_Coverage_Sufficient": True, "Momentum_Coverage_Sufficient": True,
                "Risk_Coverage_Sufficient": True, "Research_Score": 92.0,
            }
        )
        self.assertEqual(gated_rating(row, None, GateConfig()), "STRONG BUY")
        # Below its MA200 band the BUY gate fails and the rating is capped.
        self.assertEqual(gated_rating(row.copy().replace({120.0: 90.0}), None, GateConfig()), "HOLD")


class AnnotateLiveTests(unittest.TestCase):
    def test_a_missing_stage_is_filled_and_a_published_one_is_not(self):
        from unittest.mock import MagicMock

        from tools.backfill_returns_history import _annotate_market

        # 260 sessions rising steadily: Stage 2 at the end.
        days = pd.bdate_range("2025-09-01", periods=260)
        closes = [100 + index for index in range(260)]
        # No price_series base, so the prices come from the published closes:
        # every session blank except the last, whose stage was published.
        frame_rows = [
            {"observed_on": day.date().isoformat(), "symbol": "UP", "stage": None, "current_price": close}
            for day, close in zip(days[:-1], closes[:-1])
        ] + [{"observed_on": days[-1].date().isoformat(), "symbol": "UP", "stage": "Stage 2", "current_price": closes[-1]}]
        repository = MagicMock()
        repository._paged.side_effect = [frame_rows, []]
        repository._request.return_value = [{"sessions": "[]"}]
        repository._scoped.side_effect = lambda params: params

        fill_stage, age_only = _annotate_market(repository, "NSE")

        self.assertEqual(len(fill_stage), 259)
        self.assertEqual(len(age_only), 1)
        self.assertNotIn("stage", age_only[0])
        self.assertEqual(fill_stage[-1]["stage"], "Stage 2")


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
