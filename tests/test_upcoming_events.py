"""Upcoming results dates and earnings calls: what is read from a notice and what is written.

The rules worth pinning: an investor meet is not an earnings call, a time is
kept only when it is India time, a rescheduled meeting replaces the old date,
a passed date is cleared, and a notice already read is not fetched again.
"""

import tempfile
import unittest
from datetime import UTC, date, datetime, time
from pathlib import Path

from workers.upcoming_events import (
    call_schedule,
    collect_notices,
    is_call_notice,
    is_earnings_call,
    merge,
    result_dates,
    run,
)

FILED = date(2026, 10, 31)
TODAY = date(2026, 10, 31)
NOW = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)


class CallScheduleTests(unittest.TestCase):
    def read(self, text, filed=FILED):
        return call_schedule(text, filed=filed)

    def test_formats_seen_in_notices(self):
        cases = {
            "the Company will host an Earnings Conference call on Thursday, November 05, 2026, at 12.00 Noon IST.": (5, time(12, 0)),
            "a conference call has been organized on Thursday, November 05, 2026 at 06:00 P.M. (IST) to discuss": (5, time(18, 0)),
            "call to be held on Friday, November 06, 2026 at 12:30 PM (IST). This is for": (6, time(12, 30)),
            "scheduled to be held on Friday, 6th November, 2026 at 4.30 PM IST to discuss": (6, time(16, 30)),
            "scheduled on Thursday, 5th November, 2026 at 02:00 P.M. in relation to": (5, time(14, 0)),
            "to be held on 06 November 2026 at 16:00 hrs IST": (6, time(16, 0)),
        }
        for text, (day, clock) in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.read("October 31, 2026 To, NSE. " + text), (date(2026, 11, day), clock))

    def test_the_letters_own_date_is_not_the_call(self):
        self.assertIsNone(self.read("31st October, 2026 Sub: Intimation regarding conference call. Dear Sir"))

    def test_a_date_without_a_time_is_kept_as_a_date(self):
        self.assertEqual(self.read("October 31, 2026 the call is on 5th Nov, 2026 at the usual dial-in"), (date(2026, 11, 5), None))

    def test_a_time_in_another_zone_keeps_the_date_alone(self):
        self.assertEqual(self.read("call on November 05, 2026 at 8:00 AM EST"), (date(2026, 11, 5), None))

    def test_a_bare_number_or_an_ambiguous_hour_is_not_a_time(self):
        self.assertEqual(self.read("call on 5 November 2026 under Regulation 30 at 4.30"), (date(2026, 11, 5), None))

    def test_a_dotted_date_is_not_read_as_a_time(self):
        self.assertEqual(self.read("call on 05.11.2026"), (date(2026, 11, 5), None))

    def test_the_time_may_come_before_its_date(self):
        self.assertEqual(self.read("at 4 PM on 5 November 2026 the call"), (date(2026, 11, 5), time(16, 0)))


class NoticeKindTests(unittest.TestCase):
    def notice(self, text, desc="Analysts/Institutional Investor Meet/Con. Call Updates"):
        return {"desc": desc, "attchmntText": text}

    def test_schedule_notices_pass_and_the_rest_do_not(self):
        self.assertTrue(is_call_notice(self.notice("X has informed the Exchange about Schedule of meet")))
        self.assertTrue(is_call_notice(self.notice("Earnings Call Intimation Q2 FY27")))
        for text in ("Link of Recording", "Earnings Call Transcript - Q2 FY27", "Presentation", "Audio recording of the call"):
            with self.subTest(text=text):
                self.assertFalse(is_call_notice(self.notice(text)))
        self.assertFalse(is_call_notice(self.notice("x", desc="Outcome of Board Meeting")))

    def test_an_earnings_call_is_told_from_an_investor_meet(self):
        call = "we will host an Earnings Conference call to discuss the financial results for the quarter ended September 30, 2026"
        meet = "the Company will be meeting individual investors and analysts, one-on-one, at a broker's conference"
        self.assertTrue(is_earnings_call(call))
        self.assertFalse(is_earnings_call(meet))
        self.assertFalse(is_earnings_call("a conference call with Rating agency for the debt programme"))


