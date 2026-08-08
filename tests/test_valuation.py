import unittest
from types import SimpleNamespace

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
        REVERSE_DCF_BASE_GROWTH=0.15,
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


if __name__ == "__main__":
    unittest.main()
