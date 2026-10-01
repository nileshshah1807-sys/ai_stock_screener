"""SEC EDGAR statement source (screener/edgar.py).

Facts are built by hand in the shape of a ``companyfacts`` payload, so nothing
here touches the network.
"""

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import requests

from screener import edgar
from screener.statements import (
    FinancialStatementCollector,
    apply_statement_fallbacks,
    derive_statement_factors,
)

TODAY = date(2026, 3, 1)
YEARS = (2025, 2024, 2023, 2022)


def duration(year, value, *, filed=None, form="10-K"):
    return {
        "start": f"{year}-01-01",
        "end": f"{year}-12-31",
        "val": value,
        "form": form,
        "filed": filed or f"{year + 1}-02-15",
    }


def instant(year, value, *, filed=None, form="10-K"):
    return {"end": f"{year}-12-31", "val": value, "form": form, "filed": filed or f"{year + 1}-02-15"}


def facts(concepts, *, taxonomy="us-gaap", dei=None):
    """``{concept: (unit, [entries])}`` -> companyfacts payload."""
    payload = {
        "facts": {
            taxonomy: {
                name: {"units": {unit: entries}} for name, (unit, entries) in concepts.items()
            }
        }
    }
    if dei:
        payload["facts"]["dei"] = {
            name: {"units": {unit: entries}} for name, (unit, entries) in dei.items()
        }
    return payload


def company(**overrides):
    """A plain four-year industrial filer; override or drop concepts by name."""
    concepts = {
        "Revenues": ("USD", [duration(y, 1000 + 100 * i) for i, y in enumerate(reversed(YEARS))]),
        "NetIncomeLoss": ("USD", [duration(y, 100.0) for y in YEARS]),
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": (
            "USD", [duration(y, 125.0) for y in YEARS]),
        "IncomeTaxExpenseBenefit": ("USD", [duration(y, 25.0) for y in YEARS]),
        "InterestExpense": ("USD", [duration(y, 15.0) for y in YEARS]),
        "DepreciationDepletionAndAmortization": ("USD", [duration(y, 40.0) for y in YEARS]),
        "EarningsPerShareDiluted": ("USD/shares", [duration(y, 2.0) for y in YEARS]),
        "Assets": ("USD", [instant(y, 2000.0) for y in YEARS]),
        "StockholdersEquity": ("USD", [instant(y, 800.0) for y in YEARS]),
        "LongTermDebtNoncurrent": ("USD", [instant(y, 300.0) for y in YEARS]),
        "LongTermDebtCurrent": ("USD", [instant(y, 50.0) for y in YEARS]),
        "OperatingLeaseLiability": ("USD", [instant(y, 60.0) for y in YEARS]),
        "FinanceLeaseLiability": ("USD", [instant(y, 500.0) for y in YEARS]),
        "CashAndCashEquivalentsAtCarryingValue": ("USD", [instant(y, 120.0) for y in YEARS]),
        "CommonStockSharesOutstanding": ("shares", [instant(y, 50.0) for y in YEARS]),
        "WeightedAverageNumberOfSharesOutstandingBasic": ("shares", [duration(y, 50.0) for y in YEARS]),
        "AssetsCurrent": ("USD", [instant(y, 600.0) for y in YEARS]),
        "LiabilitiesCurrent": ("USD", [instant(y, 300.0) for y in YEARS]),
        "NetCashProvidedByUsedInOperatingActivities": ("USD", [duration(y, 150.0) for y in YEARS]),
        "PaymentsToAcquirePropertyPlantAndEquipment": ("USD", [duration(y, 30.0) for y in YEARS]),
    }
    for name, value in overrides.items():
        if value is None:
            concepts.pop(name, None)
        else:
            concepts[name] = value
    return concepts


def frames(concepts, **kwargs):
    return edgar.annual_frames(facts(concepts, **kwargs), today=TODAY)


def latest(frame, label):
    return float(frame.loc[label].iloc[0])


