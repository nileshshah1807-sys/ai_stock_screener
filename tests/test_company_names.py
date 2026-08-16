import unittest
from datetime import datetime

import pandas as pd

from screener.data_collection import StockDataCollector
from screener.reporting import company_label


class CompanyNameTests(unittest.TestCase):
    def test_yahoo_name_uses_long_name_first(self):
        name = StockDataCollector._company_name(
            {"longName": "Reliance Industries Limited", "shortName": "Reliance"},
            "RELIANCE",
        )
        self.assertEqual(name, "Reliance Industries Limited")

    def test_yahoo_name_has_non_blank_fallbacks(self):
        self.assertEqual(
            StockDataCollector._company_name({"shortName": "TCS"}, "TCS"),
            "TCS",
        )
        self.assertEqual(StockDataCollector._company_name({}, "INFY"), "INFY")
        self.assertEqual(StockDataCollector._company_name(None, "HDFCBANK"), "HDFCBANK")

    def test_yahoo_website_is_normalized_for_logo_lookup(self):
        self.assertEqual(
            StockDataCollector._company_logo_domain(
                {"website": "https://www.infosys.com/investors/"}
            ),
            "infosys.com",
        )
        self.assertEqual(
            StockDataCollector._company_logo_domain({"website": "tcs.com"}),
            "tcs.com",
        )

    def test_missing_or_invalid_yahoo_website_has_no_logo_domain(self):
        self.assertIsNone(StockDataCollector._company_logo_domain({}))
        self.assertIsNone(StockDataCollector._company_logo_domain(None))
        self.assertIsNone(
            StockDataCollector._company_logo_domain({"website": "://bad"})
        )

    def test_report_never_renders_nan_as_company(self):
        self.assertEqual(company_label(pd.Series({"Company": float("nan"), "Symbol": "INFY"})), "INFY")
        self.assertEqual(company_label(pd.Series({"Company": "Infosys Limited", "Symbol": "INFY"})), "Infosys Limited")

    def test_cache_refreshes_rows_with_missing_company_names(self):
        cache = pd.DataFrame([
            {
                "Symbol": "INFY", "Company": float("nan"),
                "Logo_Domain": "infosys.com",
                "Cached_Date": datetime.now().strftime("%Y-%m-%d"),
                "Sector": "Technology", "Industry": "Information Technology Services",
                "EPS": 1, "Book_Value": 1, "Shares_Outstanding": 1, "EBITDA": 1,
                "Total_Debt": 0, "Total_Cash": 0, "Dividend_Rate": 0,
                "Fundamental_Fetched_At": datetime.now().isoformat(),
                "Fundamental_Source": "Yahoo Finance quote metadata",
            },
            {
                "Symbol": "TCS", "Company": "Tata Consultancy Services Limited",
                "Logo_Domain": "tcs.com",
                "Cached_Date": datetime.now().strftime("%Y-%m-%d"),
                "Sector": "Technology", "Industry": "Information Technology Services",
                "EPS": 1, "Book_Value": 1, "Shares_Outstanding": 1, "EBITDA": 1,
                "Total_Debt": 0, "Total_Cash": 0, "Dividend_Rate": 0,
                "Fundamental_Fetched_At": datetime.now().isoformat(),
                "Fundamental_Source": "Yahoo Finance quote metadata",
            },
        ])
        fresh, stale = StockDataCollector._split_cache(cache, max_age_days=7)
        self.assertEqual([row["Symbol"] for row in fresh], ["TCS"])
        self.assertEqual(stale, {"INFY"})

    def test_cache_without_logo_domain_is_refreshed_once(self):
        cache = pd.DataFrame(
            [
                {
                    "Symbol": "TCS",
                    "Company": "Tata Consultancy Services Limited",
                    "Cached_Date": datetime.now().strftime("%Y-%m-%d"),
                }
            ]
        )

        fresh, stale = StockDataCollector._split_cache(cache, max_age_days=7)

        self.assertEqual(fresh, [])
        self.assertEqual(stale, {"TCS"})


if __name__ == "__main__":
    unittest.main()