def meeting(symbol, day, purpose="Financial Results", filed="26-Oct-2026 18:00:00"):
    return {"bm_symbol": symbol, "bm_date": day, "bm_purpose": purpose, "bm_timestamp": filed, "sm_name": symbol.title()}


class ResultDateTests(unittest.TestCase):
    def test_only_result_meetings_dated_today_or_later(self):
        found = result_dates(
            [
                meeting("AAA", "03-Nov-2026", "Financial Results/Dividend"),
                meeting("BBB", "03-Nov-2026", "Board Meeting Intimation"),
                meeting("CCC", "30-Oct-2026"),
                meeting("DDD", "31-Oct-2026"),
            ],
            today=TODAY,
        )
        self.assertEqual(set(found), {"AAA", "DDD"})
        self.assertEqual(found["AAA"]["result_purpose"], "Financial Results/Dividend")

    def test_the_later_intimation_wins_a_reschedule(self):
        found = result_dates(
            [
                meeting("AAA", "03-Nov-2026", filed="26-Oct-2026 18:00:00"),
                meeting("AAA", "07-Nov-2026", filed="29-Oct-2026 09:00:00"),
            ],
            today=TODAY,
        )
        self.assertEqual(found["AAA"]["next_result_date"], "2026-11-07")


def call_row(**fields):
    return {"symbol": "AAA", "company": "Aaa", "next_result_date": None, "result_purpose": None,
            "next_call_at": None, "next_call_date": None, "call_source_url": None,
            "updated_at": "2026-10-30T10:00:00+00:00", **fields}


class MergeTests(unittest.TestCase):
    def merged(self, stored, results, notices):
        return merge(stored, results, notices, today=TODAY, checked_at=NOW)

    def test_a_new_call_and_result_make_one_row(self):
        record = {"attchmntFile": "https://x/a.pdf", "sm_name": "Aaa"}
        rows = self.merged(
            {},
            {"AAA": {"company": "Aaa", "next_result_date": "2026-11-03", "result_purpose": "Financial Results"}},
            {"AAA": (record, (date(2026, 11, 5), time(12, 0)))},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["next_call_at"], "2026-11-05T12:00:00+05:30")
        self.assertIsNone(rows[0]["next_call_date"])
        self.assertEqual(rows[0]["call_source_url"], "https://x/a.pdf")

    def test_a_date_only_call_sets_the_date_column_not_the_time(self):
        rows = self.merged({}, {}, {"AAA": ({"attchmntFile": "u"}, (date(2026, 11, 5), None))})
        self.assertEqual((rows[0]["next_call_at"], rows[0]["next_call_date"]), (None, "2026-11-05"))

    def test_an_unchanged_row_is_not_written_again(self):
        stored = {"AAA": call_row(next_result_date="2026-11-03", result_purpose="Financial Results",
                                  next_call_at="2026-11-05T06:30:00+00:00", call_source_url="u")}
        rows = self.merged(
            stored,
            {"AAA": {"company": "Aaa", "next_result_date": "2026-11-03", "result_purpose": "Financial Results"}},
            {},
        )
        self.assertEqual(rows, [])

    def test_a_passed_date_is_cleared(self):
        stored = {"AAA": call_row(next_result_date="2026-10-30", next_call_date="2026-10-30", call_source_url="u")}
        (row,) = self.merged(stored, {}, {})
        self.assertEqual((row["next_result_date"], row["next_call_date"], row["call_source_url"]), (None, None, None))

    def test_a_notice_with_no_call_keeps_the_call_the_stock_had(self):
        stored = {"AAA": call_row(next_call_date="2026-11-05", call_source_url="old")}
        (row,) = self.merged(stored, {}, {"AAA": ({"attchmntFile": "meet"}, None)})
        self.assertEqual((row["next_call_date"], row["call_source_url"]), ("2026-11-05", "old"))
        self.assertEqual(row["updated_at"], "2026-10-31T08:00:00+00:00")

    def test_a_result_date_that_left_the_feed_is_cleared(self):
        stored = {"AAA": call_row(next_result_date="2026-11-03", result_purpose="Financial Results")}
        (row,) = self.merged(stored, {}, {})
        self.assertIsNone(row["next_result_date"])


def notice(symbol, filed, url=None):
    return {"symbol": symbol, "an_dt": filed, "attchmntFile": url or f"https://x/{symbol}.pdf", "sm_name": symbol}


