"""Market breadth: definitions, denominators and the published row contract."""

import json
import re
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from screener.markets import resolve
from screener.stage import STAGE_2, classify_stages
from tests.test_dashboard_repository import RecordingDashboardRepository
from tools.publish_market_breadth import (
    completed_session_cap,
    fetch_fresh_indices,
    fetch_index_points,
    stale_indices,
    symbol_observations,
)
from workers import market_breadth as mb

SESSIONS = [date(2020, 1, 1) + timedelta(days=offset) for offset in range(400)]


def walk(seed, length=None, drift=0.0):
    length = len(SESSIONS) if length is None else length
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(drift, 0.02, length)))


def observations(closes, start=0):
    return {SESSIONS[start + offset]: (float(value), 1) for offset, value in enumerate(closes)}


def last(row, key):
    return mb.undelta(json.loads(row["series"])[key])[-1]


def decoded(row):
    return {key: mb.undelta(values) for key, values in json.loads(row["series"]).items()}


class EncodingTests(unittest.TestCase):
    def test_sessions_round_trip(self):
        days = [date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 21)]
        self.assertEqual(mb.decode_sessions(mb.encode_sessions(days)), days)

    def test_counts_round_trip_through_deltas(self):
        values = [5, 9, 9, 2, 40]
        self.assertEqual(mb.undelta(mb._delta_list(values)), values)


class SignalTests(unittest.TestCase):
    def test_stage_2_is_the_screeners_own_classification(self):
        closes = pd.Series(walk(1, drift=0.002), index=SESSIONS)
        signals = mb.symbol_signals(closes)
        labels = classify_stages(pd.Series(closes.to_numpy()))
        expected = [
            mb.UNDEFINED if label is None else int(label == STAGE_2) for label in labels
        ]
        self.assertEqual(signals["stage2"].tolist(), expected)

    def test_an_ema_is_undefined_until_its_window_is_full(self):
        closes = pd.Series(walk(2, length=60), index=SESSIONS[:60])
        signals = mb.symbol_signals(closes)
        self.assertTrue((signals["ema50"][:49] == mb.UNDEFINED).all())
        self.assertTrue((signals["ema50"][49:] != mb.UNDEFINED).all())
        self.assertTrue((signals["ema200"] == mb.UNDEFINED).all())

    def test_a_new_high_must_beat_the_prior_year(self):
        values = np.linspace(100, 50, 300)
        values[-1] = 101
        closes = pd.Series(values, index=SESSIONS[:300])
        signals = mb.symbol_signals(closes)
        self.assertEqual(signals["high52"][-1], 1)
        self.assertEqual(signals["low52"][-2], 1)
        self.assertEqual(signals["high52"][-2], 0)


