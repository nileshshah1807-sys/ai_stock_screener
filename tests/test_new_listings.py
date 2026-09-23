"""Surfacing recent NSE listings the screener has not rated yet.

What must hold: only mainboard listings inside the window are considered,
anything already rated is left to the snapshot, the stated reason matches the
rule that actually held the stock out, and a broken master file can never wipe
the published list.
"""

import unittest
from datetime import date

import pandas as pd

from workers.new_listings import (
    STATUS_BELOW_LIQUIDITY_FLOOR,
    STATUS_INSUFFICIENT_HISTORY,
    STATUS_NO_PRICE_DATA,
    STATUS_PENDING_RUN,
    classify,
    recent_listings,
    run,
    summarize_prices,
)

AS_OF = date(2026, 9, 23)
LIMITS = {"sessions": 60, "mean_turnover": 50_00_000.0, "median_turnover": 50_00_000.0}


def master(rows):
    return pd.DataFrame(
        [
            {
                "SYMBOL": symbol,
                "NAME OF COMPANY": f"{symbol} Ltd",
                " SERIES": series,
                " DATE OF LISTING": listed,
                " ISIN NUMBER": f"INE{symbol}",
            }
            for symbol, series, listed in rows
        ]
    )


def bars(sessions, close=100.0, volume=100_000):
    index = pd.bdate_range("2026-01-01", periods=sessions)
    return pd.DataFrame({"Close": [close] * sessions, "Volume": [volume] * sessions}, index=index)


class RecentListingsTests(unittest.TestCase):
    def test_window_series_and_padded_headers(self):
        frame = master([
            ("NEWCO", "EQ", "01-SEP-2026"),
            ("BECO", "BE", "15-AUG-2026"),
            ("BZCO", "BZ", "01-SEP-2026"),
            ("RIGHTS-RE", "BE", "01-SEP-2026"),
            ("OLDCO", "EQ", "01-JAN-2020"),
            ("FUTURE", "EQ", "01-OCT-2026"),
        ])
        out = recent_listings(frame, AS_OF, 365)
        self.assertEqual(sorted(out["symbol"]), ["BECO", "NEWCO"])
        self.assertEqual(out.loc[out["symbol"] == "NEWCO", "listed_on"].iloc[0], date(2026, 9, 1))


class SummaryAndClassificationTests(unittest.TestCase):
    def test_summary_facts(self):
        prices = bars(3)
        prices["Close"] = [100.0, 110.0, 120.0]
        out = summarize_prices(prices)
        self.assertEqual(out["sessions"], 3)
        self.assertEqual(out["first_close"], 100.0)
        self.assertEqual(out["last_close"], 120.0)
        self.assertEqual(out["change_since_first_pct"], 20.0)
        self.assertEqual(out["avg_turnover_20d"], 11_000_000)

    def test_single_session_has_no_change_since_first(self):
        self.assertIsNone(summarize_prices(bars(1))["change_since_first_pct"])

    def test_no_bars_is_no_price_data(self):
        self.assertEqual(classify(summarize_prices(None), LIMITS), STATUS_NO_PRICE_DATA)

    def test_short_history_comes_before_liquidity(self):
        thin_and_new = summarize_prices(bars(20, volume=10))
        self.assertEqual(classify(thin_and_new, LIMITS), STATUS_INSUFFICIENT_HISTORY)

    def test_enough_history_but_thin_turnover(self):
        # 100 x 1,000 = Rs 1 lakh a day, far under the Rs 50 lakh floor.
        self.assertEqual(
            classify(summarize_prices(bars(80, volume=1_000)), LIMITS),
            STATUS_BELOW_LIQUIDITY_FLOOR,
        )

    def test_meets_both_minimums_is_pending(self):
        self.assertEqual(classify(summarize_prices(bars(80)), LIMITS), STATUS_PENDING_RUN)


class FakeRepository:
    market = "NSE"

    def __init__(self, rated=()):
        self.rated = list(rated)
        self.published = None

    def latest_snapshot_symbols(self):
        return self.rated

    def replace_new_listings(self, rows):
        self.published = rows
        return len(rows)


def fake_download(tickers, **_):
    names = tickers.split()
    frames = {name: bars(10 if name == "NEWCO.NS" else 80) for name in names if name != "GHOST.NS"}
    return pd.concat(frames, axis=1) if frames else pd.DataFrame()


class RunTests(unittest.TestCase):
    def test_publishes_only_unrated_recent_listings_with_reasons(self):
        repo = FakeRepository(rated=["RATED"])
        frame = master([
            ("NEWCO", "EQ", "01-SEP-2026"),
            ("READY", "EQ", "01-MAY-2026"),
            ("GHOST", "EQ", "20-SEP-2026"),
            ("RATED", "EQ", "01-MAR-2026"),
        ])
        counts = run(
            repo,
            fetch_master=lambda: frame,
            download=fake_download,
            profile_lookup=lambda ticker: {"market_cap": 5e10, "logo_domain": "example.com"},
            as_of=AS_OF,
        )
        by_symbol = {row["symbol"]: row for row in repo.published}
        self.assertEqual(sorted(by_symbol), ["GHOST", "NEWCO", "READY"])
        self.assertEqual(by_symbol["NEWCO"]["status"], STATUS_INSUFFICIENT_HISTORY)
        self.assertEqual(by_symbol["NEWCO"]["sessions"], 10)
        self.assertEqual(by_symbol["READY"]["status"], STATUS_PENDING_RUN)
        self.assertEqual(by_symbol["GHOST"]["status"], STATUS_NO_PRICE_DATA)
        self.assertIsNone(by_symbol["GHOST"]["market_cap"])
        self.assertIsNone(by_symbol["GHOST"]["logo_domain"])
        self.assertEqual(by_symbol["NEWCO"]["logo_domain"], "example.com")
        self.assertEqual(by_symbol["NEWCO"]["sessions_required"], 60)
        self.assertEqual(counts["published"], 3)

    def test_unreadable_master_never_wipes_the_table(self):
        repo = FakeRepository()
        counts = run(
            repo,
            fetch_master=lambda: master([]).reindex(
                columns=["SYMBOL", " SERIES", " DATE OF LISTING"]
            ),
            download=fake_download,
            profile_lookup=lambda ticker: {},
            as_of=AS_OF,
        )
        self.assertIsNone(repo.published)
        self.assertEqual(counts["published"], 0)

    def test_dry_run_publishes_nothing(self):
        repo = FakeRepository()
        run(
            repo,
            fetch_master=lambda: master([("NEWCO", "EQ", "01-SEP-2026")]),
            download=fake_download,
            profile_lookup=lambda ticker: {},
            as_of=AS_OF,
            dry_run=True,
        )
        self.assertIsNone(repo.published)


if __name__ == "__main__":
    unittest.main()
