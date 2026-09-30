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
from tests.test_markets import config_with_env_cleared

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


def _frame_mid_session(symbols, usable_today):
    """``_frame`` plus the partial row Yahoo serves for the live 29 Sep session."""
    index = pd.DatetimeIndex(["2026-09-25", "2026-09-28", "2026-09-29"], tz=TZ)
    parts = {}
    for symbol in symbols:
        expected_value = 10.0 if symbol in usable_today else np.nan
        for field in ("Close", "Adj Close", "Volume"):
            parts[(symbol, field)] = [9.0, expected_value, 5.0]
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

    def test_live_partial_bar_for_the_current_session_is_ignored(self):
        # Dispatched at 12:13 ET on 29 Sep: the expected session is still 28 Sep
        # and Yahoo already serves a partial 29 Sep row. Regression: the probe
        # took that row as the last bar and failed the run on 0/20.
        frame = _frame_mid_session(SYMBOLS, set(SYMBOLS))
        self.assertEqual(self.probe(frame), (10, 10))

    def test_live_partial_bar_does_not_hide_a_session_that_is_missing(self):
        # 28 Sep unfilled: the live 29 Sep row must not stand in for it.
        with self.assertRaisesRegex(RuntimeError, r"only 0/10"):
            self.probe(_frame_mid_session(SYMBOLS, set()))

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


class _FakeClock:
    """Monotonic clock that only moves when the probe sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class ProbeWaitTests(unittest.TestCase):
    """Waiting inside the job for Yahoo to finalise, rather than failing the slot."""

    def setUp(self):
        self.clock = _FakeClock()

    def probe(self, answers, wait_seconds):
        stream = iter(answers)

        def download(*args, **kwargs):
            answer = next(stream)
            if isinstance(answer, Exception):
                raise answer
            return answer

        return probe_expected_session(
            SYMBOLS,
            EXPECTED,
            TZ,
            0.5,
            downloader=download,
            wait_seconds=wait_seconds,
            retry_interval_seconds=900,
            sleep=self.clock.sleep,
            clock=self.clock,
        )

    def test_session_finalised_while_waiting_passes(self):
        # The 00:40 UTC run of 30 Sept 2026 failed on 0/20 at once; the bars
        # were there a few hours later, but no later cron slot fired.
        unfilled, filled = _frame(SYMBOLS, set()), _frame(SYMBOLS, set(SYMBOLS))
        self.assertEqual(self.probe([unfilled, unfilled, filled], 3600), (10, 10))
        self.assertEqual(self.clock.sleeps, [900, 900])

    def test_gives_up_when_the_wait_is_spent_with_a_trimmed_last_pause(self):
        with self.assertRaisesRegex(RuntimeError, r"only 0/10"):
            self.probe([_frame(SYMBOLS, set())] * 10, 2000)
        self.assertEqual(self.clock.sleeps, [900, 900, 200])

    def test_no_wait_fails_at_once(self):
        with self.assertRaises(RuntimeError):
            self.probe([_frame(SYMBOLS, set())], 0)
        self.assertEqual(self.clock.sleeps, [])

    def test_vendor_error_while_waiting_is_still_inconclusive(self):
        answers = [_frame(SYMBOLS, set()), ConnectionError("yahoo unreachable")]
        self.assertIsNone(self.probe(answers, 3600))


class ProbeWiringTests(unittest.TestCase):
    def test_off_unless_a_workflow_opts_in(self):
        # The US workflow sets the flag at job level and it leaks into its
        # regression-test step, so the default has to be read from a Config
        # built with the variable cleared -- the run of 29 Sept 2026 failed here.
        Config = config_with_env_cleared(
            "PRICE_BAR_PROBE_ENABLED", "PRICE_BAR_PROBE_WAIT_MINUTES"
        )
        self.assertIs(Config.PRICE_BAR_PROBE_ENABLED, False)
        # And an unset environment fails at once, as before waiting existed.
        self.assertEqual(Config.PRICE_BAR_PROBE_WAIT_MINUTES, 0.0)

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
