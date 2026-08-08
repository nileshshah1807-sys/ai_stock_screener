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

    def test_report_never_renders_nan_as_company(self):
        self.assertEqual(company_label(pd.Series({"Company": float("nan"), "Symbol": "INFY"})), "INFY")
        self.assertEqual(company_label(pd.Series({"Company": "Infosys Limited", "Symbol": "INFY"})), "Infosys Limited")

    def test_cache_refreshes_rows_with_missing_company_names(self):
        cache = pd.DataFrame([
            {
                "Symbol": "INFY", "Company": float("nan"),
                "Cached_Date": datetime.now().strftime("%Y-%m-%d"),
                "Sector": "Technology", "Industry": "Information Technology Services",
                "Total_Debt": 0, "Total_Cash": 0,
            },
            {
                "Symbol": "TCS", "Company": "Tata Consultancy Services Limited",
                "Cached_Date": datetime.now().strftime("%Y-%m-%d"),
                "Sector": "Technology", "Industry": "Information Technology Services",
                "Total_Debt": 0, "Total_Cash": 0,
            },
        ])
        fresh, stale = StockDataCollector._split_cache(cache, max_age_days=7)
        self.assertEqual([row["Symbol"] for row in fresh], ["TCS"])
        self.assertEqual(stale, {"INFY"})


if __name__ == "__main__":
    unittest.main()
