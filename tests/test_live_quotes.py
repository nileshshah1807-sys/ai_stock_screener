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
from screener.markets import resolve as resolve_market
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