class AnnualFrameTests(unittest.TestCase):
    def test_frames_are_yahoo_shaped_and_newest_first(self):
        income, balance, cashflow = frames(company())
        self.assertEqual(list(income.columns), [pd.Timestamp(f"{y}-12-31") for y in YEARS])
        self.assertEqual(income.loc["Total Revenue"].tolist(), [1300.0, 1200.0, 1100.0, 1000.0])
        self.assertEqual(latest(balance, "Total Assets"), 2000.0)
        derived = derive_statement_factors(income, balance, cashflow)
        self.assertEqual(derived["Statement_Years"], 4)
        self.assertEqual(derived["Statement_Latest_Period"], "2025-12-31")
        self.assertAlmostEqual(derived["Revenue_CAGR_3Y"], 1.3 ** (1 / 3) - 1)

    def test_only_full_fiscal_years_from_annual_filings_count(self):
        revenue = [duration(y, 1000.0) for y in YEARS]
        revenue.append({"start": "2025-10-01", "end": "2025-12-31", "val": 9.0,
                        "form": "10-K", "filed": "2026-02-15"})
        revenue.append({"start": "2026-01-01", "end": "2026-03-31", "val": 7.0,
                        "form": "10-Q", "filed": "2026-04-30"})
        income, _, _ = frames(company(Revenues=("USD", revenue)))
        self.assertEqual(latest(income, "Total Revenue"), 1000.0)
        self.assertEqual(len(income.columns), 4)

    def test_a_restated_year_takes_the_most_recently_filed_value(self):
        net_income = [duration(y, 100.0) for y in YEARS]
        net_income.append(duration(2024, 80.0, filed="2026-02-15"))
        income, _, _ = frames(company(NetIncomeLoss=("USD", net_income)))
        self.assertEqual(income.loc["Net Income"].tolist(), [100.0, 80.0, 100.0, 100.0])

    def test_history_is_capped_at_four_fiscal_years(self):
        long_history = [duration(y, 1000.0) for y in range(2012, 2026)]
        income, _, _ = frames(company(Revenues=("USD", long_history)))
        self.assertEqual(len(income.columns), edgar.MAX_FISCAL_YEARS)

    def test_a_concept_change_mid_history_is_coalesced_per_year(self):
        concepts = company(
            Revenues=None,
            RevenueFromContractWithCustomerExcludingAssessedTax=(
                "USD", [duration(2025, 1300.0), duration(2024, 1200.0)]),
            SalesRevenueNet=("USD", [duration(2023, 1100.0), duration(2022, 1000.0)]),
        )
        income, _, _ = frames(concepts)
        self.assertEqual(income.loc["Total Revenue"].tolist(), [1300.0, 1200.0, 1100.0, 1000.0])

    def test_revenue_is_the_largest_alternative_not_the_first(self):
        # MetLife: fee income under the contract concept, the top line under Revenues.
        concepts = company(
            RevenueFromContractWithCustomerExcludingAssessedTax=(
                "USD", [duration(y, 30.0) for y in YEARS]),
        )
        income, _, _ = frames(concepts)
        self.assertEqual(latest(income, "Total Revenue"), 1300.0)

    def test_ebit_is_pretax_income_plus_interest_and_ebitda_adds_depreciation(self):
        income, _, _ = frames(company())
        self.assertEqual(latest(income, "EBIT"), 140.0)
        self.assertEqual(latest(income, "EBITDA"), 180.0)
        self.assertAlmostEqual(latest(income, "Tax Rate For Calcs"), 0.2)

    def test_a_loss_year_uses_the_statutory_tax_rate(self):
        pretax = ("USD", [duration(y, -50.0) for y in YEARS])
        income, _, _ = frames(company(
            IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest=pretax))
        self.assertEqual(latest(income, "Tax Rate For Calcs"), edgar.US_STATUTORY_TAX_RATE)

    def test_gross_profit_is_reported_or_revenue_less_total_cost_of_revenue(self):
        income, _, _ = frames(company(GrossProfit=("USD", [duration(y, 400.0) for y in YEARS])))
        self.assertEqual(latest(income, "Gross Profit"), 400.0)
        income, _, _ = frames(company(CostOfRevenue=("USD", [duration(y, 900.0) for y in YEARS])))
        self.assertEqual(latest(income, "Gross Profit"), 1300.0 - 900.0)
        # A cost-of-goods line may cover one segment; it is not a total.
        segment = company(CostOfGoodsAndServicesSold=("USD", [duration(y, 100.0) for y in YEARS]))
        self.assertNotIn("Gross Profit", frames(segment)[0].index)

    def test_ebitda_falls_back_to_depreciation_plus_amortisation(self):
        concepts = company(
            DepreciationDepletionAndAmortization=None,
            Depreciation=("USD", [duration(y, 30.0) for y in YEARS]),
            AmortizationOfIntangibleAssets=("USD", [duration(y, 5.0) for y in YEARS]),
        )
        self.assertEqual(latest(frames(concepts)[0], "EBITDA"), 140.0 + 35.0)

    def test_capex_is_signed_negative_and_free_cash_flow_follows(self):
        _, _, cashflow = frames(company())
        self.assertEqual(latest(cashflow, "Capital Expenditure"), -30.0)
        self.assertEqual(latest(cashflow, "Free Cash Flow"), 120.0)

    def test_a_bank_has_no_ebit_or_gross_profit(self):
        concepts = company(
            Revenues=None,
            Deposits=("USD", [instant(y, 5000.0) for y in YEARS]),
            InterestIncomeExpenseNet=("USD", [duration(y, 300.0) for y in YEARS]),
            NoninterestIncome=("USD", [duration(y, 200.0) for y in YEARS]),
            GrossProfit=("USD", [duration(y, 400.0) for y in YEARS]),
        )
        income, _, _ = frames(concepts)
        self.assertEqual(latest(income, "Total Revenue"), 500.0)
        for label in ("EBIT", "EBITDA", "Gross Profit", "Operating Income"):
            self.assertNotIn(label, income.index)


