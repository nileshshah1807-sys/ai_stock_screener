"""The Concalls page's rows, derived from the stored calls.

The rules worth pinning: one row per call however many transcripts it has; the
filed transcript wins over the recording's; a call keeps the day it was held;
and a call with no score has no standing rather than the lowest one.
"""

import unittest
from datetime import date

from sentiment.outlook import OUTLOOK_VERSION
from workers.concall_feed import build_feed, highlights, management_stance, run

COMPANIES = {"ALPHA": "Alpha Ltd", "BETA": "Beta Ltd"}

EXTRACTION = {
    "guidance": {"direction": "raised", "scope": "company", "metric": "revenue", "growth_pct": 18, "quote": "We now expect eighteen percent growth."},
    "order_book": {"value_inr_crore": None, "revenue_cover_years": None, "trend": "unknown", "quote": None},
    "capacity": {"state": "none", "commissioning": None, "quote": None},
    "demand": {"tone": "weak", "quote": "Demand in the rural market remains weak."},
    "margin": {"trend": "up", "quote": "Margins should improve from here."},
    "tailwinds": [],
    "headwinds": [{"what": "freight costs", "quote": "Freight costs are a headwind."}],
    "points": [],
    "stance": {"view": "optimistic", "quote": "We now expect eighteen percent growth."},
}


def call(symbol, call_date, *, speech=False, tone=None, outlook=None, quarter="2026-09-30", verified=4):
    return {
        "id": f"{symbol}-{call_date}-{speech}",
        "symbol": symbol,
        "quarter": quarter,
        "call_date": call_date,
        "transcript_documents": {"extraction_method": "speech:large-v3-turbo" if speech else "text"},
        "transcript_sentiments": []
        if tone is None
        else [{"overall_score": tone, "guidance_direction": "raised", "created_at": "2026-10-12T15:00:00"}],
        "transcript_outlooks": []
        if outlook is None
        else [{
            "outlook_score": outlook,
            "verified_fields": verified,
            "extraction": EXTRACTION,
            "analysis_version": OUTLOOK_VERSION,
            "created_at": "2026-10-12T15:05:00",
        }],
    }


class HighlightTests(unittest.TestCase):
    def test_the_three_statements_that_moved_the_outlook_most_one_per_quote(self):
        chosen = highlights(EXTRACTION)
        # Guidance raised (+15) and the growth it guided (+6) share a quote.
        self.assertEqual(
            [(item["text"], item["tone"]) for item in chosen],
            [("guidance raised", "positive"), ("demand outlook weak", "negative"), ("margin outlook improving", "positive")],
        )
        self.assertEqual(chosen[0]["quote"], "We now expect eighteen percent growth.")

    def test_an_extraction_of_another_shape_has_no_highlights(self):
        self.assertEqual(highlights({"guidance": None}), [])
        self.assertEqual(highlights(None), [])


class StanceTests(unittest.TestCase):
    """Management's sentiment is the band of the call's outlook score."""

    def outlook(self, score, verified=4):
        return {"outlook_score": score, "verified_fields": verified, "extraction": EXTRACTION}

    def test_the_band_of_the_score_with_the_statement_that_moved_it_that_way(self):
        # Guidance raised (+15) is the largest gain; weak demand (-10) the largest loss.
        self.assertEqual(management_stance(self.outlook(82)), ("bullish", "We now expect eighteen percent growth."))
        self.assertEqual(management_stance(self.outlook(70)), ("optimistic", "We now expect eighteen percent growth."))
        self.assertEqual(management_stance(self.outlook(62)), ("neutral", None))
        self.assertEqual(management_stance(self.outlook(52)), ("cautious", "Demand in the rural market remains weak."))
        self.assertEqual(management_stance(self.outlook(40)), ("bearish", "Demand in the rural market remains weak."))

    def test_a_stance_stored_by_an_earlier_reading_is_not_what_the_page_shows(self):
        # EXTRACTION carries {"view": "optimistic"} from when the model was asked.
        self.assertEqual(management_stance(self.outlook(40))[0], "bearish")

    def test_a_call_whose_outlook_verified_nothing_has_no_stance(self):
        for outlook in (self.outlook(50, verified=0), self.outlook(None), {}, None):
            self.assertEqual(management_stance(outlook), (None, None))


