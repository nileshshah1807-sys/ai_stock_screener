import ast
import unittest
from pathlib import Path

import pandas as pd

from screener.numeric import round_half_up, round_series_half_up

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("screener", "scoring", "sentiment", "red_flags", "storage", "validation", "workers", "transcripts")
# Not exported model numbers, or not free to import screener.numeric.
EXEMPT = {
    # The speech piece jobs install the speech packages only; no pandas.
    "transcripts/speech.py",
    "workers/call_recordings.py",
    # Paise from a two-decimal quote: exact, no half to break.
    "workers/price_series.py",
}


class RoundingConventionTests(unittest.TestCase):
    def test_half_up_differs_from_the_builtin_at_exact_halves(self):
        self.assertEqual(round_half_up(72.25, 1), 72.3)
        self.assertEqual(round_half_up(2.675, 2), 2.68)
        self.assertEqual(list(round_series_half_up(pd.Series([72.25]), 1)), [72.3])

    def test_no_bare_round_in_first_party_code(self):
        # Python, NumPy and pandas round exact halves differently; every
        # exported number goes through screener.numeric instead.
        offenders = []
        files = [ROOT / "app.py"] + [path for package in PACKAGES for path in (ROOT / package).rglob("*.py")]
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            if relative in EXEMPT:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                bare = isinstance(node.func, ast.Name) and node.func.id == "round"
                method = isinstance(node.func, ast.Attribute) and node.func.attr == "round"
                if bare or method:
                    offenders.append(f"{relative}:{node.lineno}")
        self.assertEqual(offenders, [], "use round_half_up / round_series_half_up from screener.numeric")


if __name__ == "__main__":
    unittest.main()
