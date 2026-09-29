"""The pre-download price-bar probe (screener/price_probe.py).

Regression for the 28 Sept 2026 US run: Yahoo served the session's row with
empty close/volume values for ~97% of the universe, and the run only learned
that after an eleven minute download. The probe reaches the same verdict from
a 20-symbol request.
"""

import inspect
import re
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from screener import price_probe
from screener.data_collection import StockDataCollector
from screener.price_probe import probe_expected_session
from screener.runtime import Config

TZ = "America/New_York"
EXPECTED = date(2026, 9, 28)
SYMBOLS = [f"S{i}" for i in range(10)]


def _frame(symbols, usable_today):
    """Yahoo-shaped daily frame; ``usable_today`` symbols have a filled 28 Sep row."""
    index = pd.DatetimeIndex(["2026-09-25", "2026-09-28"], tz=TZ, name="Date")
    parts = {}
    for symbol in symbols:
        today_value = 10.0 if symbol in usable_today else np.nan
        for field in ("Close", "Adj Close", "Volume"):
            parts[(symbol, field)] = [9.0, today_value]
    return pd.DataFrame(parts, index=index)


def _downloader(frame):
    return lambda *args, **kwargs: frame


class PriceProbeTests(unittest.TestCase):
    def probe(self, frame, symbols=SYMBOLS, minimum=0.5):
        return probe_expected_session(
            symbols, EXPECTED, TZ, minimum, downloader=_downloader(frame)
        )

    def test_finalised_session_passes(self):
        self.assertEqual(self.probe(_frame(SYMBOLS, set(SYMBOLS))), (10, 10))

    def test_row_present_but_unfilled_stops_the_run(self):
        # The row for the expected date exists, with NaN values: the last
        # *usable* bar is Friday, exactly what the alignment guard sees.
        with self.assertRaisesRegex(
            RuntimeError, r"only 0/10 \(0%\) bellwether .* 2026-09-28"
        ):
            self.probe(_frame(SYMBOLS, set()))

    def test_share_is_compared_with_the_floor(self):
        self.probe(_frame(SYMBOLS, set(SYMBOLS[:6])))
        with self.assertRaisesRegex(RuntimeError, r"4/10"):
            self.probe(_frame(SYMBOLS, set(SYMBOLS[:4])))

    def test_vendor_error_is_inconclusive_not_fatal(self):
        def boom(*args, **kwargs):
            raise ConnectionError("yahoo unreachable")

        self.assertIsNone(
            probe_expected_session(SYMBOLS, EXPECTED, TZ, 0.5, downloader=boom)
        )

    def test_empty_response_is_inconclusive_not_fatal(self):
        self.assertIsNone(self.probe(pd.DataFrame()))

    def test_too_few_symbols_never_calls_the_vendor(self):
        def fail(*args, **kwargs):
            raise AssertionError("vendor must not be called")

        self.assertIsNone(
            probe_expected_session(
                SYMBOLS[: price_probe.MIN_PROBE_SYMBOLS - 1],
                EXPECTED,
                TZ,
                0.5,
                downloader=fail,
            )
        )

    def test_symbols_absent_from_the_response_are_not_evidence(self):
        # Ten asked, only six answered, all six unfilled: still a verdict.
        # Ten asked, only three answered: too little to condemn a run.
        with self.assertRaises(RuntimeError):
            self.probe(_frame(SYMBOLS[:6], set()))
        self.assertIsNone(self.probe(_frame(SYMBOLS[:3], set())))

    def test_request_is_capped(self):
        seen = {}

        def capture(tickers, **kwargs):
            seen["count"] = len(tickers.split())
            return _frame(SYMBOLS, set(SYMBOLS))

        many = [f"T{i}" for i in range(price_probe.MAX_PROBE_SYMBOLS + 15)]
        probe_expected_session(many, EXPECTED, TZ, 0.5, downloader=capture)
        self.assertEqual(seen["count"], price_probe.MAX_PROBE_SYMBOLS)


class ProbeWiringTests(unittest.TestCase):
    def test_off_unless_a_workflow_opts_in(self):
        self.assertIs(Config.PRICE_BAR_PROBE_ENABLED, False)

    def test_only_the_us_workflow_opts_in(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        pattern = re.compile(r'PRICE_BAR_PROBE_ENABLED:\s*"True"')
        self.assertRegex((workflows / "daily-us-screener.yml").read_text(), pattern)
        self.assertNotRegex(
            (workflows / "daily-stock-screener.yml").read_text(), pattern
        )

    def test_probe_runs_before_the_batch_download(self):
        source = inspect.getsource(StockDataCollector.download_stock_data)
        self.assertLess(
            source.index("probe_expected_session("), source.index("yf.download(")
        )


if __name__ == "__main__":
    unittest.main()