class PeriodAlignmentTests(unittest.TestCase):
    def test_a_line_not_tagged_for_the_newest_year_is_absent_not_stale(self):
        # Gross profit last tagged for 2023: it must not be read as "latest".
        concepts = company(GrossProfit=("USD", [duration(2023, 400.0), duration(2022, 390.0)]))
        income, balance, cashflow = frames(concepts)
        self.assertNotIn("Gross Profit", income.index)
        self.assertIsNone(
            derive_statement_factors(income, balance, cashflow)["Gross_Profit_To_Assets"]
        )

    def test_a_gap_ends_the_history_instead_of_closing_up(self):
        eps = [duration(2025, 2.0), duration(2024, 1.9), duration(2022, 1.0)]
        income, balance, cashflow = frames(company(EarningsPerShareDiluted=("USD/shares", eps)))
        derived = derive_statement_factors(income, balance, cashflow)
        self.assertAlmostEqual(derived["EPS_YoY_Latest"], 2.0 / 1.9 - 1)
        # Three years back is not observed; 2022 must not stand in for 2023.
        self.assertIsNone(derived["EPS_CAGR_3Y"])

    def test_a_filer_missing_core_figures_for_the_newest_year_is_unusable(self):
        stale_revenue = ("USD", [duration(2022, 1000.0)])
        self.assertIsNone(frames(company(Revenues=stale_revenue)))
        self.assertIsNone(frames(company(NetIncomeLoss=None)))
        self.assertIsNone(frames(company(Assets=None)))