class OutlookDetailTests(unittest.TestCase):
    """The stock page's panel reads these fields, from a run or from here."""

    def detail(self, *stored):
        rows = build_feed(list(stored), COMPANIES)
        return {(row["symbol"], row["quarter"]): row["outlook_detail"] for row in rows}

    def test_a_call_carries_its_score_and_every_scored_item_under_the_runs_names(self):
        detail = self.detail(call("ALPHA", "2026-10-12", speech=True, tone=60, outlook=67))[("ALPHA", "2026-09-30")]
        self.assertEqual(detail["Transcript_Call_Date"], "2026-10-12")
        self.assertEqual(detail["Transcript_Outlook_Score"], 67.0)
        self.assertIn(
            {"reason": "guidance raised", "points": 15.0, "quote": "We now expect eighteen percent growth."},
            detail["Transcript_Outlook_Points"],
        )
        self.assertNotIn("Transcript_Outlook_Previous_Score", detail)

    def test_the_quarter_before_is_compared_as_a_run_would(self):
        details = self.detail(
            call("ALPHA", "2026-10-12", tone=60, outlook=67),
            call("ALPHA", "2026-07-15", tone=55, outlook=53, quarter="2026-06-30"),
            call("BETA", "2026-07-20", tone=55, outlook=80, quarter="2026-06-30"),
        )
        detail = details[("ALPHA", "2026-09-30")]
        self.assertEqual(
            (detail["Transcript_Outlook_Previous_Call_Date"], detail["Transcript_Outlook_Previous_Score"]),
            ("2026-07-15", 53.0),
        )
        self.assertEqual(detail["Transcript_Outlook_QoQ_Delta"], 14.0)
        self.assertTrue(all("change" in item for item in detail["Transcript_Outlook_QoQ_Items"]))
        # The earlier call has nothing before it, and another company's call is not it.
        self.assertNotIn("Transcript_Outlook_Previous_Score", details[("ALPHA", "2026-06-30")])

    def test_a_second_document_from_the_same_season_is_not_the_quarter_before(self):
        details = self.detail(
            call("ALPHA", "2026-10-12", tone=60, outlook=67),
            call("ALPHA", "2026-09-20", tone=55, outlook=53, quarter="2026-06-30"),
        )
        self.assertNotIn("Transcript_Outlook_Previous_Score", details[("ALPHA", "2026-09-30")])

    def test_an_outlook_with_nothing_verified_has_no_detail(self):
        details = self.detail(
            call("ALPHA", "2026-10-12", tone=60, outlook=50, verified=0),
            call("BETA", "2026-10-11", tone=60),
        )
        self.assertIsNone(details[("ALPHA", "2026-09-30")])
        self.assertIsNone(details[("BETA", "2026-09-30")])


