"""BSE-only companies get a chart on the NSE calendar from Yahoo's history."""

import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from screener import universe
from screener.markets import resolve
from tools.publish_price_series import bse_only_rows

SESSIONS = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(40)]


class BseOnlyRowsTests(unittest.TestCase):
    def _rows(self, symbols):
        asked = {}

        def collect(wanted, profile, *, start, end):
            asked["symbols"] = list(wanted)
            return {symbol: {day: (100.0 + i, 10) for i, day in enumerate(SESSIONS)} for symbol in wanted}

        result = universe.UniverseResult(tuple(symbols), "https://example.test", "ok")
        args = SimpleNamespace(end=None, min_points=30)
        rows = bse_only_rows(
            args, resolve("NSE"), SESSIONS,
            fetch_universe=lambda profile, config: result, collect=collect,
        )
        return rows, asked.get("symbols")

    def test_only_bse_only_symbols_are_fetched_and_charted(self):
        rows, asked = self._rows(["RELIANCE", "TANFACIND.BO"])
        self.assertEqual(asked, ["TANFACIND.BO"])
        self.assertEqual([row["symbol"] for row in rows], ["TANFACIND.BO"])
        self.assertEqual(rows[0]["points"], len(SESSIONS))

    def test_an_nse_only_universe_fetches_nothing(self):
        rows, asked = self._rows(["RELIANCE"])
        self.assertEqual((rows, asked), ([], None))


if __name__ == "__main__":
    unittest.main()
