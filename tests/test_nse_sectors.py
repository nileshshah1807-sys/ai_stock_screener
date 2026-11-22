"""NSE's industry classification per symbol (workers/nse_sectors.py)."""

import json
import unittest
from datetime import date

from workers import nse_sectors


def quote_record(sector="Capital Goods"):
    return {
        "secInfo": {
            "macro": "Industrials",
            "sector": sector,
            "industryInfo": "Electrical Equipment",
            "basicIndustry": "Heavy Electrical Equipment",
        }
    }


class ClassifyTests(unittest.TestCase):
    def test_reads_the_four_levels(self):
        self.assertEqual(
            nse_sectors.classification(quote_record()),
            {"macro": "Industrials", "sector": "Capital Goods", "industry": "Electrical Equipment",
             "basic": "Heavy Electrical Equipment"},
        )
        self.assertIsNone(nse_sectors.classification({"secInfo": {"sector": ""}}))

    def test_tries_each_series_until_one_answers(self):
        asked = []

        def quote(symbol, series):
            asked.append(series)
            if series != "SM":
                raise json.JSONDecodeError("Expecting value", "", 0)  # a series it does not trade in
            return quote_record("Services")

        self.assertEqual(nse_sectors.classify(quote, "SHREEOSFM", sme=True)["sector"], "Services")
        self.assertEqual(asked, ["SM"])
        asked.clear()
        self.assertEqual(nse_sectors.classify(quote, "SHREEOSFM", sme=False)["sector"], "Services")
        self.assertEqual(asked, ["EQ", "BE", "BZ", "SM"])

    def test_a_404_is_a_series_it_does_not_trade_in(self):
        def quote(symbol, series):
            if series == "SM":
                raise ConnectionError("https://www.nseindia.in/api/NextApi/apiClient/GetQuoteApi 404: Not Found")
            return quote_record("Services")

        self.assertEqual(nse_sectors.classify(quote, "AARADHYA", sme=True)["sector"], "Services")

    def test_a_failed_session_is_raised_not_read_as_unclassified(self):
        def quote(symbol, series):
            raise ConnectionError("refused")

        with self.assertRaises(ConnectionError):
            nse_sectors.classify(quote, "TDPOWERSYS", sme=False)


class DueTests(unittest.TestCase):
    def test_never_asked_first_then_the_oldest_stale_check_and_no_bse_names(self):
        held = {
            "OLD": {"checked": "2026-09-01"},
            "OLDER": {"checked": "2026-08-01"},
            "RECENT": {"checked": "2026-11-20"},
        }
        universe = [("OLD", False), ("RECENT", False), ("OLDER", False), ("NEW", True), ("X.BO", False)]
        self.assertEqual(
            nse_sectors.due(universe, held, date(2026, 11, 22)),
            [("NEW", True), ("OLDER", False), ("OLD", False)],
        )


class Repo:
    def __init__(self, body=None, unreadable=False):
        self.body, self.unreadable, self.written = body, unreadable, None

    def nse_sectors_object(self):
        if self.unreadable:
            raise ValueError("bad JSON")
        return self.body

    def latest_snapshot_fields(self, fields):
        return "2026-11-20", [{"symbol": "TDPOWERSYS", "is_sme": False}, {"symbol": "GONE", "is_sme": False}]

    def put_nse_sectors_object(self, rows):
        self.written = rows
        return True


class RunTests(unittest.TestCase):
    def test_classifies_and_stamps_symbols_nse_does_not_classify(self):
        def quote(symbol, series):
            if symbol == "GONE":
                raise KeyError("equityResponse")
            return quote_record()

        repo = Repo()
        counts = nse_sectors.run(repo, quote, today=date(2026, 11, 22), pause=0, retry_pause=0)
        self.assertEqual((counts["classified"], counts["unclassified"], counts["held"]), (1, 1, 1))
        self.assertEqual(repo.written[0], {"symbol": "GONE", "checked": "2026-11-22"})
        self.assertEqual(repo.written[1]["sector"], "Capital Goods")

    def test_a_dropped_session_keeps_what_was_learnt(self):
        def quote(symbol, series):
            if symbol == "TDPOWERSYS":
                raise ConnectionError("reset")
            return quote_record()

        held = {"rows": [{"symbol": "GONE", "sector": "Power", "checked": "2026-01-01"}]}
        repo = Repo(held)
        counts = nse_sectors.run(repo, quote, today=date(2026, 11, 22), pause=0, retry_pause=0)
        self.assertEqual(counts["asked"], 0)
        self.assertIsNone(repo.written)  # nothing new learnt, nothing rewritten

    def test_an_endpoint_that_classifies_nothing_stamps_nothing(self):
        class Many(Repo):
            def latest_snapshot_fields(self, fields):
                return "2026-11-20", [{"symbol": f"S{i:03}", "is_sme": False} for i in range(50)]

        def quote(symbol, series):
            if symbol == "S000":
                return quote_record()
            raise json.JSONDecodeError("Expecting value", "", 0)  # a redirect's empty body, every time

        repo = Many()
        counts = nse_sectors.run(repo, quote, today=date(2026, 11, 22), pause=0, retry_pause=0)
        self.assertEqual(counts["asked"], 1 + nse_sectors.FAILED_STREAK)
        self.assertEqual([row["symbol"] for row in repo.written], ["S000"])  # the streak is not stamped

    def test_a_timeout_is_tried_again(self):
        calls = {"n": 0}

        def quote(symbol, series):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("The request timed out.")
            return quote_record()

        repo = Repo()
        counts = nse_sectors.run(repo, quote, today=date(2026, 11, 22), pause=0, retry_pause=0)
        self.assertEqual(counts["classified"], 2)

    def test_a_timeout_opens_a_new_session_and_carries_on(self):
        sessions = []

        class Session:
            def __init__(self):
                sessions.append(self)
                self.asked = 0

            def quote(self, symbol, series):
                self.asked += 1
                if len(sessions) == 1 and self.asked > 1:
                    raise TimeoutError("The request timed out.")  # the first session's cookies run out
                return quote_record()

            def exit(self):
                self.closed = True

        exchange = nse_sectors.Exchange(Session)
        exchange.open()
        repo = Repo()
        counts = nse_sectors.run(repo, exchange.quote, today=date(2026, 11, 22), pause=0, retry_pause=0,
                                 renew=exchange.open)
        self.assertEqual((counts["classified"], len(sessions)), (2, 2))
        self.assertTrue(sessions[0].closed)

    def test_three_timeouts_in_a_row_stop_the_run(self):
        def quote(symbol, series):
            raise TimeoutError("The request timed out.")

        repo = Repo()
        counts = nse_sectors.run(repo, quote, today=date(2026, 11, 22), pause=0, retry_pause=0)
        self.assertEqual(counts["asked"], 0)
        self.assertIsNone(repo.written)

    def test_an_unreadable_object_is_never_overwritten(self):
        repo = Repo(unreadable=True)
        nse_sectors.run(repo, lambda symbol, series: quote_record(), today=date(2026, 11, 22), pause=0)
        self.assertIsNone(repo.written)

    def test_nothing_due_writes_nothing(self):
        rows = [{"symbol": s, "sector": "Power", "checked": "2026-11-21"} for s in ("TDPOWERSYS", "GONE")]
        repo = Repo({"rows": rows})
        self.assertEqual(nse_sectors.run(repo, lambda *a: quote_record(), today=date(2026, 11, 22), pause=0)["asked"], 0)
        self.assertIsNone(repo.written)


if __name__ == "__main__":
    unittest.main()
