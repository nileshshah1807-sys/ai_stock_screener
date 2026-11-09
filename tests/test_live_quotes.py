"""Intraday quotes for display.

What must hold: the worker does nothing outside the session or on a holiday,
a change of unit is never published as a move, one failed constituent list
never wipes the others, and a vendor outage fails the run instead of
quietly leaving prices stale.
"""

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

from screener.index_members import parse_nse_index_csv
from screener.market_calendar import calendar_rows, parse_nse_holidays
from screener.markets import resolve as resolve_market
from screener.numeric import round_half_up
from workers.live_quotes import (
    in_session,
    member_rows,
    members_due,
    quote_row,
    run,
    yahoo_quotes,
)

NSE = resolve_market("NSE")
US = resolve_market("US")

# 11:45 IST on a Friday.
IN_SESSION = datetime(2026, 10, 16, 6, 15, tzinfo=UTC)
# 11:44 IST that day, as a vendor epoch.
TRADED = int(datetime(2026, 10, 16, 6, 14, tzinfo=UTC).timestamp())
FETCHED = "2026-10-16T06:15:00+00:00"


def quote(price, previous=100.0, traded=TRADED, **extra):
    return {
        "regularMarketPrice": price,
        "regularMarketPreviousClose": previous,
        "regularMarketTime": traded,
        **extra,
    }


def must_not_fetch(*args):
    raise AssertionError("must not fetch")


class FakeRepo:
    def __init__(self, snapshot=(), members=(), refreshed_at="2026-10-16T03:00:00+00:00"):
        self.snapshot = list(snapshot)
        self.members = list(members)
        self.refreshed_at = refreshed_at
        self.quotes = None
        self.replaced = None
        self.pruned = None

    def index_members_refreshed_at(self):
        return self.refreshed_at

    def latest_snapshot_symbols(self):
        return self.snapshot

    def index_member_symbols(self):
        return self.members

    def replace_index_members(self, rows):
        self.replaced = rows
        return len(rows)

    def upsert_live_quotes(self, rows):
        self.quotes = rows
        return len(rows)

    def prune_live_quotes(self, before):
        self.pruned = before


def fetcher(quotes):
    requested = []

    def fetch(tickers):
        requested.extend(tickers)
        return quotes

    return fetch, requested


class SessionTests(unittest.TestCase):
    def test_session_hours_with_margin(self):
        def at(hour, minute, day=16):
            # IST is UTC+5:30.
            return datetime(2026, 10, day, hour, minute, tzinfo=UTC)

        self.assertFalse(in_session(at(3, 30), NSE))  # 09:00 IST
        self.assertTrue(in_session(at(3, 35), NSE))  # 09:05, the pre-open margin
        self.assertTrue(in_session(IN_SESSION, NSE))
        self.assertTrue(in_session(at(10, 10), NSE))  # 15:40, the closing margin
        self.assertFalse(in_session(at(10, 15), NSE))  # 15:45
        self.assertFalse(in_session(at(6, 15, day=17), NSE))  # a Saturday

    def test_each_market_in_its_own_clock(self):
        # 11:45 IST is 02:15 in New York.
        self.assertFalse(in_session(IN_SESSION, US))
        self.assertTrue(in_session(datetime(2026, 10, 16, 15, 0, tzinfo=UTC), US))


MUHURAT = {"day": "2026-11-08", "kind": "special_session", "reason": "Muhurat trading", "session_open": "14:20", "session_close": "15:30"}
HOLIDAY = {"day": "2026-10-16", "kind": "holiday", "reason": "Test holiday", "session_open": None, "session_close": None}
# 14:30 IST on Sunday 8 November 2026.
SUNDAY_MUHURAT = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


