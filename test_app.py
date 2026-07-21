import os
import tempfile
import unittest

import pandas as pd

from app import Config, EmailReporter, ReverseDCFModel


class TestReverseDCF(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.config.EMAIL_ENABLED = False
        self.config.TOP_STOCKS_COUNT = 2

    def sample_scored_df(self):
        return pd.DataFrame([
            {
                "Rank": 1,
                "Symbol": "TEST",
                "Current_Price": 100.0,
                "Rating": "BUY",
                "Combined_Score": 65.0,
                "Fundamental_Score": 70.0,
                "Technical_Score": 55.0,
                "Dynamic_Weight_Fund": 0.7,
                "Dynamic_Weight_Tech": 0.3,
                "Rating_Capped": False,
                "PE_Ratio": 20.0,
                "ADX_14": 30.0,
                "StochRSI_14": 45.0,
                "ATR_14": 2.0,
                "Market_Cap": 10_000_000_000.0,
                "Free_CashFlow": 700_000_000.0,
                "Total_Revenue": 8_000_000_000.0,
            },
            {
                "Rank": 2,
                "Symbol": "FALLBACK",
                "Current_Price": 50.0,
                "Rating": "HOLD",
                "Combined_Score": 55.0,
                "Fundamental_Score": 58.0,
                "Technical_Score": 48.0,
                "Dynamic_Weight_Fund": 0.7,
                "Dynamic_Weight_Tech": 0.3,
                "Rating_Capped": False,
                "PE_Ratio": 18.0,
                "ADX_14": 25.0,
                "StochRSI_14": 50.0,
                "ATR_14": 1.5,
                "Market_Cap": 5_000_000_000.0,
                "Free_CashFlow": None,
                "Total_Revenue": 6_000_000_000.0,
            },
        ])

    def test_reverse_dcf_enriches_rows(self):
        enriched = ReverseDCFModel(self.config).enrich(self.sample_scored_df())

        self.assertIn("DCF_Implied_FCF_CAGR", enriched.columns)
        self.assertIn("DCF_Implied_Terminal_Growth", enriched.columns)
        self.assertEqual(enriched.loc[0, "DCF_Status"], "OK")
        self.assertEqual(enriched.loc[1, "DCF_FCF_Source"], "revenue_margin_fallback")
        self.assertGreater(enriched.loc[0, "DCF_Base_Case_Value"], 0)

    def test_email_html_contains_reverse_dcf_table(self):
        enriched = ReverseDCFModel(self.config).enrich(self.sample_scored_df())
        html = EmailReporter(self.config).create_html_report(enriched, "21-07-2026")

        self.assertIn("Reverse DCF: Market-Implied Expectations", html)
        self.assertIn("Implied 5Y FCF CAGR", html)
        self.assertIn("TEST", html)

    def test_disabled_email_does_not_send(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            csv_path = tmp.name
        try:
            result = EmailReporter(self.config).send_email("<html></html>", "21-07-2026", csv_path)
            self.assertFalse(result)
        finally:
            os.unlink(csv_path)


if __name__ == "__main__":
    unittest.main()
