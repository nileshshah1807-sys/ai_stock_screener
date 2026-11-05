"""Said vs did: which periods can be checked, and what counts as kept."""

import unittest
from datetime import date

from sentiment.promises import KEPT, MISSED, NOT_YET_DUE, flag_on, guidance_outcome, period_quarters, promise_record


def filings(ends, revenue, *, filed="2026-05-20T10:00:00", consolidated=True):
    return [{"period_end": e, "is_consolidated": consolidated, "filed_at": filed, "lines": {"revenue": revenue}} for e in ends]


FY26 = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]
FY25 = ["2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"]


def extraction(period="FY26", pct=18, metric="revenue", scope="company"):
    return {"guidance": {"direction": "raised", "scope": scope, "growth_metric": metric, "growth_pct": pct, "period": period}}


class PeriodTests(unittest.TestCase):
    def test_a_year_and_its_halves(self):
        self.assertEqual(period_quarters("FY27")[0], date(2026, 6, 30))
        self.assertEqual(period_quarters("FY 2027")[-1], date(2027, 3, 31))
        self.assertEqual(period_quarters("H2 FY27"), [date(2026, 12, 31), date(2027, 3, 31)])
        self.assertEqual(period_quarters("H2FY27"), [date(2026, 12, 31), date(2027, 3, 31)])
        self.assertEqual(period_quarters("FY27 H1"), [date(2026, 6, 30), date(2026, 9, 30)])

    def test_anything_else_is_not_guessed(self):
        for text in (None, "", "next year", "Q3", "calendar 2026", "FY26-27", "FY2026-27", "9M FY27", "9MFY27", "Q3 FY27"):
            self.assertIsNone(period_quarters(text))

    def test_the_flag_reads_common_truthy_words_and_is_off_when_unset(self):
        self.assertTrue(flag_on("true"))
        self.assertFalse(flag_on(None))
        self.assertFalse(flag_on("0"))


class OutcomeTests(unittest.TestCase):
    today = date(2026, 6, 1)

    def outcome(self, now, then=100, **kwargs):
        rows = filings(FY26, now) + filings(FY25, then, filed="2025-05-20T10:00:00")
        return guidance_outcome(extraction(**kwargs), rows, self.today)

    def test_growth_at_or_above_guidance_less_the_tolerance_is_kept(self):
        self.assertEqual(self.outcome(120)["outcome"], KEPT)
        self.assertEqual(self.outcome(116.5)["outcome"], KEPT)

    def test_growth_below_that_is_missed(self):
        result = self.outcome(110)
        self.assertEqual((result["outcome"], result["actual_pct"]), (MISSED, 10.0))

    def test_a_year_still_being_filed_is_not_yet_due(self):
        rows = filings(FY26[:2], 120) + filings(FY25, 100)
        self.assertEqual(guidance_outcome(extraction(), rows, self.today)["outcome"], NOT_YET_DUE)

    def test_a_filing_made_after_the_date_is_not_seen(self):
        rows = filings(FY26, 120, filed="2026-05-20T10:00:00") + filings(FY25, 100)
        self.assertEqual(guidance_outcome(extraction(), rows, date(2026, 4, 1))["outcome"], NOT_YET_DUE)

    def test_standalone_is_used_when_consolidated_is_incomplete(self):
        rows = filings(FY26[:2], 999) + filings(FY26, 120, consolidated=False) + filings(FY25, 100, consolidated=False)
        self.assertEqual(guidance_outcome(extraction(), rows, self.today)["outcome"], KEPT)

    def test_what_the_filings_cannot_answer_is_none(self):
        self.assertIsNone(self.outcome(120, scope="segment"))
        self.assertIsNone(self.outcome(120, metric="ebitda"))
        self.assertIsNone(self.outcome(120, pct=None))
        self.assertIsNone(self.outcome(120, then=0))
        self.assertIsNone(guidance_outcome({"guidance": {"direction": "none"}}, [], self.today))


class RecordTests(unittest.TestCase):
    def test_a_period_guided_on_several_calls_is_one_promise(self):
        miss = {"outcome": MISSED, "metric": "revenue", "period": "FY27"}
        again = {"outcome": MISSED, "metric": "revenue", "period": "FY 2027"}
        other = {"outcome": KEPT, "metric": "profit", "period": "FY27"}
        self.assertEqual(promise_record([miss, again, other, None]), {KEPT: 1, MISSED: 1})

    def test_the_latest_guidance_of_a_period_is_the_one_counted(self):
        first = {"outcome": KEPT, "metric": "revenue", "period": "FY27", "guided_pct": 15}
        raised = {"outcome": MISSED, "metric": "revenue", "period": "FY27", "guided_pct": 20}
        self.assertEqual(promise_record([first, raised]), {KEPT: 0, MISSED: 1})


if __name__ == "__main__":
    unittest.main()