class CalendarTests(unittest.TestCase):
    def test_special_session_runs_on_a_sunday_in_its_own_hours(self):
        self.assertFalse(in_session(SUNDAY_MUHURAT, NSE))
        self.assertTrue(in_session(SUNDAY_MUHURAT, NSE, MUHURAT))
        self.assertFalse(in_session(datetime(2026, 11, 8, 4, 0, tzinfo=UTC), NSE, MUHURAT))  # 09:30, normal hours do not apply

    def test_a_holiday_is_out_of_session_and_fetches_nothing(self):
        self.assertFalse(in_session(IN_SESSION, NSE, HOLIDAY))
        repo = FakeRepo(snapshot=["AAA"])
        repo.market_calendar = lambda since: [{**HOLIDAY, "refreshed_at": FETCHED}]
        self.assertEqual(run(repo, NSE, now=IN_SESSION, fetch_quotes=must_not_fetch)["status"], "outside_session")

    def test_a_missing_calendar_keeps_the_weekday_rule(self):
        self.assertEqual(run(FakeRepo(snapshot=["AAA"]), NSE, now=SUNDAY_MUHURAT, fetch_quotes=must_not_fetch)["status"], "outside_session")

    def test_a_stale_calendar_is_rebuilt_and_a_failed_feed_leaves_it_alone(self):
        repo = FakeRepo(snapshot=["AAA"])
        repo.market_calendar = lambda since: []
        written = []
        repo.replace_market_calendar = written.append
        run(repo, NSE, now=SUNDAY_MUHURAT, fetch_quotes=lambda t: {}, fetch_holidays=lambda: None)
        self.assertEqual(written, [])  # no feed, no rebuild: it would drop the holidays
        run(repo, NSE, now=SUNDAY_MUHURAT, fetch_quotes=lambda t: {}, fetch_holidays=lambda: {"CM": []})
        self.assertEqual([r["day"] for r in written[0]], ["2026-11-08"])

    def test_nse_list_keeps_weekday_holidays_and_the_special_session_wins_its_day(self):
        payload = {"CM": [
            {"tradingDate": "24-Nov-2026", "description": "Prakash Gurpurb Sri Guru Nanak Dev"},
            {"tradingDate": "08-Nov-2026", "description": "Diwali Laxmi Pujan*"},
            {"tradingDate": "15-Feb-2026", "description": "Mahashivratri"},
        ]}
        self.assertEqual([r["day"] for r in parse_nse_holidays(payload)], ["2026-11-24"])  # the Sundays are not holidays
        kinds = {r["day"]: r["kind"] for r in calendar_rows("NSE", payload)}
        self.assertEqual(kinds, {"2026-11-08": "special_session", "2026-11-24": "holiday"})
        self.assertIn("2026-11-26", {r["day"] for r in calendar_rows("US")})


class QuoteRowTests(unittest.TestCase):
    def test_row_from_a_quote(self):
        extra = {"regularMarketDayHigh": 102, "regularMarketDayLow": 99.5, "regularMarketVolume": 1234}
        row = quote_row("AAA", quote(101.5, **extra), NSE, "stock", FETCHED)
        self.assertEqual(row["price"], 101.5)
        self.assertEqual(row["change_pct"], 1.5)
        self.assertEqual(row["day_high"], 102)
        self.assertEqual(row["volume"], 1234)
        self.assertEqual(row["traded_at"], "2026-10-16T06:14:00+00:00")
        self.assertEqual(row["session"], "2026-10-16")
        self.assertEqual(row["fetched_at"], FETCHED)

    def test_session_is_the_exchange_date(self):
        # 23:00 UTC is already the next morning in India.
        late = int(datetime(2026, 10, 15, 23, 0, tzinfo=UTC).timestamp())
        row = quote_row("AAA", quote(100, traded=late), NSE, "stock", FETCHED)
        self.assertEqual(row["session"], "2026-10-16")

    def test_no_price_no_row(self):
        for bad in (None, 0, -1, "n/a", float("nan")):
            self.assertIsNone(quote_row("AAA", quote(bad), NSE, "stock", FETCHED), bad)
        self.assertIsNone(quote_row("AAA", quote(100, traded=None), NSE, "stock", FETCHED))

    def test_previous_close_from_the_days_change_not_the_stale_field(self):
        # The index shape: the field names an older close, the change is right.
        stale = quote(23124.05, previous=22622.7, regularMarketChange=126.7)
        row = quote_row("Index", stale, NSE, "index", FETCHED)
        self.assertEqual(row["previous_close"], 22997.35)
        self.assertEqual(row["change_pct"], round_half_up((23124.05 / 22997.35 - 1) * 100, 4))

    def test_missing_previous_close_keeps_the_price(self):
        row = quote_row("AAA", quote(100, previous=None), NSE, "stock", FETCHED)
        self.assertEqual(row["price"], 100)
        self.assertIsNone(row["change_pct"])

    def test_change_past_the_auction_cap_is_withheld(self):
        # Half the previous close on NSE: a split's ex-date, not a trade.
        split = quote_row("AAA", quote(50, previous=100), NSE, "stock", FETCHED)
        self.assertEqual(split["price"], 50)
        self.assertIsNone(split["change_pct"])
        # Within the cap it is a move.
        capped = quote_row("AAA", quote(120, previous=100), NSE, "stock", FETCHED)
        self.assertEqual(capped["change_pct"], 20)

    def test_uncapped_market_publishes_any_move(self):
        row = quote_row("AAA", quote(50, previous=100), US, "stock", FETCHED)
        self.assertEqual(row["change_pct"], -50)

    def test_an_index_is_never_capped(self):
        row = quote_row("Index", quote(50, previous=100), NSE, "index", FETCHED)
        self.assertEqual(row["change_pct"], -50)


