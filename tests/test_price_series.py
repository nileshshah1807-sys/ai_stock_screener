"""Encoding for the per-symbol price series.

A chart is only as trustworthy as its round trip: a delta chain that drifts by
one paise at session 40 stays wrong for every session after it, and the error is
invisible on screen. These tests exist to make that class of bug loud.
"""

import unittest
from datetime import date, timedelta

from workers.price_series import (
    build_series,
    decode_calendar,
    decode_deltas,
    decode_series,
    encode_calendar,
    encode_deltas,
)


def calendar(days, start=date(2024, 1, 1)):
    """``days`` consecutive weekdays, standing in for a trading calendar."""
    out, day = [], start
    while len(out) < days:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


class DeltaCodecTests(unittest.TestCase):
    def test_round_trip_preserves_every_value(self):
        values = [12345, 12350, 12290, 99999, 1, 0, 500000]
        self.assertEqual(decode_deltas(encode_deltas(values)), values)

    def test_a_long_chain_does_not_drift(self):
        """Each value is reconstructed from every delta before it."""
        values = [100_00 + (index * 37) % 5000 for index in range(5000)]
        self.assertEqual(decode_deltas(encode_deltas(values)), values)

    def test_negative_deltas_survive(self):
        values = [50000, 10, 50000]
        self.assertEqual(decode_deltas(encode_deltas(values)), values)

    def test_empty_and_single_value_series(self):
        self.assertEqual(encode_deltas([]), "[]")
        self.assertEqual(decode_deltas("[]"), [])
        self.assertEqual(decode_deltas(""), [])
        self.assertEqual(decode_deltas(encode_deltas([42])), [42])

    def test_deltas_are_smaller_than_absolutes(self):
        """The whole reason for delta encoding; if this fails, drop it."""
        values = [100_00 + index for index in range(2000)]
        absolute = len(str(values).replace(" ", ""))
        self.assertLess(len(encode_deltas(values)), absolute / 2)


class BuildSeriesTests(unittest.TestCase):
    def setUp(self):
        self.sessions = calendar(10)

    def test_a_dense_series_round_trips_to_the_original_prices(self):
        observations = {
            day: (100.0 + index * 1.5, 1000 + index)
            for index, day in enumerate(self.sessions)
        }
        row = build_series(self.sessions, observations)
        points = decode_series(row, self.sessions)

        self.assertEqual(len(points), 10)
        self.assertEqual([p["date"] for p in points],
                         [d.isoformat() for d in self.sessions])
        for index, point in enumerate(points):
            self.assertAlmostEqual(point["close"], 100.0 + index * 1.5, places=2)
            self.assertEqual(point["volume"], 1000 + index)

    def test_untraded_sessions_stay_absent_rather_than_forward_filled(self):
        """A thin stock's gaps are real; inventing prices would draw a lie."""
        traded = [self.sessions[0], self.sessions[3], self.sessions[9]]
        row = build_series(self.sessions, {d: (50.0, 10) for d in traded})
        points = decode_series(row, self.sessions)
        self.assertEqual([p["date"] for p in points],
                         [d.isoformat() for d in traded])

    def test_first_and_last_session_describe_the_encoded_range(self):
        traded = self.sessions[2:6]
        row = build_series(self.sessions, {d: (10.0, 1) for d in traded})
        self.assertEqual(row["first_session"], traded[0].isoformat())
        self.assertEqual(row["last_session"], traded[-1].isoformat())
        self.assertEqual(row["points"], len(traded))

    def test_a_session_outside_the_calendar_is_dropped_not_misaligned(self):
        """Silently shifting one array against the others corrupts every later point."""
        observations = {d: (10.0, 1) for d in self.sessions[:3]}
        observations[date(1999, 1, 4)] = (99.0, 1)
        row = build_series(self.sessions, observations)
        self.assertEqual(row["points"], 3)
        decode_series(row, self.sessions)  # must not raise

    def test_non_positive_prices_are_dropped(self):
        observations = {d: (10.0, 1) for d in self.sessions}
        observations[self.sessions[4]] = (0.0, 1)
        observations[self.sessions[5]] = (None, 1)
        row = build_series(self.sessions, observations)
        self.assertEqual(row["points"], 8)

    def test_missing_volume_becomes_zero_not_a_gap(self):
        """No trades is a real observation when a close still printed."""
        observations = {d: (10.0, 0) for d in self.sessions}
        row = build_series(self.sessions, observations)
        points = decode_series(row, self.sessions)
        self.assertEqual(len(points), 10)
        self.assertTrue(all(p["volume"] == 0 for p in points))

    def test_a_series_too_short_to_chart_returns_none(self):
        self.assertIsNone(build_series(self.sessions, {}))
        self.assertIsNone(
            build_series(self.sessions, {self.sessions[0]: (10.0, 1)})
        )

    def test_misaligned_arrays_raise_rather_than_draw_wrong_prices(self):
        row = build_series(
            self.sessions, {d: (10.0, 1) for d in self.sessions}
        )
        row["closes"] = encode_deltas([1, 2, 3])
        with self.assertRaises(ValueError):
            decode_series(row, self.sessions)

    def test_paise_rounding_is_exact_for_two_decimal_quotes(self):
        prices = [1234.56, 0.05, 99999.99, 7.10]
        sessions = calendar(len(prices))
        row = build_series(
            sessions, {d: (p, 1) for d, p in zip(sessions, prices)}
        )
        got = [p["close"] for p in decode_series(row, sessions)]
        self.assertEqual(got, prices)


class CalendarCodecTests(unittest.TestCase):
    def test_round_trip(self):
        sessions = calendar(50)
        self.assertEqual(decode_calendar(encode_calendar(sessions)), sessions)

    def test_calendar_is_stored_once_not_per_symbol(self):
        """~23 KB shared, against ~23 KB x 2861 if each series carried its dates."""
        sessions = calendar(2116)
        self.assertLess(len(encode_calendar(sessions)), 30_000)


if __name__ == "__main__":
    unittest.main()
