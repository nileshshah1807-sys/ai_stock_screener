import datetime as dt
import unittest

from tools.evaluate_outlook_returns import (
    distinct_calls,
    evaluate,
    forward_excess,
    item_key,
    season,
)

DAY = dt.date(2026, 4, 1)
SESSIONS = [DAY + dt.timedelta(days=offset) for offset in range(40)]


def extraction(**sections):
    base = {
        "guidance": {"direction": "none", "scope": "none", "metric": None, "growth_pct": None, "quote": None},
        "order_book": {"value_inr_crore": None, "revenue_cover_years": None, "trend": "unknown", "quote": None},
        "capacity": {"state": "none", "commissioning": None, "quote": None},
        "demand": {"tone": "unknown", "quote": None},
        "margin": {"trend": "unknown", "quote": None},
        "tailwinds": [],
        "headwinds": [],
    }
    return base | sections


class ForwardExcessTests(unittest.TestCase):
    def test_entered_the_session_after_the_call_and_measured_against_the_universe(self):
        closes = {SESSIONS[1]: 100.0, SESSIONS[3]: 110.0}
        universe = {SESSIONS[2]: 1.0, SESSIONS[3]: 1.0}
        # Held on SESSIONS[0]; entered at SESSIONS[1]; two sessions later +10%
        # against a universe that compounded 1% twice.
        excess = forward_excess(closes, SESSIONS, universe, SESSIONS[0], 2)
        self.assertAlmostEqual(excess, (1.10 - 1.01 * 1.01) * 100)

    def test_the_morning_after_the_call_is_not_counted(self):
        closes = {SESSIONS[0]: 50.0, SESSIONS[1]: 100.0, SESSIONS[2]: 100.0}
        universe = {SESSIONS[2]: 0.0}
        self.assertAlmostEqual(forward_excess(closes, SESSIONS, universe, SESSIONS[0], 1), 0.0)

    def test_a_missing_close_or_universe_session_is_no_measurement(self):
        universe = dict.fromkeys(SESSIONS, 0.0)
        self.assertIsNone(forward_excess({SESSIONS[1]: 100.0}, SESSIONS, universe, SESSIONS[0], 2))
        closes = {SESSIONS[1]: 100.0, SESSIONS[3]: 101.0}
        self.assertIsNone(forward_excess(closes, SESSIONS, {SESSIONS[3]: 0.0}, SESSIONS[0], 2))
        # Past the end of the calendar.
        self.assertIsNone(forward_excess(closes, SESSIONS, universe, SESSIONS[-2], 5))


class GroupingTests(unittest.TestCase):
    def test_a_named_tailwind_or_headwind_is_one_item(self):
        self.assertEqual(item_key("tailwind: new plant"), "tailwind")
        self.assertEqual(item_key("headwind: freight costs"), "headwind")
        self.assertEqual(item_key("guidance raised"), "guidance raised")

    def test_seasons_follow_the_calendar_quarter_of_the_call(self):
        self.assertEqual(season(dt.date(2026, 5, 20)), "Apr-Jun 2026")
        self.assertEqual(season(dt.date(2026, 9, 30)), "Jul-Sep 2026")

    def test_a_call_stored_twice_is_counted_once_as_its_newest_reading(self):
        rows = [
            {"symbol": "AAA", "call_date": "2026-08-10", "created_at": "2026-08-10T20:00", "outlook_score": 60},
            {"symbol": "AAA", "call_date": "2026-08-14", "created_at": "2026-08-15T09:00", "outlook_score": 66},
            {"symbol": "AAA", "call_date": "2026-11-10", "created_at": "2026-11-10T20:00", "outlook_score": 70},
            {"symbol": "BBB", "call_date": "2026-08-10", "created_at": "2026-08-10T20:00", "outlook_score": 55},
        ]
        kept = distinct_calls(rows)
        self.assertEqual(sorted((row["symbol"], row["outlook_score"]) for row in kept), [("AAA", 66), ("AAA", 70), ("BBB", 55)])


class EvaluateTests(unittest.TestCase):
    def test_a_score_that_orders_the_returns_ranks_them_and_its_item_shows(self):
        universe = dict.fromkeys(SESSIONS, 0.0)
        calls, closes = [], {}
        for index in range(20):
            symbol = f"S{index:02d}"
            raised = index >= 10
            calls.append({
                "symbol": symbol, "day": SESSIONS[0], "outlook_score": 50 + index, "verified_fields": 2,
                "extraction": extraction(guidance={
                    "direction": "raised" if raised else "none", "scope": "company", "metric": "revenue",
                    "growth_pct": None, "quote": "q" if raised else None,
                }),
            })
            closes[symbol] = {SESSIONS[1]: 100.0, SESSIONS[6]: 100.0 + index}

        report = evaluate(calls, closes, SESSIONS, universe, horizons=[5])
        block = report["seasons"]["Apr-Jun 2026"]["5"]
        self.assertEqual(block["calls"], 20)
        self.assertAlmostEqual(block["spearman"], 1.0)
        self.assertGreater(block["top_fifth_excess"], block["bottom_fifth_excess"])
        self.assertIn("tailwind", block["count_spearman"])
        raised = block["items"]["guidance raised"]
        self.assertEqual(raised["calls"], 10)
        self.assertGreater(raised["difference"], 0)


if __name__ == "__main__":
    unittest.main()