class FetchTests(unittest.TestCase):
    def test_batches_and_a_failed_batch(self):
        calls = []

        class Response:
            def __init__(self, symbols):
                self.symbols = symbols

            def raise_for_status(self):
                if "C.NS" in self.symbols:
                    raise RuntimeError("503")

            def json(self):
                return {"quoteResponse": {"result": [{"symbol": s} for s in self.symbols]}}

        def get(url, params, timeout):
            symbols = params["symbols"].split(",")
            calls.append(symbols)
            return Response(symbols)

        with mock.patch("workers.live_quotes.time.sleep"):
            quotes = yahoo_quotes(["A.NS", "B.NS", "C.NS"], batch_size=2, get=get)
        self.assertEqual(sorted(quotes), ["A.NS", "B.NS"])
        # The failing batch is retried once, then skipped.
        self.assertEqual(calls, [["A.NS", "B.NS"], ["C.NS"], ["C.NS"]])


class MembersTests(unittest.TestCase):
    def test_parse_nse_constituent_file(self):
        text = (
            "﻿Company Name,Industry, Symbol ,Series,ISIN Code\n"
            "Alpha Ltd.,Services,AAA,EQ,INE000A01010\n"
            ",,,,\n"
            "Alpha Ltd.,Services,AAA,EQ,INE000A01010\n"
            "Beta Ltd.,Metals,bbb,EQ,INE000B01010\n"
        )
        self.assertEqual(parse_nse_index_csv(text), [("AAA", "Alpha Ltd."), ("BBB", "Beta Ltd.")])

    def test_rows_in_display_order(self):
        profile = SimpleNamespace(
            live_indices=(
                SimpleNamespace(label="First", members_source="x:first"),
                SimpleNamespace(label="Second", members_source="x:second"),
            )
        )
        rows = member_rows(profile, lambda source: [(source.upper(), None)])
        self.assertEqual(
            [(row["index_name"], row["position"], row["symbol"]) for row in rows],
            [("First", 0, "X:FIRST"), ("Second", 1, "X:SECOND")],
        )

    def test_one_failed_list_keeps_all_of_yesterdays(self):
        profile = SimpleNamespace(
            live_indices=(
                SimpleNamespace(label="First", members_source="first"),
                SimpleNamespace(label="Second", members_source="second"),
            )
        )

        def fetch(source):
            if source == "second":
                raise OSError("timeout")
            return [("AAA", None)]

        self.assertIsNone(member_rows(profile, fetch))
        self.assertIsNone(member_rows(profile, lambda source: []))

    def test_refresh_due_once_a_day(self):
        self.assertTrue(members_due(None, IN_SESSION))
        self.assertTrue(members_due("garbage", IN_SESSION))
        self.assertTrue(members_due("2026-10-15T06:00:00Z", IN_SESSION))
        self.assertFalse(members_due("2026-10-16T03:00:00+00:00", IN_SESSION))


