import os
import tempfile
import unittest
from unittest.mock import patch

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

    @patch("app.requests.post")
    def test_brevo_email_posts_payload_with_attachment(self, mock_post):
        class Response:
            status_code = 201
            text = '{"messageId":"abc"}'

        mock_post.return_value = Response()
        self.config.EMAIL_ENABLED = True
        self.config.EMAIL_DELIVERY_METHOD = "BREVO"
        self.config.BREVO_API_KEY = "test-key"
        self.config.EMAIL_SENDER = "sender@example.com"
        self.config.EMAIL_RECEIVER = "one@example.com,two@example.com"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(b"Symbol,Rating\nTEST,BUY\n")
            csv_path = tmp.name
        try:
            result = EmailReporter(self.config).send_email("<html>ok</html>", "21-07-2026", csv_path)
            self.assertTrue(result)
        finally:
            os.unlink(csv_path)

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["api-key"], "test-key")
        self.assertEqual(kwargs["json"]["to"], [{"email": "one@example.com"}, {"email": "two@example.com"}])
        self.assertEqual(kwargs["json"]["attachment"][0]["name"], os.path.basename(csv_path))
        self.assertTrue(kwargs["json"]["attachment"][0]["content"])

    @patch("app.requests.post")
    def test_gmail_api_refreshes_token_and_sends_raw_message(self, mock_post):
        class TokenResponse:
            status_code = 200
            text = '{"access_token":"access-token"}'

            def json(self):
                return {"access_token": "access-token"}

        class SendResponse:
            status_code = 200
            text = '{"id":"message-id"}'

            def json(self):
                return {"id": "message-id"}

        mock_post.side_effect = [TokenResponse(), SendResponse()]
        self.config.EMAIL_ENABLED = True
        self.config.EMAIL_DELIVERY_METHOD = "GMAIL_API"
        self.config.GMAIL_CLIENT_ID = "client-id"
        self.config.GMAIL_CLIENT_SECRET = "client-secret"
        self.config.GMAIL_REFRESH_TOKEN = "refresh-token"
        self.config.EMAIL_SENDER = "sender@gmail.com"
        self.config.EMAIL_RECEIVER = "receiver@gmail.com"

        result = EmailReporter(self.config).send_email("<html>ok</html>", "21-07-2026")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)
        token_call = mock_post.call_args_list[0]
        send_call = mock_post.call_args_list[1]
        self.assertEqual(token_call.kwargs["data"]["grant_type"], "refresh_token")
        self.assertEqual(send_call.kwargs["headers"]["authorization"], "Bearer access-token")
        self.assertIn("raw", send_call.kwargs["json"])


if __name__ == "__main__":
    unittest.main()