class DebtTests(unittest.TestCase):
    def test_total_debt_adds_operating_leases_but_not_finance_leases(self):
        _, balance, _ = frames(company())
        self.assertEqual(latest(balance, "Total Debt"), 300.0 + 50.0 + 60.0)

    def test_invested_capital_is_equity_plus_borrowings_without_leases(self):
        _, balance, _ = frames(company())
        self.assertEqual(latest(balance, "Invested Capital"), 800.0 + 350.0)

    def test_current_maturities_are_not_counted_twice(self):
        concepts = company(
            LongTermDebt=("USD", [instant(y, 350.0) for y in YEARS]),
            CommercialPaper=("USD", [instant(y, 20.0) for y in YEARS]),
            OperatingLeaseLiability=None,
        )
        _, balance, _ = frames(concepts)
        # LongTermDebt already includes the current portion tagged beside it.
        self.assertEqual(latest(balance, "Total Debt"), 370.0)

    def test_specialised_borrowing_concepts_stand_in_for_a_missing_total(self):
        # A REIT: secured debt and a credit line, no long-term-debt concept.
        concepts = company(
            LongTermDebtNoncurrent=None, LongTermDebtCurrent=None, OperatingLeaseLiability=None,
            SecuredDebt=("USD", [instant(y, 900.0) for y in YEARS]),
            LineOfCredit=("USD", [instant(y, 100.0) for y in YEARS]),
        )
        _, balance, _ = frames(concepts)
        self.assertEqual(latest(balance, "Total Debt"), 1000.0)

    def test_specialised_concepts_are_not_added_to_a_total_that_includes_them(self):
        concepts = company(
            OperatingLeaseLiability=None,
            SecuredDebt=("USD", [instant(y, 200.0) for y in YEARS]),
        )
        _, balance, _ = frames(concepts)
        self.assertEqual(latest(balance, "Total Debt"), 350.0)

    def test_no_debt_concepts_is_absent_evidence_not_zero_debt(self):
        concepts = company(LongTermDebtNoncurrent=None, LongTermDebtCurrent=None,
                           OperatingLeaseLiability=None)
        _, balance, _ = frames(concepts)
        self.assertNotIn("Total Debt", balance.index)
        self.assertEqual(latest(balance, "Invested Capital"), 800.0)
        derived = derive_statement_factors(*frames(concepts))
        self.assertIsNone(derived["Statement_Total_Debt"])
        self.assertIsNone(derived["Net_Debt_To_EBITDA"])