class CollectNoticeTests(unittest.TestCase):
    def collect(self, records, stored=None, read=None, limit=60):
        reads = []

        def fake_read(record, folder, *, filed):
            reads.append(record["symbol"])
            return (read or {}).get(record["attchmntFile"], (date(2026, 11, 5), None))

        found = collect_notices(
            stored or {}, folder=Path(tempfile.gettempdir()), pause=0, limit=limit,
            discover=lambda days, matches: records, read=fake_read,
        )
        return found, reads

    def test_a_notice_older_than_the_last_look_is_not_fetched(self):
        stored = {"AAA": call_row(updated_at="2026-10-31T05:00:00+00:00")}  # 10:30 IST
        found, reads = self.collect(
            [notice("AAA", "31-Oct-2026 09:00:00"), notice("BBB", "31-Oct-2026 09:00:00")], stored
        )
        self.assertEqual(reads, ["BBB"])
        self.assertEqual(set(found), {"BBB"})

    def test_the_newest_earnings_call_notice_stands(self):
        records = [notice("AAA", "31-Oct-2026 11:00:00", "new"), notice("AAA", "30-Oct-2026 11:00:00", "old")]
        found, reads = self.collect(records)
        self.assertEqual(reads, ["AAA"])
        self.assertEqual(found["AAA"][0]["attchmntFile"], "new")

    def test_an_investor_meet_falls_through_to_an_older_call_notice(self):
        records = [notice("AAA", "31-Oct-2026 11:00:00", "meet"), notice("AAA", "30-Oct-2026 11:00:00", "call")]
        found, _ = self.collect(records, read={"meet": None, "call": (date(2026, 11, 6), time(16, 0))})
        self.assertEqual(found["AAA"][0]["attchmntFile"], "call")

    def test_a_stock_with_only_investor_meets_is_still_marked_as_looked_at(self):
        found, _ = self.collect([notice("AAA", "31-Oct-2026 11:00:00")], read={"https://x/AAA.pdf": None})
        self.assertEqual(found["AAA"][1], None)

    def test_a_download_failure_leaves_the_stock_untouched(self):
        def failing(record, folder, *, filed):
            raise ValueError("403")

        found = collect_notices(
            {}, folder=Path(tempfile.gettempdir()), pause=0,
            discover=lambda days, matches: [notice("AAA", "31-Oct-2026 11:00:00")], read=failing,
        )
        self.assertEqual(found, {})

    def test_a_run_reads_at_most_the_limit_newest_first(self):
        records = [notice(f"S{n}", f"31-Oct-2026 {10 + n:02d}:00:00") for n in range(3)]
        _, reads = self.collect(records, limit=2)
        self.assertEqual(reads, ["S2", "S1"])


class FakeRepo:
    market = "NSE"

    def __init__(self, stored=None, unreadable=False):
        self.stored, self.unreadable, self.written = stored or {}, unreadable, []

    def upcoming_events(self):
        if self.unreadable:
            raise RuntimeError("relation does not exist")
        return self.stored

    def upsert_upcoming_events(self, rows):
        self.written += rows
        return len(rows)


class RunTests(unittest.TestCase):
    def run_with(self, repo, **kwargs):
        from unittest.mock import patch

        with (
            patch("workers.upcoming_events.fetch_board_meetings", return_value=[meeting("AAA", "03-Nov-2026")]),
            patch("workers.upcoming_events.discover_nse_announcements", return_value=[]),
        ):
            return run(repo, now=NOW, **kwargs)

    def test_a_dry_run_writes_nothing(self):
        repo = FakeRepo()
        counts = self.run_with(repo, dry_run=True)
        self.assertEqual((counts["results"], counts["written"], repo.written), (1, 0, []))

    def test_rows_are_written(self):
        repo = FakeRepo()
        self.assertEqual(self.run_with(repo)["written"], 1)
        self.assertEqual(repo.written[0]["next_result_date"], "2026-11-03")

    def test_a_missing_table_is_a_warning_not_a_failure(self):
        with self.assertLogs("workers.upcoming_events", "WARNING"):
            self.assertEqual(self.run_with(FakeRepo(unreadable=True))["written"], 0)


if __name__ == "__main__":
    unittest.main()
