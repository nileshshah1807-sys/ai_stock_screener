"""Absent fundamental evidence must lower confidence, not assert the worst value.

Before this, every component scored 0 when its input was missing, so a company
whose vendor simply did not report ROA was scored as though it had the worst ROA
in the market. That silently cost SBCL 682 rank places in the 2026-08-11
validation run and affected 81.5% of the universe.
"""

import unittest

from screener.scoring import (
    FUNDAMENTAL_COMPONENT_MAX,
    StockScorer,
    fundamental_component_capacity,
    fundamental_score_details,
    score_financial_services,
    score_fundamentals,
    score_real_estate,
)


GENERIC = "Generic Fundamental Model"


def complete_row(**overrides):
    row = {
        "PE_Ratio": 15.0,
        "PB_Ratio": 1.5,
        "ROE": 0.22,
        "ROA": 0.12,
        "Debt_to_Equity": 20.0,
        "Current_Ratio": 2.5,
        "Profit_Margin": 0.18,
        "Revenue_Growth": 0.20,
        "Earnings_Growth": 0.25,
        "Dividend_Yield": 0.035,
        "EV_EBITDA": 8.0,
    }
    row.update(overrides)
    return row


class FundamentalCapacityTableTests(unittest.TestCase):
    def test_every_model_capacity_sums_to_the_declared_maximum(self):
        for model, capacity in FUNDAMENTAL_COMPONENT_MAX.items():
            with self.subTest(model=model):
                self.assertEqual(
                    sum(capacity.values()),
                    StockScorer.MAX_FUND_SCORE,
                    f"{model} capacity must sum to MAX_FUND_SCORE",
                )

    def test_fundamental_capacity_tables_match_scorers(self):
        """A declared cap must never be lower than the points a scorer can emit.

        This is the drift lock: the point curves live in the scorers while the
        capacity lives in the table, so a future change to one without the other
        would corrupt every coverage calculation.
        """

        ideal = complete_row(
            Gross_NPA=0.5, Net_NPA=0.2, Capital_Adequacy=20.0, Solvency_Ratio=2.0
        )
        cases = [
            (GENERIC, score_fundamentals(ideal, return_components=True)),
            ("Real Estate Asset Model", score_real_estate(ideal, return_components=True)),
        ]
        for model in (
            "Bank Equity Quality Model",
            "NBFC Equity Quality Model",
            "Insurance Equity Quality Model",
            "Capital Markets Earnings Quality Model",
            "Financial Services Data-Limited Model",
        ):
            cases.append(
                (
                    model,
                    score_financial_services(
                        ideal, fundamental_model=model, return_components=True
                    ),
                )
            )

        for model, components in cases:
            capacity = fundamental_component_capacity(model)
            with self.subTest(model=model):
                self.assertEqual(
                    set(components), set(capacity),
                    f"{model} components and capacity keys must match",
                )
                for key, points in components.items():
                    self.assertLessEqual(
                        points, capacity[key],
                        f"{model}.{key} emitted {points} above declared cap "
                        f"{capacity[key]}",
                    )


class MissingFundamentalEvidenceTests(unittest.TestCase):
    def test_complete_row_is_unshrunk(self):
        row = complete_row()
        details = fundamental_score_details(
            row, GENERIC, score_fundamentals(row, return_components=True)
        )

        self.assertEqual(details["coverage"], 1.0)
        self.assertEqual(details["missing_components"], [])
        self.assertEqual(details["adjusted_score"], details["observed_score"])

    def test_unreported_field_is_not_scored_as_the_worst_value(self):
        row = complete_row(ROA=None, Current_Ratio=None)
        components = score_fundamentals(row, return_components=True)
        details = fundamental_score_details(row, GENERIC, components)

        # ROA (5) + CR (7) leave the denominator entirely.
        self.assertEqual(details["observed_capacity"], 88.0)
        self.assertEqual(sorted(details["missing_components"]), ["CR", "ROA"])

        naive = sum(components.values())  # the old behaviour: missing == zero
        self.assertGreater(
            details["adjusted_score"], naive,
            "dropping unreported inputs must not score worse than a full row",
        )

    def test_shrinkage_always_moves_toward_neutral_and_never_past_it(self):
        """The adjusted score sits between the observed score and neutral 50.

        Dropping a component changes the observed score in whichever direction
        that component pointed -- removing strong evidence lowers it. What must
        always hold is that incomplete coverage moves the *final* number toward
        50 relative to the evidence actually seen, never beyond it.
        """

        rows = [
            complete_row(),
            complete_row(ROA=None, Current_Ratio=None),
            complete_row(
                PE_Ratio=90.0, PB_Ratio=14.0, ROE=0.01, Profit_Margin=0.001,
                Revenue_Growth=-0.2, Earnings_Growth=-0.3, EV_EBITDA=60.0,
            ),
            complete_row(
                PE_Ratio=90.0, ROE=0.01, ROA=None, Current_Ratio=None,
                Debt_to_Equity=None, Earnings_Growth=None,
            ),
        ]
        for index, row in enumerate(rows):
            details = fundamental_score_details(
                row, GENERIC, score_fundamentals(row, return_components=True)
            )
            observed = details["observed_score"]
            adjusted = details["adjusted_score"]
            with self.subTest(row=index):
                low, high = sorted((observed, 50.0))
                self.assertGreaterEqual(adjusted, low - 1e-9)
                self.assertLessEqual(adjusted, high + 1e-9)

    def test_strong_company_with_gaps_is_pulled_down_toward_neutral(self):
        strong_row = complete_row()
        strong = fundamental_score_details(
            strong_row, GENERIC, score_fundamentals(strong_row, return_components=True)
        )
        gapped_row = complete_row(ROA=None, Current_Ratio=None, EV_EBITDA=None)
        gapped = fundamental_score_details(
            gapped_row, GENERIC, score_fundamentals(gapped_row, return_components=True)
        )

        self.assertGreater(strong["adjusted_score"], 50.0)
        self.assertLess(gapped["adjusted_score"], strong["adjusted_score"])
        self.assertGreater(gapped["adjusted_score"], 50.0)

    def test_absent_dividend_is_treated_as_unreported_not_as_zero_income(self):
        """The feed cannot separate "pays nothing" from "not reported".

        Scoring absence as a zero would penalise a paying company whose data is
        merely missing, so dividend yield is excluded like any other gap until
        the collector can record an explicit 0.0.
        """

        row = complete_row(Dividend_Yield=None)
        details = fundamental_score_details(
            row, GENERIC, score_fundamentals(row, return_components=True)
        )

        self.assertIn("DY", details["missing_components"])
        self.assertEqual(details["observed_capacity"], 95.0)

    def test_no_observable_evidence_is_exactly_neutral(self):
        row = {"Symbol": "EMPTY"}
        details = fundamental_score_details(
            row, GENERIC, score_fundamentals(row, return_components=True)
        )

        self.assertEqual(details["adjusted_score"], 50.0)
        self.assertEqual(details["coverage"], 0.0)


if __name__ == "__main__":
    unittest.main()