class ShareCountTests(unittest.TestCase):
    def split_company(self):
        """10-for-1 split in 2024: only the 2025 and 2026 filings are post-split."""
        weighted = [
            duration(2022, 5.0, filed="2023-02-15"),
            duration(2023, 5.0, filed="2024-02-15"),
            duration(2023, 50.0, filed="2025-02-15"),
            duration(2024, 50.0, filed="2025-02-15"),
            duration(2025, 50.0, filed="2026-02-15"),
        ]
        outstanding = [
            instant(2022, 5.0, filed="2023-02-15"),
            instant(2023, 5.0, filed="2024-02-15"),
            instant(2024, 50.0, filed="2025-02-15"),
            instant(2025, 50.0, filed="2026-02-15"),
        ]
        eps = [
            duration(2022, 20.0, filed="2023-02-15"),
            duration(2023, 20.0, filed="2024-02-15"),
            duration(2023, 2.0, filed="2025-02-15"),
            duration(2024, 2.0, filed="2025-02-15"),
            duration(2025, 2.0, filed="2026-02-15"),
        ]
        return company(
            WeightedAverageNumberOfSharesOutstandingBasic=("shares", weighted),
            CommonStockSharesOutstanding=("shares", outstanding),
            EarningsPerShareDiluted=("USD/shares", eps),
        )

    def test_a_split_is_read_off_the_restated_share_count(self):
        events = edgar._split_events(
            facts(self.split_company())["facts"]["us-gaap"], edgar._USGAAP
        )
        self.assertEqual(events, [("2025-02-15", 10.0)])

    def test_pre_split_filings_are_restated_to_todays_share_basis(self):
        income, balance, cashflow = frames(self.split_company())
        self.assertEqual(balance.loc["Ordinary Shares Number"].tolist(), [50.0] * 4)
        self.assertEqual(income.loc["Diluted EPS"].tolist(), [2.0] * 4)
        derived = derive_statement_factors(income, balance, cashflow)
        # Unadjusted, this read as 115% annual dilution and a 54% EPS collapse.
        self.assertAlmostEqual(derived["Share_Dilution_3Y"], 0.0)
        self.assertAlmostEqual(derived["EPS_CAGR_3Y"], 0.0)

    def test_an_ordinary_buyback_is_not_a_split(self):
        weighted = [duration(2024, 50.0, filed="2025-02-15"), duration(2024, 49.0, filed="2026-02-15")]
        concepts = company(WeightedAverageNumberOfSharesOutstandingBasic=("shares", weighted))
        self.assertEqual(
            edgar._split_events(facts(concepts)["facts"]["us-gaap"], edgar._USGAAP), []
        )

    def test_cover_page_count_fills_in_for_a_missing_balance_sheet_count(self):
        cover = [{"end": f"{y + 1}-02-10", "val": 43.0, "form": "10-K", "filed": f"{y + 1}-02-15"}
                 for y in YEARS]
        concepts = company(CommonStockSharesOutstanding=None,
                           CommonStockSharesIssued=("shares", [instant(y, 70.0) for y in YEARS]))
        _, balance, _ = frames(concepts, dei={"EntityCommonStockSharesOutstanding": ("shares", cover)})
        self.assertEqual(latest(balance, "Ordinary Shares Number"), 43.0)

    def test_issued_shares_count_only_net_of_treasury_stock(self):
        concepts = company(
            CommonStockSharesOutstanding=None,
            CommonStockSharesIssued=("shares", [instant(y, 70.0) for y in YEARS]),
            TreasuryStockCommonShares=("shares", [instant(y, 27.0) for y in YEARS]),
        )
        _, balance, _ = frames(concepts)
        self.assertEqual(latest(balance, "Ordinary Shares Number"), 43.0)

    def test_a_pre_listing_placeholder_count_is_dropped(self):
        outstanding = [instant(2025, 50.0), instant(2024, 50.0), instant(2023, 50.0),
                       instant(2022, 0.0001)]
        concepts = company(CommonStockSharesOutstanding=("shares", outstanding),
                           WeightedAverageNumberOfSharesOutstandingBasic=None)
        derived = derive_statement_factors(*frames(concepts))
        self.assertIsNone(derived["Share_Dilution_3Y"])


class UnusableFilerTests(unittest.TestCase):
    def test_a_filer_reporting_in_another_currency_is_left_to_the_next_source(self):
        concepts = company(Assets=("TWD", [instant(y, 2000.0) for y in YEARS]))
        # A lone dollar convenience translation does not make it a dollar filer.
        payload = facts(concepts)
        payload["facts"]["us-gaap"]["Assets"]["units"]["USD"] = [instant(2024, 60.0)]
        self.assertIsNone(edgar.annual_frames(payload, today=TODAY))

    def test_a_filer_that_stopped_filing_is_not_evidence(self):
        self.assertIsNone(edgar.annual_frames(facts(company()), today=date(2029, 1, 1)))

    def test_no_annual_facts_at_all(self):
        self.assertIsNone(edgar.annual_frames({"facts": {"us-gaap": {}}}, today=TODAY))
        self.assertIsNone(edgar.annual_frames(None, today=TODAY))

    def test_ifrs_filer_in_dollars_is_served(self):
        concepts = {
            "Revenue": ("USD", [duration(y, 1000.0, form="20-F") for y in YEARS]),
            "ProfitLoss": ("USD", [duration(y, 100.0, form="20-F") for y in YEARS]),
            "Assets": ("USD", [instant(y, 2000.0, form="20-F") for y in YEARS]),
            "Equity": ("USD", [instant(y, 800.0, form="20-F") for y in YEARS]),
        }
        income, balance, _ = frames(concepts, taxonomy="ifrs-full")
        self.assertEqual(latest(income, "Total Revenue"), 1000.0)
        self.assertEqual(latest(balance, "Stockholders Equity"), 800.0)


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []
        self.headers_seen = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        self.headers_seen.append(headers)
        answer = self.responses[url]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"},
           "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire"}}
AAPL_URL = edgar.FACTS_URL.format(cik=320193)


