import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from screener.valuation import ReverseDCFModel


def config():
    return SimpleNamespace(
        REVERSE_DCF_FCF_MARGIN_FALLBACK=0.08,
        REVERSE_DCF_MIN_VALID_FCF_YIELD=0.005,
        REVERSE_DCF_FORECAST_YEARS=5,
        REVERSE_DCF_DISCOUNT_RATE=0.11,
        REVERSE_DCF_TERMINAL_GROWTH=0.04,
        REVERSE_DCF_MAX_TERMINAL_GROWTH=0.09,
        REVERSE_DCF_MIN_GROWTH=-0.30,
        REVERSE_DCF_MAX_GROWTH=0.60,
        REVERSE_DCF_MIN_TERMINAL_GROWTH=-0.05,
        REVERSE_DCF_RANKING_WEIGHT=0.10,
        REVERSE_DCF_SCORE_LOG_SCALE=1.0,
        REVERSE_DCF_NEUTRAL_LOG_BAND=0.05,
    )


class ReverseDCFTests(unittest.TestCase):
    def test_yahoo_free_cash_flow_proxy_is_solved_against_equity_value(self):
        model = ReverseDCFModel(config())
        base = {
            "Market_Cap": 1000.0,
            "Total_Revenue": 1200.0,
            "Free_CashFlow": 100.0,
            "Total_Cash": 0.0,
            "Sector": "Technology",
        }

        low_debt = model.analyze_row(pd.Series({**base, "Total_Debt": 0.0}))
        high_debt = model.analyze_row(pd.Series({**base, "Total_Debt": 1000.0}))

        self.assertEqual(low_debt["DCF_Status"], "OK")
        self.assertEqual(low_debt["DCF_EV_Method"], "equity_value_proxy")
        self.assertEqual(low_debt["DCF_Cash_Flow_Basis"], "operating_cash_flow_less_capex_equity_proxy")
        self.assertEqual(low_debt["DCF_FCF_Yield"], 0.1)
        self.assertEqual(low_debt["DCF_Implied_FCF_CAGR"], high_debt["DCF_Implied_FCF_CAGR"])
        self.assertNotEqual(low_debt["DCF_Enterprise_Value"], high_debt["DCF_Enterprise_Value"])

    def test_rate_solver_returns_symmetric_censored_bounds(self):
        model = ReverseDCFModel(config())
        value = lambda rate: 1.0 + rate

        below = model._solve_rate(0.5, value, 0.0, 1.0)
        within = model._solve_rate(1.5, value, 0.0, 1.0)
        above = model._solve_rate(3.0, value, 0.0, 1.0)

        self.assertEqual(below.state, "below_range")
        self.assertIsNone(below.point)
        self.assertEqual(below.upper_bound, 0.0)
        self.assertEqual(within.state, "within_range")
        self.assertAlmostEqual(within.point, 0.5)
        self.assertEqual(above.state, "above_range")
        self.assertIsNone(above.point)
        self.assertEqual(above.lower_bound, 1.0)

    def test_single_signal_score_is_smooth_monotonic_and_reciprocal(self):
        model = ReverseDCFModel(config())
        ratios = [0.25, 0.5, 1.0, 2.0, 4.0]
        scores = [model._valuation_score(ratio) for ratio in ratios]

        self.assertEqual(scores, sorted(scores))
        self.assertEqual(model._valuation_score(1.0), 50.0)
        self.assertAlmostEqual(
            model._valuation_score(0.5) + model._valuation_score(2.0),
            100.0,
            places=2,
        )
        self.assertGreater(scores[0], 0.0)
        self.assertLess(scores[-1], 100.0)
        self.assertGreater(model._valuation_score(1e-12), 0.0)
        self.assertLess(model._valuation_score(1e12), 100.0)

    def test_reported_low_yield_is_reliable_adverse_evidence(self):
        model = ReverseDCFModel(config())
        result = model.analyze_row(
            pd.Series(
                {
                    "Market_Cap": 1_000_000.0,
                    "Total_Revenue": 1_000_000.0,
                    "Free_CashFlow": 100.0,
                    "Sector": "Technology",
                }
            )
        )

        self.assertEqual(result["DCF_Status"], "low_fcf_yield")
        self.assertEqual(result["DCF_Source_Type"], "reported")
        self.assertEqual(result["DCF_Reliability"], "reported")
        self.assertEqual(result["DCF_Signal_Direction"], "adverse")
        self.assertTrue(result["DCF_Blend_Eligible"])
        self.assertEqual(result["DCF_Blend_Weight"], 0.10)
        self.assertLess(result["DCF_Valuation_Score"], 50.0)

    def test_estimated_cash_flow_is_neutral_and_not_blend_eligible(self):
        model = ReverseDCFModel(config())
        result = model.analyze_row(
            pd.Series(
                {
                    "Market_Cap": 1_000.0,
                    "Total_Revenue": 1_200.0,
                    "Free_CashFlow": np.nan,
                    "Sector": "Technology",
                }
            )
        )

        self.assertEqual(result["DCF_Status"], "estimated_fcf")
        self.assertEqual(result["DCF_Source_Type"], "estimated")
        self.assertEqual(result["DCF_Reliability"], "estimated")
        self.assertFalse(result["DCF_Blend_Eligible"])
        self.assertEqual(result["DCF_Blend_Weight"], 0.0)
        self.assertEqual(result["DCF_Valuation_Score"], 50.0)

    def test_reported_negative_cash_flow_is_not_replaced_by_revenue_margin(self):
        model = ReverseDCFModel(config())
        result = model.analyze_row(
            pd.Series(
                {
                    "Market_Cap": 1_000.0,
                    "Total_Revenue": 1_200.0,
                    "Free_CashFlow": -50.0,
                    "Sector": "Technology",
                }
            )
        )

        self.assertEqual(result["DCF_Status"], "negative_fcf")
        self.assertEqual(result["DCF_Source_Type"], "observed_negative")
        self.assertEqual(result["DCF_Reliability"], "reported_unmodeled")
        self.assertEqual(result["DCF_Base_FCF"], -50.0)
        self.assertFalse(result["DCF_Blend_Eligible"])
        self.assertEqual(result["DCF_Valuation_Score"], 50.0)
        self.assertTrue(result["DCF_Review_Required"])
        self.assertEqual(result["DCF_Cash_Flow_Quality"], "reported_nonpositive")

    def test_unsupported_sector_is_neutral_and_not_solved(self):
        model = ReverseDCFModel(config())
        result = model.analyze_row(
            pd.Series(
                {
                    "Market_Cap": 1_000.0,
                    "Total_Revenue": 1_200.0,
                    "Free_CashFlow": 100.0,
                    "Sector": "Financial Services",
                }
            )
        )

        self.assertEqual(result["DCF_Status"], "sector_not_supported")
        self.assertEqual(result["DCF_Reliability"], "unsupported")
        self.assertEqual(result["DCF_Solve_State"], "not_applicable")
        self.assertFalse(result["DCF_Blend_Eligible"])
        self.assertEqual(result["DCF_Valuation_Score"], 50.0)

    def test_censored_rate_is_not_published_as_an_exact_point(self):
        model = ReverseDCFModel(config())
        result = model.analyze_row(
            pd.Series(
                {
                    "Market_Cap": 1_000.0,
                    "Total_Revenue": 20_000.0,
                    "Free_CashFlow": 5_000.0,
                    "Sector": "Technology",
                }
            )
        )

        self.assertEqual(result["DCF_Solve_State"], "below_range")
        self.assertTrue(np.isnan(result["DCF_Implied_FCF_CAGR"]))
        self.assertEqual(result["DCF_Implied_FCF_CAGR_Upper_Bound"], -0.30)
        self.assertTrue(result["DCF_Blend_Eligible"])

    def test_enrichment_is_evidence_only_and_preserves_order_and_decisions(self):
        model = ReverseDCFModel(config())
        source = pd.DataFrame(
            {
                "Symbol": ["SECOND", "FIRST"],
                "Combined_Score": [60.0, 70.0],
                "Rating": ["BUY", "STRONG BUY"],
                "Rank": [2, 1],
                "Market_Cap": [1_000.0, 1_000.0],
                "Total_Revenue": [1_200.0, 1_200.0],
                "Free_CashFlow": [100.0, 100.0],
                "Sector": ["Technology", "Technology"],
            }
        )
        original = source.copy(deep=True)

        result = model.enrich(source)

        self.assertEqual(result["Symbol"].tolist(), source["Symbol"].tolist())
        self.assertEqual(result["Rating"].tolist(), source["Rating"].tolist())
        self.assertEqual(result["Rank"].tolist(), source["Rank"].tolist())
        self.assertNotIn("Final_Score", result)
        self.assertIn("DCF_Blend_Eligible", result)
        pd.testing.assert_frame_equal(source, original)

    def test_enrichment_retry_replaces_evidence_without_duplicate_columns(self):
        model = ReverseDCFModel(config())
        source = pd.DataFrame(
            {
                "Symbol": ["ROW"],
                "Combined_Score": [65.0],
                "Market_Cap": [1_000.0],
                "Total_Revenue": [1_200.0],
                "Free_CashFlow": [100.0],
                "Sector": ["Technology"],
            }
        )

        first = model.enrich(source)
        second = model.enrich(first)

        self.assertTrue(second.columns.is_unique)
        self.assertEqual(
            first.loc[0, "DCF_Valuation_Score"],
            second.loc[0, "DCF_Valuation_Score"],
        )

    def test_legacy_pre_dcf_aliases_are_sourced_from_core_diagnostics(self):
        model = ReverseDCFModel(config())
        source = pd.DataFrame(
            {
                "Symbol": ["ROW"],
                "Combined_Score": [65.0],
                "Core_Rating": ["BUY"],
                "Core_Score_Rank": [7],
                # Canonical-looking values must not override Core_* evidence.
                "Rating": ["SELL"],
                "Rank": [99],
                "Market_Cap": [1_000.0],
                "Total_Revenue": [1_200.0],
                "Free_CashFlow": [100.0],
                "Sector": ["Technology"],
            }
        )

        result = model.enrich(source)

        self.assertEqual(result.loc[0, "Pre_DCF_Combined_Score"], 65.0)
        self.assertEqual(result.loc[0, "Pre_DCF_Rating"], "BUY")
        self.assertEqual(result.loc[0, "Pre_DCF_Rank"], 7)


if __name__ == "__main__":
    unittest.main()
