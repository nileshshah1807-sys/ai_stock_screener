"""Expectations-gap diagnostics.

The whole value of this column is that absence reads as absence. Forward
estimates are missing for 55% of the universe, so a bug that renders "no
consensus published" as "no expected decline" would put a reassurance the model
has not earned next to exactly the rows nobody is covering.
"""

import unittest

import numpy as np
import pandas as pd

from screener.expectations import (
    attach_expectations_gap,
    expected_earnings_change,
    guidance_transition,
    implied_growth_gap,
)


def frame(**overrides):
    """One row with healthy defaults; override what the test is about."""
    row = {
        "Symbol": "TEST",
        "Current_Price": 100.0,
        "Forward_PE": 10.0,
        "EPS": 10.0,
        "DCF_Implied_FCF_CAGR": 0.10,
        "DCF_Assumed_Growth": 0.12,
        "DCF_Solve_State": "within_range",
        "Transcript_Scoring_Eligible": True,
        "Transcript_Previous_Guidance": "raised",
        "Transcript_Guidance": "raised",
    }
    row.update(overrides)
    return pd.DataFrame([row])


class ExpectedEarningsChangeTests(unittest.TestCase):
    def test_forward_pe_above_trailing_reads_as_a_decline(self):
        # The LUPIN case: 2188 / 21.40 = 102.22 against a trailing 120.66.
        out = attach_expectations_gap(
            frame(Current_Price=2188.0, Forward_PE=21.404266, EPS=120.66)
        ).iloc[0]
        self.assertAlmostEqual(out["Expected_EPS_Forward"], 102.22, places=1)
        self.assertAlmostEqual(out["Expected_EPS_Change_Pct"], -15.28, places=1)
        self.assertEqual(out["Expectations_Status"], "Priced for decline")
        self.assertIn("earnings decline", out["Expectations_Warning"])

    def test_forward_pe_below_trailing_reads_as_growth_and_does_not_warn(self):
        out = attach_expectations_gap(
            frame(Current_Price=100.0, Forward_PE=8.0, EPS=10.0)
        ).iloc[0]
        self.assertEqual(out["Expectations_Status"], "Priced for growth")
        self.assertEqual(out["Expectations_Warning"], "")

    def test_missing_forward_pe_is_unavailable_not_reassurance(self):
        out = attach_expectations_gap(frame(Forward_PE=np.nan)).iloc[0]
        self.assertEqual(
            out["Expectations_Status"], "Unavailable: no forward estimate"
        )
        self.assertTrue(pd.isna(out["Expected_EPS_Change_Pct"]))
        self.assertEqual(out["Expectations_Warning"], "")

    def test_trailing_loss_gives_no_ratio(self):
        """A percentage change against a negative base is not information."""
        out = attach_expectations_gap(frame(EPS=-4.0)).iloc[0]
        self.assertEqual(out["Expectations_Status"], "Unavailable: trailing loss")
        self.assertTrue(pd.isna(out["Expected_EPS_Change_Pct"]))

    def test_negative_forward_pe_is_a_loss_and_warns(self):
        out = attach_expectations_gap(frame(Forward_PE=-12.0)).iloc[0]
        self.assertEqual(out["Expectations_Status"], "Priced for a loss")
        self.assertIn("expects a loss", out["Expectations_Warning"])

    def test_absent_columns_do_not_raise(self):
        """A 4.x run carries no DCF solve state and no transcript columns."""
        out = attach_expectations_gap(
            pd.DataFrame([{"Symbol": "X", "Current_Price": 50.0}])
        ).iloc[0]
        self.assertEqual(
            out["Expectations_Status"], "Unavailable: no forward estimate"
        )
        self.assertEqual(out["Expectations_Warning"], "")

    def test_status_is_never_null(self):
        prices, fpes, epss = [100.0, np.nan, 0.0], [10.0, 10.0, np.nan], [np.nan, 5.0, 5.0]
        _eps, _chg, status = expected_earnings_change(
            pd.Series(prices), pd.Series(fpes), pd.Series(epss)
        )
        self.assertTrue(status.notna().all())
        self.assertTrue((status.astype(str).str.len() > 0).all())