class ClientTests(unittest.TestCase):
    def client(self, responses, **kwargs):
        self.session = FakeSession({edgar.TICKERS_URL: FakeResponse(body=TICKERS), **responses})
        self.sleeps = []
        return edgar.EdgarClient(
            "Winnow test@example.com", session=self.session,
            sleep=self.sleeps.append, clock=lambda: 0.0, **kwargs
        )

    def test_a_contact_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, "SEC_USER_AGENT"):
            edgar.EdgarClient("  ")

    def test_every_request_names_the_contact(self):
        client = self.client({AAPL_URL: FakeResponse(body=facts(company()))})
        self.assertIsNotNone(client.annual_frames("AAPL", today=TODAY))
        self.assertEqual(self.session.urls, [edgar.TICKERS_URL, AAPL_URL])
        for headers in self.session.headers_seen:
            self.assertEqual(headers["User-Agent"], "Winnow test@example.com")

    def test_share_class_tickers_are_matched_across_spellings(self):
        client = self.client({})
        for spelling in ("BRK.B", "BRK/B", "brk-b"):
            self.assertEqual(client.cik_for(spelling), 1067983)
        self.assertIsNone(client.cik_for("NOPE"))
        # The directory is fetched once, not per symbol.
        self.assertEqual(self.session.urls, [edgar.TICKERS_URL])

    def test_an_unknown_ticker_or_missing_facts_is_none_not_an_error(self):
        client = self.client({AAPL_URL: FakeResponse(status=404)})
        self.assertIsNone(client.annual_frames("NOPE", today=TODAY))
        self.assertIsNone(client.annual_frames("AAPL", today=TODAY))

    def test_rate_limiting_and_server_errors_are_retried(self):
        client = self.client({AAPL_URL: [
            FakeResponse(status=429), requests.ConnectionError("reset"),
            FakeResponse(body=facts(company())),
        ]})
        self.assertIsNotNone(client.annual_frames("AAPL", today=TODAY))
        self.assertEqual(self.session.urls.count(AAPL_URL), 3)

    def test_a_refusal_is_not_retried(self):
        client = self.client({AAPL_URL: FakeResponse(status=403)})
        with self.assertRaises(requests.HTTPError):
            client.annual_frames("AAPL", today=TODAY)
        self.assertEqual(self.session.urls.count(AAPL_URL), 1)

    def test_requests_are_spaced_to_the_fair_access_limit(self):
        client = self.client({AAPL_URL: FakeResponse(body=facts(company()))})
        client.annual_frames("AAPL", today=TODAY)
        self.assertIn(edgar.MIN_REQUEST_INTERVAL_SECONDS, self.sleeps)

    def test_the_limit_holds_across_threads_sharing_a_client(self):
        client = self.client({AAPL_URL: FakeResponse(body=facts(company()))})
        client.cik_for("AAPL")
        self.sleeps.clear()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: client._get(AAPL_URL), range(8)))
        # The clock is frozen, so every start after the directory request waits.
        self.assertEqual(self.sleeps, [edgar.MIN_REQUEST_INTERVAL_SECONDS] * 8)


class StubEdgar:
    """Serves the symbols it was given; everything else is 'no record'."""

    def __init__(self, served):
        self.served = set(served)
        self.asked = []

    def annual_frames(self, symbol, *, today=None):
        self.asked.append(symbol)
        return frames(company()) if symbol in self.served else None


class StubTicker:
    def __init__(self):
        self.income_stmt, self.balance_sheet, self.cashflow = frames(company())