class BuildRowsTests(unittest.TestCase):
    def setUp(self):
        self.observations = {
            "UP": observations(walk(3, drift=0.003)),
            "DOWN": observations(walk(4, drift=-0.003)),
            "FLAT": observations(walk(5)),
            # Listed late: too young for a 200-day EMA at the end.
            "YOUNG": observations(walk(6, length=100), start=300),
            "OUT": observations(walk(7)),
        }
        self.classification = {
            "UP": ("Technology", "Software"),
            "DOWN": ("Technology", "Software"),
            "FLAT": ("Energy", "Oil"),
            "YOUNG": ("Energy", "Oil"),
        }

    def build(self, **kwargs):
        return mb.build_rows(
            self.observations, SESSIONS, self.classification, min_industry_members=2, **kwargs
        )

    def test_universe_is_the_classified_symbols_only(self):
        market = next(row for row in self.build() if row["scope"] == "market")
        self.assertEqual(market["members"], 4)
        self.assertEqual(last(market, "n"), 4)

    def test_a_young_stock_leaves_the_long_denominators(self):
        market = next(row for row in self.build() if row["scope"] == "market")
        self.assertEqual(last(market, "e50d"), 4)
        self.assertEqual(last(market, "e200d"), 3)

    def test_an_untraded_day_is_not_counted(self):
        del self.observations["UP"][SESSIONS[-1]]
        market = next(row for row in self.build() if row["scope"] == "market")
        self.assertEqual(last(market, "n"), 3)
        self.assertEqual(last(market, "e20d"), 3)

    def test_rs_rating_splits_the_universe_by_percentile(self):
        market = next(row for row in self.build() if row["scope"] == "market")
        series = decoded(market)
        # Three stocks have a full year at the end; ratings 1, 50 and 99 leave
        # exactly one above 75.
        self.assertEqual(series["rsd"][-1], 3)
        self.assertEqual(series["rs"][-1], 1)

    def test_groups_and_small_industries(self):
        rows = self.build()
        sectors = {row["name"]: row for row in rows if row["scope"] == "sector"}
        self.assertEqual(set(sectors), {"Technology", "Energy"})
        self.assertEqual(sectors["Technology"]["members"], 2)
        industries = {row["name"]: row for row in rows if row["scope"] == "industry"}
        self.assertEqual(industries["Software"]["parent"], "Technology")

        strict = mb.build_rows(self.observations, SESSIONS, self.classification)
        self.assertFalse([row for row in strict if row["scope"] == "industry"])

    def test_a_group_starts_when_its_first_member_trades(self):
        self.classification = {"YOUNG": ("Energy", "Oil")}
        market = next(row for row in self.build() if row["scope"] == "market")
        self.assertEqual(market["first_session"], SESSIONS[300].isoformat())
        self.assertEqual(market["points"], 100)

    def test_benchmark_relative_count_needs_a_benchmark(self):
        market = next(row for row in self.build() if row["scope"] == "market")
        self.assertNotIn("bb", json.loads(market["series"]))

        benchmark = dict.fromkeys(SESSIONS, 100.0)
        market = next(
            row for row in self.build(benchmark_points=benchmark) if row["scope"] == "market"
        )
        series = decoded(market)
        up_beats_flat_index = walk(3, drift=0.003)[-1] > walk(3, drift=0.003)[-127]
        self.assertTrue(up_beats_flat_index)
        self.assertGreaterEqual(series["bb"][-1], 1)
        self.assertEqual(series["bbd"][-1], 3)

    def test_index_rows_are_ordered_levels_in_hundredths(self):
        rows = self.build(
            index_points=[("B", {SESSIONS[0]: 10.005, SESSIONS[1]: 11.0}), ("Empty", {})]
        )
        indices = [row for row in rows if row["scope"] == "index"]
        self.assertEqual([row["name"] for row in indices], ["B"])
        self.assertEqual(decoded(indices[0])["c"], [1001, 1100])
        self.assertEqual(indices[0]["position"], 0)

    def test_each_list_is_exactly_the_stocks_behind_the_final_count(self):
        benchmark = dict.fromkeys(SESSIONS, 100.0)
        rows, members = mb.build_breadth(
            self.observations,
            SESSIONS,
            self.classification,
            benchmark_points=benchmark,
            min_industry_members=2,
        )
        market = next(row for row in rows if row["scope"] == "market")
        for key in ("e20", "e50", "e100", "e200", "s2", "rs", "bb", "hi", "lo"):
            self.assertEqual(len(members[key]), last(market, key), key)
            self.assertLessEqual(set(members[key]), set(self.classification), key)

    def test_a_stock_that_did_not_trade_last_session_is_in_no_list(self):
        del self.observations["UP"][SESSIONS[-1]]
        _, members = mb.build_breadth(self.observations, SESSIONS, self.classification)
        self.assertFalse(any("UP" in symbols for symbols in members.values()))

    def test_no_overlap_is_an_error_not_an_empty_publish(self):
        with self.assertRaises(ValueError):
            mb.build_rows(self.observations, SESSIONS, {"NOPE": ("X", "Y")})


class DashboardContractTests(unittest.TestCase):
    def test_the_page_accepts_exactly_the_lists_the_worker_publishes(self):
        source = (
            Path(__file__).resolve().parents[1] / "dashboard" / "lib" / "market-breadth.mjs"
        ).read_text(encoding="utf-8")
        match = re.search(r"export const LIST_METRICS = \[([^\]]*)\]", source)
        self.assertIsNotNone(match)
        keys = set(re.findall(r'"(\w+)"', match.group(1)))
        self.assertEqual(keys, set(mb.LIST_PANELS))