class ImpliedGrowthGapTests(unittest.TestCase):
    def test_gap_is_implied_minus_assumed_in_points(self):
        gap = implied_growth_gap(
            pd.Series([0.0985]), pd.Series([0.145]), pd.Series(["within_range"])
        )
        self.assertAlmostEqual(gap.iloc[0], -4.65, places=2)

    def test_censored_solve_is_not_reported_as_an_expectation(self):
        """A bound means the solver left the interval; it found no solution."""
        for state in ("censored_upper", "censored_lower", "failed", ""):
            gap = implied_growth_gap(
                pd.Series([0.0985]), pd.Series([0.145]), pd.Series([state])
            )
            self.assertTrue(pd.isna(gap.iloc[0]), state)

    def test_gap_never_raises_a_warning(self):
        """Deliberate: it is near-symmetric about zero across the universe.

        Wired to the warning it fired on 22.6% of rows, because
        `DCF_Assumed_Growth` is a sector template rather than a company
        forecast. It stays a per-stock diagnostic.
        """
        out = attach_expectations_gap(
            frame(DCF_Implied_FCF_CAGR=0.02, DCF_Assumed_Growth=0.20)
        ).iloc[0]
        self.assertAlmostEqual(out["Implied_Growth_Gap_Pct"], -18.0, places=1)
        self.assertEqual(out["Expectations_Warning"], "")


class GuidanceTransitionTests(unittest.TestCase):
    def test_withdrawn_guidance_is_a_downgrade(self):
        out = attach_expectations_gap(
            frame(Transcript_Previous_Guidance="raised", Transcript_Guidance="unclear")
        ).iloc[0]
        self.assertEqual(out["Guidance_Transition"], "raised -> unclear")
        self.assertTrue(out["Guidance_Downgraded"])
        self.assertIn("Guidance moved", out["Expectations_Warning"])

    def test_unchanged_guidance_is_not_a_downgrade(self):
        out = attach_expectations_gap(frame()).iloc[0]
        self.assertEqual(out["Guidance_Transition"], "raised -> raised")
        self.assertFalse(out["Guidance_Downgraded"])
        self.assertEqual(out["Expectations_Warning"], "")

    def test_prior_cycle_transcripts_are_ignored(self):
        """A stale call describes a transition two quarters old."""
        out = attach_expectations_gap(
            frame(
                Transcript_Scoring_Eligible=False,
                Transcript_Previous_Guidance="raised",
                Transcript_Guidance="lowered",
            )
        ).iloc[0]
        self.assertEqual(out["Guidance_Transition"], "")
        self.assertFalse(out["Guidance_Downgraded"])

    def test_unrecognised_guidance_words_are_not_ranked(self):
        label, down = guidance_transition(
            pd.Series(["raised"]), pd.Series(["???"]), pd.Series([True])
        )
        self.assertEqual(label.iloc[0], "")
        self.assertFalse(bool(down.iloc[0]))


class WarningCompositionTests(unittest.TestCase):
    def test_two_signals_produce_two_sentences_not_four(self):
        """Regression: the first draft re-read the column it was writing.

        Appending with two `mask` calls keyed on "is the note empty yet" made
        the second call see the string the first had just written, so every
        multi-signal row got its sentence twice.
        """
        out = attach_expectations_gap(
            frame(
                Current_Price=2188.0,
                Forward_PE=21.404266,
                EPS=120.66,
                Transcript_Previous_Guidance="raised",
                Transcript_Guidance="unclear",
            )
        ).iloc[0]
        warning = out["Expectations_Warning"]
        self.assertEqual(warning.count("earnings decline"), 1)
        self.assertEqual(warning.count("Guidance moved"), 1)
        self.assertFalse(warning.startswith(" "))
        self.assertFalse(warning.endswith(" "))
        self.assertNotIn("  ", warning)

    def test_healthy_row_gets_an_empty_warning(self):
        self.assertEqual(attach_expectations_gap(frame()).iloc[0]["Expectations_Warning"], "")

    def test_empty_frame_is_returned_unchanged(self):
        empty = pd.DataFrame()
        self.assertIs(attach_expectations_gap(empty), empty)

    def test_nothing_that_scores_is_touched(self):
        """The module is display-only; it must add columns and change none."""
        before = frame(Research_Score=99.45, Rating="HOLD", Decision_Score=59.99)
        after = attach_expectations_gap(before)
        for column in before.columns:
            self.assertTrue(
                after[column].equals(before[column]), f"{column} was modified"
            )


if __name__ == "__main__":
    unittest.main()