class RunTests(unittest.TestCase):
    def test_outside_the_session_fetches_nothing(self):
        repo = FakeRepo(snapshot=["AAA"])
        evening = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
        summary = run(repo, NSE, now=evening, fetch_quotes=must_not_fetch)
        self.assertEqual(summary["status"], "outside_session")
        self.assertIsNone(repo.quotes)

    def test_writes_stocks_and_index_levels(self):
        repo = FakeRepo(snapshot=["AAA"], members=["AAA", "BBB"])
        fetch, requested = fetcher(
            {"AAA.NS": quote(101), "BBB.NS": quote(99), "^NSEI": quote(25000, previous=24900)}
        )
        summary = run(repo, NSE, now=IN_SESSION, fetch_quotes=fetch, fetch_members=must_not_fetch)
        self.assertEqual(summary["status"], "written")
        self.assertEqual((summary["requested"], summary["quoted"], summary["indices"]), (2, 2, 1))
        self.assertIn("AAA.NS", requested)
        self.assertIn("^NSEI", requested)
        by_symbol = {row["symbol"]: row for row in repo.quotes}
        self.assertEqual(by_symbol["Nifty 50"]["kind"], "index")
        self.assertEqual(by_symbol["BBB"]["change_pct"], -1)
        self.assertEqual(repo.pruned, "2026-10-09T06:15:00+00:00")

    def test_charted_indices_are_quoted_without_a_movers_list(self):
        # The Nasdaq Composite and Russell 2000 have no movers list, but the
        # US Market page charts them.
        ten_am_et = datetime(2026, 10, 16, 14, 0, tzinfo=UTC)
        traded = int(datetime(2026, 10, 16, 13, 59, tzinfo=UTC).timestamp())
        levels = {ticker: quote(5000, previous=4990, traded=traded) for ticker, _ in US.headline_indices}
        fetch, requested = fetcher({"AAA": quote(101, traded=traded), **levels})
        summary = run(FakeRepo(snapshot=["AAA"]), US, now=ten_am_et, fetch_quotes=fetch)
        self.assertEqual(summary["indices"], len(US.headline_indices))
        for ticker, _ in US.headline_indices:
            self.assertIn(ticker, requested)

    def test_a_charted_index_with_a_movers_list_is_asked_for_once(self):
        fetch, requested = fetcher({"AAA.NS": quote(101)})
        run(FakeRepo(snapshot=["AAA"]), NSE, now=IN_SESSION, fetch_quotes=fetch, fetch_members=must_not_fetch)
        self.assertEqual(requested.count("^NSEI"), 1)
        charted = {label for _, label in NSE.headline_indices}
        self.assertLessEqual(charted, {index.label for index in NSE.live_indices})

    def test_holiday_writes_nothing(self):
        yesterday = int(datetime(2026, 10, 15, 10, 0, tzinfo=UTC).timestamp())
        repo = FakeRepo(snapshot=["AAA"])
        fetch, _ = fetcher({"AAA.NS": quote(101, traded=yesterday)})
        summary = run(repo, NSE, now=IN_SESSION, fetch_quotes=fetch)
        self.assertEqual(summary["status"], "no_session_today")
        self.assertIsNone(repo.quotes)

    def test_stale_constituents_are_refreshed_first(self):
        repo = FakeRepo(snapshot=["AAA"], refreshed_at=None)
        fetch, requested = fetcher({"AAA.NS": quote(101)})
        run(
            repo, NSE, now=IN_SESSION, fetch_quotes=fetch,
            fetch_members=lambda source: [("NEW", "New Ltd")],
        )
        self.assertEqual({row["symbol"] for row in repo.replaced}, {"NEW"})
        self.assertEqual(len({row["index_name"] for row in repo.replaced}), len(NSE.live_indices))
        # A member the screener does not rate is quoted on the same run.
        self.assertIn("NEW.NS", requested)

    def test_dry_run_writes_nothing(self):
        repo = FakeRepo(snapshot=["AAA"], refreshed_at=None)
        fetch, _ = fetcher({"AAA.NS": quote(101)})
        summary = run(
            repo, NSE, now=IN_SESSION, fetch_quotes=fetch,
            fetch_members=lambda source: [("AAA", None)], dry_run=True,
        )
        self.assertEqual(summary["status"], "dry_run")
        self.assertIsNone(repo.quotes)
        self.assertIsNone(repo.replaced)

    def test_vendor_outage_is_a_failure(self):
        repo = FakeRepo(snapshot=["AAA", "BBB", "CCC"])
        fetch, _ = fetcher({"AAA.NS": quote(101)})
        summary = run(repo, NSE, now=IN_SESSION, fetch_quotes=fetch)
        self.assertEqual(summary["status"], "low_coverage")
        # What did arrive is still written.
        self.assertEqual([row["symbol"] for row in repo.quotes], ["AAA"])


if __name__ == "__main__":
    unittest.main()