class ToolTests(unittest.TestCase):
    def test_archive_securities_are_rekeyed_to_the_newest_holder_of_a_ticker(self):
        old = {date(2019, 1, 1): (10.0, 1)}
        new = {date(2026, 1, 1): (20.0, 1)}
        rekeyed = symbol_observations({"A": old, "B": new}, {"A": "TICK", "B": "TICK"})
        self.assertIs(rekeyed["TICK"], new)

    def test_a_failed_index_does_not_end_the_run(self):
        frame = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.to_datetime(["2026-09-17", "2026-09-18"]))

        def downloader(ticker):
            if ticker == "BAD":
                raise RuntimeError("vendor down")
            return frame

        points = fetch_index_points(["GOOD", "BAD"], downloader=downloader)
        self.assertEqual(points["BAD"], {})
        self.assertEqual(points["GOOD"][date(2026, 9, 18)], 2.0)

    def test_the_live_sessions_partial_bar_is_not_a_close(self):
        frame = pd.DataFrame(
            {"Close": [1.0, 2.0, 3.0]},
            index=pd.to_datetime(["2026-09-25", "2026-09-28", "2026-09-29"]),
        )
        points = fetch_index_points(
            ["IDX"], downloader=lambda ticker: frame, not_after=date(2026, 9, 28)
        )
        self.assertEqual(sorted(points["IDX"]), [date(2026, 9, 25), date(2026, 9, 28)])

    def test_cap_is_today_only_after_the_market_cutoff(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        nse = resolve("NSE")
        tz = ZoneInfo(nse.timezone)
        during = datetime(2026, 9, 29, 10, 41, tzinfo=tz)
        after = datetime(2026, 9, 29, 20, 0, tzinfo=tz)
        self.assertEqual(completed_session_cap(nse, during), date(2026, 9, 28))
        self.assertEqual(completed_session_cap(nse, after), date(2026, 9, 29))

    def test_an_index_behind_the_market_is_retried_until_it_catches_up(self):
        # 28 Sept 2026: the NSE indices ended on the 25th; the run stayed green.
        late = {date(2026, 9, 25): 1.0}
        caught_up = {date(2026, 9, 25): 1.0, date(2026, 9, 28): 2.0}
        answers = iter([{"A": caught_up, "B": late}, {"B": caught_up}])
        sleeps = []

        indices, stale = fetch_fresh_indices(
            ["A", "B"],
            date(2026, 9, 28),
            fetch=lambda names: next(answers),
            retries=3,
            wait=5,
            sleep=sleeps.append,
        )
        self.assertEqual(stale, [])
        self.assertEqual(sleeps, [5])
        self.assertEqual(max(indices["B"]), date(2026, 9, 28))

    def test_an_index_that_never_catches_up_is_reported_and_keeps_its_history(self):
        late = {date(2026, 9, 25): 1.0}
        calls = []

        def fetch(names):
            calls.append(list(names))
            return {name: (late if len(calls) == 1 else {}) for name in names}

        indices, stale = fetch_fresh_indices(
            ["A"], date(2026, 9, 28), fetch=fetch, retries=2, wait=0, sleep=lambda _: None
        )
        self.assertEqual(stale, ["A"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(indices["A"], late)

    def test_a_current_index_is_not_retried(self):
        sleeps = []
        _, stale = fetch_fresh_indices(
            ["A"],
            date(2026, 9, 28),
            fetch=lambda names: {"A": {date(2026, 9, 28): 1.0}},
            sleep=sleeps.append,
        )
        self.assertEqual((stale, sleeps), ([], []))
        self.assertEqual(stale_indices({}, ["A"], date(2026, 9, 28)), ["A"])

    def test_nse_own_closes_fill_the_session_yahoo_has_not_published(self):
        from tools.publish_market_breadth import overlay_nse_closes

        csv_text = (
            "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
            "Closing Index Value,Points Change\n"
            "Nifty 50,28-09-2026,23064.9,23080.25,22762.2,22780.25,-360.25\n"
            "Nifty 500,28-09-2026,1,1,1,22232.15,-1\n"
            "Nifty Next 50,28-09-2026,1,1,1,70309.5,-1\n"
        )
        asked = []

        class Response:
            def __init__(self, status, text=""):
                self.status_code, self.text = status, text

        def get(url):
            asked.append(url)
            return Response(200, csv_text) if "28092026" in url else Response(404)

        points = {
            "^NSEI": {date(2026, 9, 25): 23140.5},  # Yahoo stopped on the 25th
            "^CRSLDX": {date(2026, 9, 25): 22603.5, date(2026, 9, 28): 22232.2},
            "EMPTY": {},  # Yahoo returned nothing: must not become a 1-day chart
        }
        headline = (("^NSEI", "Nifty 50"), ("^CRSLDX", "Nifty 500"), ("EMPTY", "Nifty Midcap 150"))
        overlay_nse_closes(points, headline, date(2026, 9, 29), get=get)

        self.assertEqual(points["^NSEI"][date(2026, 9, 28)], 22780.25)
        self.assertEqual(points["^NSEI"][date(2026, 9, 25)], 23140.5)
        self.assertEqual(points["^CRSLDX"][date(2026, 9, 28)], 22232.15)  # NSE wins
        self.assertEqual(points["EMPTY"], {})
        # 19-29 Sept is 11 days, of which the weekends are never requested.
        self.assertFalse(any(d in url for url in asked for d in ("20092026", "26092026", "27092026")))
        self.assertTrue(any("29092026" in url for url in asked))

    def test_an_nse_file_for_another_day_or_a_failed_download_is_ignored(self):
        from tools.publish_market_breadth import fetch_nse_index_closes

        wrong_day = "Index Name,Index Date,Closing Index Value\nNifty 50,25-09-2026,23140.5\n"

        class Response:
            status_code = 200
            text = wrong_day

        calls = iter([Response(), RuntimeError("blocked")])

        def get(url):
            result = next(calls)
            if isinstance(result, Exception):
                raise result
            return result

        closes = fetch_nse_index_closes(
            ["Nifty 50"], [date(2026, 9, 28), date(2026, 9, 29)], get=get
        )
        self.assertEqual(closes, {"Nifty 50": {}})

    def test_every_market_names_its_headline_indices(self):
        for code in ("NSE", "US"):
            self.assertEqual(len(resolve(code).headline_indices), 4)


class RepositoryTests(unittest.TestCase):
    def test_replace_upserts_then_removes_groups_no_longer_published(self):
        repository = RecordingDashboardRepository(
            [None, [{"scope": "sector", "name": "Tech"}, {"scope": "sector", "name": "Gone"}]]
        )
        repository.replace_market_breadth([{"scope": "sector", "name": "Tech"}])

        method, path, kwargs = repository.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("on_conflict=market,scope,name", path)
        self.assertEqual(kwargs["json"][0]["market"], "NSE")
        deletes = [call for call in repository.calls if call[0] == "DELETE"]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0][2]["params"]["name"], "eq.Gone")
        self.assertEqual(deletes[0][2]["params"]["market"], "eq.NSE")

    def test_lists_are_upserted_then_everything_older_is_deleted(self):
        repository = RecordingDashboardRepository(market="US")
        written = repository.replace_breadth_members(
            {"hi": ["AAA", "BBB"], "lo": ["CCC"]}, "2026-09-23"
        )

        self.assertEqual(written, 3)
        method, path, kwargs = repository.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("on_conflict=market,metric,symbol", path)
        stamps = {row["published_at"] for row in kwargs["json"]}
        self.assertEqual(len(stamps), 1)
        self.assertTrue(all(row["market"] == "US" for row in kwargs["json"]))
        self.assertTrue(all(row["session"] == "2026-09-23" for row in kwargs["json"]))

        method, path, kwargs = repository.calls[-1]
        self.assertEqual((method, path), ("DELETE", "market_breadth_members"))
        self.assertEqual(kwargs["params"]["published_at"], f"lt.{stamps.pop()}")
        self.assertEqual(kwargs["params"]["market"], "eq.US")


if __name__ == "__main__":
    unittest.main()
