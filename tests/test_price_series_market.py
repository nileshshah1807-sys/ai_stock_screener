"""Vendor-sourced price observations for markets with no bhavcopy archive."""

import unittest
from datetime import date
from unittest import mock

import pandas as pd

from screener.markets import resolve
from workers import price_series_market as psm
from workers.price_series import decode_series
from workers.price_series_publisher import build_rows

US = resolve("US")
NSE = resolve("NSE")


def _frame(dates, closes, volumes=None):
    return pd.DataFrame(
        {
            "Close": closes,
            "Volume": volumes if volumes is not None else [1_000] * len(closes),
        },
        index=pd.to_datetime(dates),
    )


def _grouped(per_ticker):
    """A yfinance-shaped multi-ticker frame: columns are (ticker, field)."""
    return pd.concat(per_ticker, axis=1, keys=list(per_ticker))


class TradingCalendarTests(unittest.TestCase):
    def test_calendar_comes_from_the_markets_benchmark(self):
        index = _frame(["2026-09-16", "2026-09-17", "2026-09-18"], [1.0, 2.0, 3.0])
        with mock.patch.object(psm.yf, "download", return_value=index) as download:
            sessions = psm.trading_calendar(US, start="2026-09-01")

        self.assertEqual(
            sessions, [date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]
        )
        self.assertEqual(download.call_args.args[0], "^GSPC")

    def test_an_empty_benchmark_is_fatal_rather_than_an_empty_calendar(self):
        """Series index into the calendar, so a wrong one misdates every point."""
        with (
            mock.patch.object(psm.yf, "download", return_value=pd.DataFrame()),
            self.assertRaises(RuntimeError),
        ):
            psm.trading_calendar(US)


class ObservationTests(unittest.TestCase):
    def _collect(self, per_ticker, symbols=None, profile=US, **kwargs):
        captured = {}

        def downloader(tickers):
            captured["tickers"] = list(tickers)
            return _grouped(per_ticker)

        result = psm.collect_observations(
            symbols if symbols is not None else list(per_ticker),
            profile,
            downloader=downloader,
            pause_seconds=0,
            **kwargs,
        )
        return result, captured

    def test_close_and_volume_are_collected_per_session(self):
        frames = {"AAPL": _frame(["2026-09-17", "2026-09-18"], [10.0, 11.0], [5, 6])}
        observations, _ = self._collect(frames)

        self.assertEqual(
            observations["AAPL"],
            {date(2026, 9, 17): (10.0, 5), date(2026, 9, 18): (11.0, 6)},
        )

    def test_us_tickers_carry_no_suffix_and_nse_tickers_do(self):
        frames = {"AAPL": _frame(["2026-09-18"], [10.0])}
        _, captured = self._collect(frames, symbols=["AAPL"])
        self.assertEqual(captured["tickers"], ["AAPL"])

        frames = {"RELIANCE.NS": _frame(["2026-09-18"], [10.0])}
        _, captured = self._collect(frames, symbols=["RELIANCE"], profile=NSE)
        self.assertEqual(captured["tickers"], ["RELIANCE.NS"])

    def test_symbols_are_keyed_bare_even_when_the_vendor_suffixes_them(self):
        frames = {"RELIANCE.NS": _frame(["2026-09-17", "2026-09-18"], [10.0, 11.0])}
        observations, _ = self._collect(frames, symbols=["RELIANCE"], profile=NSE)

        self.assertIn("RELIANCE", observations)
        self.assertNotIn("RELIANCE.NS", observations)

    def test_missing_and_non_positive_closes_are_dropped_not_invented(self):
        """A gap is a session the symbol did not trade; it is never filled."""
        frames = {
            "AAPL": _frame(
                ["2026-09-16", "2026-09-17", "2026-09-18"],
                [10.0, float("nan"), 0.0],
            )
        }
        observations, _ = self._collect(frames)

        self.assertEqual(list(observations["AAPL"]), [date(2026, 9, 16)])

    def test_a_symbol_the_vendor_does_not_know_is_simply_absent(self):
        frames = {"AAPL": _frame(["2026-09-18"], [10.0])}
        observations, _ = self._collect(frames, symbols=["AAPL", "NOSUCH"])

        self.assertIn("AAPL", observations)
        self.assertNotIn("NOSUCH", observations)

    def test_negative_and_missing_volume_becomes_zero(self):
        frames = {"AAPL": _frame(["2026-09-17", "2026-09-18"], [10.0, 11.0], [-5, None])}
        observations, _ = self._collect(frames)

        self.assertEqual(observations["AAPL"][date(2026, 9, 17)][1], 0)
        self.assertEqual(observations["AAPL"][date(2026, 9, 18)][1], 0)

    def test_a_failed_batch_does_not_end_the_run(self):
        """One bad batch must cost its own symbols, not the whole rebuild."""
        calls = {"n": 0}

        def downloader(tickers):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("vendor said no")
            return _grouped({"BBB": _frame(["2026-09-18"], [10.0])})

        observations = psm.collect_observations(
            ["AAA", "BBB"],
            US,
            downloader=downloader,
            batch_size=1,
            pause_seconds=0,
        )

        self.assertEqual(calls["n"], 2)
        self.assertEqual(list(observations), ["BBB"])

    def test_symbols_are_batched(self):
        seen = []

        def downloader(tickers):
            seen.append(list(tickers))
            return _grouped({t: _frame(["2026-09-18"], [1.0]) for t in tickers})

        psm.collect_observations(
            ["A", "B", "C", "D", "E"],
            US,
            downloader=downloader,
            batch_size=2,
            pause_seconds=0,
        )

        self.assertEqual(seen, [["A", "B"], ["C", "D"], ["E"]])


class SharedPipelineTests(unittest.TestCase):
    """Vendor observations must feed the same encoder the archive path uses."""

    def test_rows_round_trip_through_the_shared_encoder(self):
        sessions = [date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]
        observations = {
            "AAPL": {
                sessions[0]: (10.0, 100),
                sessions[1]: (11.5, 200),
                sessions[2]: (12.25, 300),
            }
        }

        rows = build_rows(
            sessions, observations, psm.identity_symbols(observations), min_points=2
        )

        self.assertEqual(len(rows), 1)
        decoded = decode_series(rows[0], sessions)
        self.assertEqual(
            [(point["date"], point["close"], point["volume"]) for point in decoded],
            [
                ("2026-09-16", 10.0, 100),
                ("2026-09-17", 11.5, 200),
                ("2026-09-18", 12.25, 300),
            ],
        )

    def test_a_session_the_symbol_missed_stays_a_gap(self):
        sessions = [date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]
        observations = {"AAPL": {sessions[0]: (10.0, 1), sessions[2]: (12.0, 1)}}

        rows = build_rows(
            sessions, observations, psm.identity_symbols(observations), min_points=2
        )
        decoded = decode_series(rows[0], sessions)

        self.assertEqual([point["date"] for point in decoded], ["2026-09-16", "2026-09-18"])

    def test_identity_symbols_maps_each_symbol_to_itself(self):
        self.assertEqual(
            psm.identity_symbols({"AAPL": {}, "MSFT": {}}),
            {"AAPL": "AAPL", "MSFT": "MSFT"},
        )


if __name__ == "__main__":
    unittest.main()
