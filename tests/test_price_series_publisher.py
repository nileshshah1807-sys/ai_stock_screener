"""Building publishable price-series rows from the archive.

The publisher's job is to turn per-security observations into one row per
*symbol*, which is where the real ambiguities live: a ticker outlives the
company holding it, and a security trades under several tickers over a decade.
"""

import unittest
from datetime import date, timedelta

from workers.price_series import decode_series
from workers.price_series_publisher import (
    PublishRefused,
    build_rows,
    calendar_row,
    publish,
)


def calendar(days, start=date(2024, 1, 1)):
    out, day = [], start
    while len(out) < days:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def observations(sessions, price=100.0, volume=1000):
    return {day: (price + index, volume) for index, day in enumerate(sessions)}


class RecordingRepository:
    """Captures writes so publish() can be tested without a network."""

    def __init__(self):
        self.calendar = None
        self.rows = []

    def upsert_price_calendar(self, row):
        self.calendar = row

    def upsert_price_series(self, rows):
        self.rows.extend(rows)
        return len(rows)


class BuildRowsTests(unittest.TestCase):
    def setUp(self):
        self.sessions = calendar(60)

    def test_one_row_per_symbol_carrying_the_symbol(self):
        rows = build_rows(
            self.sessions,
            {"SEC1": observations(self.sessions)},
            {"SEC1": "ALPHA"},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "ALPHA")
        self.assertEqual(rows[0]["points"], 60)

    def test_a_security_with_no_known_symbol_is_skipped(self):
        """Publishing under a Security_ID would make the row unreachable."""
        rows = build_rows(
            self.sessions, {"SEC1": observations(self.sessions)}, {}
        )
        self.assertEqual(rows, [])

    def test_short_histories_are_skipped(self):
        short = self.sessions[:5]
        rows = build_rows(
            self.sessions,
            {"SEC1": observations(short)},
            {"SEC1": "THIN"},
            min_points=30,
        )
        self.assertEqual(rows, [])

    def test_a_reused_ticker_resolves_to_the_most_recent_security(self):
        """Two companies, one ticker. The reader typing it means the live one."""
        old = self.sessions[:30]
        new = self.sessions[30:]
        rows = build_rows(
            self.sessions,
            {
                "OLDCO": observations(old, price=10.0),
                "NEWCO": observations(new, price=500.0),
            },
            {"OLDCO": "SHARED", "NEWCO": "SHARED"},
            min_points=10,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["last_session"], new[-1].isoformat())
        first = decode_series(rows[0], self.sessions)[0]
        self.assertGreater(first["close"], 100)  # the newer company's prices

    def test_rows_are_sorted_by_symbol_for_a_stable_diff(self):
        rows = build_rows(
            self.sessions,
            {k: observations(self.sessions) for k in ("A", "B", "C")},
            {"A": "ZETA", "B": "ALPHA", "C": "MIKE"},
        )
        self.assertEqual([r["symbol"] for r in rows], ["ALPHA", "MIKE", "ZETA"])

    def test_published_rows_decode_back_to_the_original_prices(self):
        rows = build_rows(
            self.sessions,
            {"SEC1": observations(self.sessions, price=250.5)},
            {"SEC1": "ALPHA"},
        )
        points = decode_series(rows[0], self.sessions)
        self.assertEqual(len(points), 60)
        self.assertAlmostEqual(points[0]["close"], 250.5, places=2)
        self.assertAlmostEqual(points[-1]["close"], 250.5 + 59, places=2)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.sessions = calendar(60)
        self.rows = build_rows(
            self.sessions,
            {"SEC1": observations(self.sessions)},
            {"SEC1": "ALPHA"},
        )

    def test_calendar_is_written_before_the_series(self):
        """A series indexes into the calendar; the wrong one dates every point wrong."""
        repository = RecordingRepository()
        order = []
        repository.upsert_price_calendar = lambda row: order.append("calendar")
        repository.upsert_price_series = lambda rows: (
            order.append("series") or len(rows)
        )
        publish(repository, self.sessions, self.rows)
        self.assertEqual(order, ["calendar", "series"])

    def test_dry_run_writes_nothing(self):
        repository = RecordingRepository()
        written = publish(repository, self.sessions, self.rows, dry_run=True)
        self.assertEqual(written, 0)
        self.assertIsNone(repository.calendar)
        self.assertEqual(repository.rows, [])

    def test_calendar_row_describes_its_own_span(self):
        row = calendar_row(self.sessions)
        self.assertEqual(row["session_count"], 60)
        self.assertEqual(row["first_session"], self.sessions[0].isoformat())
        self.assertEqual(row["last_session"], self.sessions[-1].isoformat())



class ShrinkGuardTests(unittest.TestCase):
    """A cold or partly-restored archive must not overwrite a good series.

    The archive is resumable and cached, so an evicted CI cache leaves it nearly
    empty rather than failing outright. An upsert gives no hint that history was
    replaced with a stub, so the guard is the only thing standing between a cache
    miss and every chart silently losing eight years.
    """

    def setUp(self):
        self.sessions = calendar(60)
        self.rows = build_rows(
            self.sessions,
            {"SEC1": observations(self.sessions)},
            {"SEC1": "ALPHA"},
        )

    def _repository(self, published):
        repository = RecordingRepository()
        repository.published_calendar_size = lambda: published
        return repository

    def test_a_truncated_archive_is_refused(self):
        repository = self._repository(2116)
        with self.assertRaises(PublishRefused) as caught:
            publish(repository, self.sessions, self.rows)
        self.assertIn("2116", str(caught.exception))
        self.assertEqual(repository.rows, [])

    def test_a_full_archive_publishes(self):
        repository = self._repository(60)
        self.assertEqual(publish(repository, self.sessions, self.rows), 1)

    def test_a_small_shrink_is_allowed(self):
        """Delistings and trimmed windows legitimately shorten the calendar."""
        repository = self._repository(63)  # 60/63 is inside the tolerance
        self.assertEqual(publish(repository, self.sessions, self.rows), 1)

    def test_the_first_publish_is_not_blocked(self):
        repository = self._repository(None)
        self.assertEqual(publish(repository, self.sessions, self.rows), 1)

    def test_allow_shrink_overrides_the_guard(self):
        repository = self._repository(2116)
        self.assertEqual(
            publish(repository, self.sessions, self.rows, allow_shrink=True), 1
        )

    def test_an_unreadable_calendar_does_not_block_publishing(self):
        """A diagnostic read must never be the reason a run fails."""
        repository = RecordingRepository()

        def explode():
            raise RuntimeError("network")

        repository.published_calendar_size = explode
        self.assertEqual(publish(repository, self.sessions, self.rows), 1)


if __name__ == "__main__":
    unittest.main()