class FeedTests(unittest.TestCase):
    def test_a_call_read_from_its_recording_says_so(self):
        (row,) = build_feed([call("ALPHA", "2026-10-12", speech=True, tone=61.5, outlook=68)], COMPANIES)
        self.assertEqual(
            (row["symbol"], row["company"], row["call_date"], row["source"]),
            ("ALPHA", "Alpha Ltd", "2026-10-12", "recording"),
        )
        self.assertEqual((row["tone_score"], row["outlook_score"], row["guidance_direction"]), (61.5, 68.0, "raised"))
        self.assertEqual(len(row["highlights"]), 3)
        self.assertEqual(row["management_stance"], "optimistic")

    def test_the_filed_transcript_wins_and_the_call_keeps_the_day_it_was_held(self):
        rows = build_feed(
            [
                call("ALPHA", "2026-10-12", speech=True, tone=61.5),
                call("ALPHA", "2026-10-16", tone=58.0),
            ],
            COMPANIES,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["source"], rows[0]["call_date"], rows[0]["tone_score"]), ("transcript", "2026-10-12", 58.0))

    def test_the_day_held_survives_the_recording_transcript_being_removed(self):
        (row,) = build_feed(
            [call("ALPHA", "2026-10-16", tone=58.0)], COMPANIES, {("ALPHA", "2026-09-30"): "2026-10-12"}
        )
        self.assertEqual((row["source"], row["call_date"]), ("transcript", "2026-10-12"))

    def test_an_unscored_call_has_no_standing(self):
        rows = build_feed(
            [
                call("ALPHA", "2026-10-12", tone=70),
                call("BETA", "2026-10-11", tone=50),
                call("GAMMA", "2026-10-10"),
            ],
            COMPANIES,
        )
        by_symbol = {row["symbol"]: row for row in rows}
        self.assertEqual(by_symbol["ALPHA"]["tone_percentile"], 75.0)
        self.assertEqual(by_symbol["BETA"]["tone_percentile"], 25.0)
        self.assertIsNone(by_symbol["GAMMA"]["tone_percentile"])
        self.assertIsNone(by_symbol["GAMMA"]["tone_score"])
        self.assertIsNone(by_symbol["GAMMA"]["company"])
        # No outlook read, so no stance -- not a neutral one.
        self.assertIsNone(by_symbol["GAMMA"]["management_stance"])

    def test_newest_call_first_and_calls_without_a_date_are_left_out(self):
        rows = build_feed(
            [
                call("BETA", "2026-10-11", tone=50),
                call("ALPHA", "2026-10-12", tone=70),
                call("ALPHA", None, tone=40),
            ],
            COMPANIES,
        )
        self.assertEqual([row["symbol"] for row in rows], ["ALPHA", "BETA"])

    def test_a_quarter_stored_as_a_label_or_not_at_all_is_dated_from_the_call(self):
        # Early rows carry "2026-Q3"; the feed's quarter is a date column.
        rows = build_feed(
            [
                call("ALPHA", "2026-07-20", tone=40, quarter="2026-Q3"),
                call("BETA", "2026-07-22", tone=45, quarter=None),
                # The same call stored twice, once under each form, is one row.
                call("ALPHA", "2026-07-24", tone=42, quarter="2026-06-30"),
            ],
            COMPANIES,
        )
        self.assertEqual(
            sorted((row["symbol"], row["quarter"]) for row in rows),
            [("ALPHA", "2026-06-30"), ("BETA", "2026-06-30")],
        )

    def test_an_outlook_from_another_version_is_not_shown(self):
        stored = call("ALPHA", "2026-10-12", tone=60, outlook=70)
        stored["transcript_outlooks"][0]["analysis_version"] = "outlook-v0"
        (row,) = build_feed([stored], COMPANIES)
        self.assertIsNone(row["outlook_score"])
        self.assertEqual(row["highlights"], [])


class FakeRepository:
    market = "NSE"

    def __init__(self, calls, readable=True, reject_stance=False):
        self.calls = calls
        self.readable = readable
        self.reject_stance = reject_stance
        self.written = None

    def concall_call_dates(self):
        if not self.readable:
            raise RuntimeError("relation concall_feed does not exist")
        return {}

    def calls_since(self, since):
        self.since = since
        return self.calls

    def snapshot_companies(self):
        return COMPANIES

    def replace_concall_feed(self, rows, since):
        if self.reject_stance and any("management_stance" in row or "outlook_detail" in row for row in rows):
            raise RuntimeError("Could not find the 'management_stance' column")
        self.written = (rows, since)
        return len(rows)


class RunTests(unittest.TestCase):
    def test_the_window_is_written(self):
        repository = FakeRepository([call("ALPHA", "2026-10-12", speech=True, tone=60)])
        counts = run(repository, today=date(2026, 10, 12))
        self.assertEqual(counts, {"calls": 1, "from_recording": 1, "written": 1})
        self.assertEqual(repository.since, "2026-03-26")
        self.assertEqual(repository.written[1], "2026-03-26")

    def test_a_table_without_the_stance_columns_still_gets_its_calls(self):
        repository = FakeRepository([call("ALPHA", "2026-10-12", tone=60, outlook=64)], reject_stance=True)
        self.assertEqual(run(repository, today=date(2026, 10, 12))["written"], 1)
        (row,) = repository.written[0]
        self.assertNotIn("management_stance", row)
        self.assertNotIn("outlook_detail", row)
        self.assertEqual(row["outlook_score"], 64.0)

    def test_a_dry_run_writes_nothing(self):
        repository = FakeRepository([call("ALPHA", "2026-10-12", tone=60)])
        self.assertEqual(run(repository, today=date(2026, 10, 12), dry_run=True)["written"], 0)
        self.assertIsNone(repository.written)

    def test_a_missing_table_is_a_warning_not_a_failure(self):
        repository = FakeRepository([call("ALPHA", "2026-10-12", tone=60)], readable=False)
        self.assertEqual(run(repository, today=date(2026, 10, 12)), {"calls": 0, "from_recording": 0, "written": 0})


if __name__ == "__main__":
    unittest.main()