class CollectorSourceTests(unittest.TestCase):
    def setUp(self):
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        class Config:
            MARKET = "US"
            OUTPUT_DIR = Path(self._temp.name)
            STATEMENT_COLLECTION_ENABLED = True
            STATEMENT_CACHE_MAX_AGE_DAYS = 90
            STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN = 400
            STATEMENT_REQUESTS_PER_MINUTE = 10_000
            STATEMENT_SOURCE = "edgar"
            SEC_USER_AGENT = "Winnow test@example.com"

        self.config = Config

    def collector(self, served=(), yahoo_calls=None, **config):
        for name, value in config.items():
            setattr(self.config, name, value)
        self.stub = StubEdgar(served)

        def factory(symbol):
            if yahoo_calls is not None:
                yahoo_calls.append(symbol)
            return StubTicker()

        return FinancialStatementCollector(
            self.config, ticker_factory=factory, edgar_client=self.stub,
            clock=lambda: datetime(2026, 3, 1),
        )

    def test_edgar_is_asked_first_and_yahoo_only_for_the_remainder(self):
        yahoo = []
        result = self.collector(served={"AAPL", "MSFT"}, yahoo_calls=yahoo).collect(
            ["AAPL", "TSM", "MSFT"]
        ).set_index("Symbol")
        # EDGAR is asked from a thread pool, so the order of arrival is not fixed.
        self.assertEqual(sorted(self.stub.asked), ["AAPL", "MSFT", "TSM"])
        self.assertEqual(yahoo, ["TSM"])
        self.assertEqual(result.loc["AAPL", "Statement_Source"], edgar.SOURCE_LABEL)
        self.assertEqual(result.loc["TSM", "Statement_Source"], "Yahoo Finance annual statements")

    def test_a_yahoo_fallback_row_is_not_asked_for_again(self):
        self.collector(served={"AAPL"}, yahoo_calls=[]).collect(["AAPL", "TSM"])
        yahoo = []
        again = self.collector(served={"AAPL"}, yahoo_calls=yahoo)
        self.assertEqual(len(again.collect(["AAPL", "TSM"])), 2)
        self.assertEqual(self.stub.asked, [])
        self.assertEqual(yahoo, [])

    def test_switching_the_source_refreshes_a_cache_built_under_the_other(self):
        yahoo = []
        self.collector(yahoo_calls=yahoo, STATEMENT_SOURCE="yahoo").collect(["AAPL"])
        self.assertEqual(yahoo, ["AAPL"])
        self.assertEqual(self.stub.asked, [])

        result = self.collector(served={"AAPL"}, STATEMENT_SOURCE="edgar").collect(["AAPL"])
        self.assertEqual(self.stub.asked, ["AAPL"])
        self.assertEqual(result.iloc[0]["Statement_Source"], edgar.SOURCE_LABEL)

    def test_without_a_contact_edgar_is_not_used(self):
        self.config.SEC_USER_AGENT = ""
        with self.assertLogs("screener.statements", level="WARNING") as logs:
            collector = FinancialStatementCollector(
                self.config, ticker_factory=lambda symbol: StubTicker(),
                clock=lambda: datetime(2026, 3, 1),
            )
        self.assertEqual(collector.source, "yahoo")
        self.assertIn("SEC_USER_AGENT", logs.output[0])
        self.assertEqual(len(collector.collect(["AAPL"])), 1)

    def test_nse_default_never_touches_edgar(self):
        del self.config.STATEMENT_SOURCE
        self.config.MARKET = "NSE"
        collector = FinancialStatementCollector(
            self.config, ticker_factory=lambda symbol: StubTicker(),
            clock=lambda: datetime(2026, 3, 1),
        )
        self.assertEqual(collector.source, "yahoo")
        collector.collect(["TCS"])
        self.assertIsNone(collector._edgar)

    def test_fallback_markers_name_the_provider_that_served_the_statements(self):
        frame = pd.DataFrame({
            "Symbol": ["AAPL", "TSM"],
            "Statement_Source": [edgar.SOURCE_LABEL, "Yahoo Finance annual statements"],
            "ROA": [None, None],
            "ROA_Statement": [0.1, 0.2],
        })
        filled = apply_statement_fallbacks(frame)
        self.assertEqual(filled.loc[0, "ROA_Source"], "SEC EDGAR annual statements")
        self.assertEqual(filled.loc[1, "ROA_Source"], "Yahoo Finance annual statements")


if __name__ == "__main__":
    unittest.main()
