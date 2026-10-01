"""SEC EDGAR as the annual-statement source for US filers.

Yahoo's statement endpoints are the slowest and least dependable part of a US
run: one request per symbol at 40 a minute is ninety minutes for the universe,
behind a session token Yahoo rejects for the first minutes of every cold run.
EDGAR's ``companyfacts`` API is the filing itself -- the XBRL facts each
registrant submits with its 10-K -- served by the regulator, free, with a
documented fair-access limit of ten requests a second.

This module turns one company's facts into the three frames
``screener.statements.derive_statement_factors`` already consumes: rows carry
Yahoo's labels, columns are fiscal-year ends, newest first. Every factor is then
derived by the same arithmetic whichever source supplied the numbers, so the
scoring layer cannot tell the two apart and needs no market branch.

What EDGAR cannot serve returns ``None`` and the collector falls back to Yahoo:

* filers that report in a currency other than the US dollar (most 20-F and
  40-F registrants) -- the absolute outputs are compared with dollar prices;
* registrants with no annual XBRL facts, or none in the last two years.

Like the Yahoo path, the frames are the statements as published *today*,
restatements included. They are not a point-in-time record.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta

import pandas as pd
import requests

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SOURCE_LABEL = "SEC EDGAR annual filings (XBRL)"

# SEC's fair-access policy allows ten requests a second per client.
MIN_REQUEST_INTERVAL_SECONDS = 0.125
REQUEST_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A"})
# A fiscal year is 52 or 53 weeks; anything else is a quarter, a year-to-date
# figure or a transition period.
MIN_ANNUAL_DAYS, MAX_ANNUAL_DAYS = 340, 380
# Yahoo serves four fiscal years. The dispersion and trend factors are computed
# over whatever history they are handed, so the window is matched rather than
# letting a US company be judged on fifteen years and an NSE one on four.
MAX_FISCAL_YEARS = 4
# A registrant whose newest annual facts are older than this has stopped
# filing; its last statements are not evidence about the company today.
MAX_STATEMENT_AGE_DAYS = 800
# The cover-page share count is dated a few weeks after the fiscal year end.
COVER_PAGE_WINDOW_DAYS = 120
# Used for ROIC when a year's effective rate is not meaningful (a loss, a tax
# credit). Yahoo substitutes the same federal statutory rate.
US_STATUTORY_TAX_RATE = 0.21
# A share count this many times away from the newest year's is a pre-listing
# placeholder or an unadjusted split, not a measurement.
MAX_SHARE_COUNT_RATIO = 50
# A restated share count this far from the original is a split, not a revision.
SPLIT_RATIO_THRESHOLD = 1.25

# Concept alternatives, most specific first. They are coalesced per fiscal year,
# not per company: registrants change tags over time (revenue moved to the
# contract-with-customer concepts in 2018), so one company's four years can
# sit under two concepts.
_USGAAP = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "RevenuesNetOfInterestExpense",
    ),
    "net_interest_income": ("InterestIncomeExpenseNet",),
    "noninterest_income": ("NoninterestIncome",),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "income_tax": ("IncomeTaxExpenseBenefit",),
    "net_income": (
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ),
    "interest_expense": (
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
    ),
    "depreciation_amortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "eps_basic": ("EarningsPerShareBasic",),
    "total_assets": ("Assets",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "debt_combined": ("DebtLongtermAndShorttermCombinedAmount",),
    # The note-payable concepts stand in only where a filer tags no long-term
    # debt total at all (insurers, convertible-note issuers).
    "long_term_debt_total": (
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "NotesPayable",
        "SeniorNotes",
        "ConvertibleNotesPayable",
    ),
    "long_term_debt_noncurrent": (
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermNotesPayable",
        "ConvertibleNotesPayableNoncurrent",
        "ConvertibleDebtNoncurrent",
        "SeniorLongTermNotes",
    ),
    "long_term_debt_current": (
        "LongTermDebtCurrent",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
    ),
    "debt_current": ("DebtCurrent",),
    "short_term_borrowings": (
        "ShortTermBorrowings",
        "CommercialPaper",
        "OtherShortTermBorrowings",
    ),
    "operating_lease": ("OperatingLeaseLiability",),
    "operating_lease_noncurrent": ("OperatingLeaseLiabilityNoncurrent",),
    "operating_lease_current": ("OperatingLeaseLiabilityCurrent",),
    "finance_lease": ("FinanceLeaseLiability",),
    "finance_lease_noncurrent": ("FinanceLeaseLiabilityNoncurrent",),
    "finance_lease_current": ("FinanceLeaseLiabilityCurrent",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "Cash",
    ),
    "shares": ("CommonStockSharesOutstanding",),
    "shares_issued": ("CommonStockSharesIssued",),
    "treasury_shares": ("TreasuryStockCommonShares", "TreasuryStockShares"),
    "shares_weighted": (
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "deposits": ("Deposits",),
    "ocf": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
}

_IFRS = {
    "revenue": ("Revenue", "RevenueFromContractsWithCustomers"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("ProfitLossFromOperatingActivities",),
    "pretax_income": ("ProfitLossBeforeTax",),
    "income_tax": ("IncomeTaxExpenseContinuingOperations",),
    "net_income": ("ProfitLossAttributableToOwnersOfParent", "ProfitLoss"),
    "interest_expense": ("InterestExpense", "FinanceCosts"),
    "depreciation_amortization": (
        "DepreciationAndAmortisationExpense",
        "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
    ),
    "eps_diluted": ("DilutedEarningsLossPerShare",),
    "eps_basic": ("BasicEarningsLossPerShare",),
    "total_assets": ("Assets",),
    "equity": ("EquityAttributableToOwnersOfParent", "Equity"),
    "long_term_debt_total": ("Borrowings",),
    "long_term_debt_noncurrent": (
        "NoncurrentPortionOfNoncurrentBorrowings",
        "LongtermBorrowings",
    ),
    "long_term_debt_current": (
        "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
        "ShorttermBorrowings",
    ),
    "operating_lease": ("LeaseLiabilities",),
    "operating_lease_noncurrent": ("NoncurrentLeaseLiabilities",),
    "operating_lease_current": ("CurrentLeaseLiabilities",),
    "cash": ("CashAndCashEquivalents",),
    "shares": ("NumberOfSharesOutstanding",),
    "shares_issued": ("NumberOfSharesIssued",),
    "treasury_shares": ("TreasuryShares",),
    "shares_weighted": ("WeightedAverageShares", "AdjustedWeightedAverageShares"),
    "current_assets": ("CurrentAssets",),
    "current_liabilities": ("CurrentLiabilities",),
    "deposits": ("DepositsFromCustomers",),
    "ocf": ("CashFlowsFromUsedInOperatingActivities",),
    "capex": ("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
}

_TAXONOMIES = (("us-gaap", _USGAAP), ("ifrs-full", _IFRS))
_INSTANT_KEYS = frozenset({
    "total_assets", "equity", "debt_combined", "long_term_debt_total",
    "long_term_debt_noncurrent", "long_term_debt_current", "debt_current",
    "short_term_borrowings",
    "operating_lease", "operating_lease_noncurrent", "operating_lease_current",
    "finance_lease", "finance_lease_noncurrent", "finance_lease_current",
    "cash", "shares", "shares_issued", "treasury_shares", "current_assets",
    "current_liabilities", "deposits",
})
# Insurers and banks tag their fee income under the contract-revenue concept
# and their whole top line under ``Revenues``; first-available would report
# MetLife's revenue as 3% of what it is. The total is the largest alternative.
_LARGEST_WINS = frozenset({"revenue"})
_UNITS = {
    "eps_diluted": "USD/shares",
    "eps_basic": "USD/shares",
    "shares": "shares",
    "shares_issued": "shares",
    "treasury_shares": "shares",
    "shares_weighted": "shares",
}


def normalise_ticker(symbol) -> str:
    """EDGAR writes share classes with a hyphen: BRK.B and BRK/B are BRK-B."""
    return re.sub(r"[./ ]", "-", str(symbol).strip().upper())


def _parse(day):
    return date.fromisoformat(day)


def _is_annual(entry, *, instant):
    if entry.get("form") not in ANNUAL_FORMS or "val" not in entry or "end" not in entry:
        return False
    if instant:
        return "start" not in entry
    if "start" not in entry:
        return False
    days = (_parse(entry["end"]) - _parse(entry["start"])).days
    return MIN_ANNUAL_DAYS <= days <= MAX_ANNUAL_DAYS


def _annual_facts(taxonomy_facts, concept, unit, *, instant):
    """``{period end: (filed, value)}`` for one concept from annual filings.

    A fiscal year's figure is repeated in later filings as a comparative, and
    restated when it changes; the most recently filed value for a period wins,
    which is what a reader of today's statements sees.
    """
    entries = taxonomy_facts.get(concept, {}).get("units", {}).get(unit)
    best = {}
    for entry in entries or ():
        if not _is_annual(entry, instant=instant):
            continue
        filed = entry.get("filed", "")
        held = best.get(entry["end"])
        if held is None or filed >= held[0]:
            best[entry["end"]] = (filed, float(entry["val"]))
    return best


def _split_events(taxonomy_facts, concepts):
    """``[(filed, ratio)]``: stock splits, read off restated share counts.

    A filing never revises an older one. After a 10-for-1 split the next 10-K
    restates the comparative years it shows, but a year that has dropped off
    the page -- and every balance-sheet share count more than a year old --
    survives only in pre-split filings. Mixing the two reads as a tenfold
    dilution and a 90% collapse in earnings per share.

    The split is visible in the facts themselves: the same fiscal year's
    weighted-average share count, filed once before the split and once after,
    differs by the split ratio. Each such jump is dated by the first filing
    that carries the restated figure.
    """
    ratios = {}
    for concept in concepts.get("shares_weighted", ()):
        by_period = {}
        entries = taxonomy_facts.get(concept, {}).get("units", {}).get("shares")
        for entry in entries or ():
            if _is_annual(entry, instant=False) and entry["val"]:
                by_period.setdefault(entry["end"], {})[entry.get("filed", "")] = float(entry["val"])
        for filings in by_period.values():
            ordered = sorted(filings.items())
            for (_, before), (filed, after) in zip(ordered, ordered[1:], strict=False):
                ratio = after / before
                if ratio >= SPLIT_RATIO_THRESHOLD or ratio <= 1.0 / SPLIT_RATIO_THRESHOLD:
                    ratios.setdefault(filed, []).append(ratio)
        if ratios:
            break
    return sorted((filed, sorted(found)[len(found) // 2]) for filed, found in ratios.items())


def _split_factor(filed, events):
    """What a share count filed on ``filed`` must be multiplied by today."""
    factor = 1.0
    for event_filed, ratio in events:
        if filed < event_filed:
            factor *= ratio
    return factor


def _series(taxonomy_facts, concepts, key, events=()):
    """Coalesce a key's concept alternatives into one ``{end: value}`` map."""
    unit = _UNITS.get(key, "USD")
    merged = {}
    for concept in concepts.get(key, ()):
        for end, (filed, value) in _annual_facts(
            taxonomy_facts, concept, unit, instant=key in _INSTANT_KEYS
        ).items():
            if key in _LARGEST_WINS:
                merged[end] = max(value, merged.get(end, value))
                continue
            if end in merged:
                continue
            if unit == "shares":
                value *= _split_factor(filed, events)
            elif unit == "USD/shares":
                value /= _split_factor(filed, events)
            merged[end] = value
    return merged


def _reports_in_dollars(taxonomy_facts, concepts):
    """False when the registrant's statements are in another currency.

    Foreign filers often tag a few dollar "convenience translation" figures
    beside the real ones. They cover a single year and would be read here as a
    one-year history in the wrong unit, so the currency with the most annual
    facts for total assets is taken as the reporting currency.
    """
    for key in ("total_assets", "net_income", "revenue"):
        for concept in concepts.get(key, ()):
            units = taxonomy_facts.get(concept, {}).get("units", {})
            counts = {
                unit: sum(1 for entry in entries if entry.get("form") in ANNUAL_FORMS)
                for unit, entries in units.items()
            }
            if any(counts.values()):
                return max(counts, key=counts.get) == "USD"
    return False


def _combine(ends, *parts, required=1):
    """Per-period sum of ``parts``; a period needs ``required`` of them present."""
    out = {}
    for end in ends:
        present = [part[end] for part in parts if end in part]
        if len(present) >= required:
            out[end] = sum(present)
    return out


# Yahoo's ``Total Debt`` carries operating-lease liabilities as capital-lease
# obligations but leaves finance leases out; measured against it on a sample of
# filers, this is the definition that tracks it most closely.
_LEASES_COUNTED_AS_DEBT = (
    ("operating_lease", ("operating_lease_noncurrent", "operating_lease_current")),
)


def _borrowings(series, ends):
    """Interest-bearing borrowings per period, current portion counted once.

    A period with none of the borrowing concepts is left absent rather than
    reported as zero: a missing tag is not evidence of a debt-free balance sheet.
    """
    out = {}
    for end in ends:
        if end in series["debt_combined"]:
            out[end] = series["debt_combined"][end]
            continue
        short_term = series["short_term_borrowings"].get(end)
        if end in series["long_term_debt_total"]:
            # Already includes the current maturities of long-term debt.
            out[end] = series["long_term_debt_total"][end] + (short_term or 0.0)
            continue
        noncurrent = series["long_term_debt_noncurrent"].get(end)
        if end in series["debt_current"]:
            # Current maturities and short-term borrowings in one figure.
            current = series["debt_current"][end]
        else:
            parts = [series["long_term_debt_current"].get(end), short_term]
            current = sum(p for p in parts if p is not None) if any(
                p is not None for p in parts
            ) else None
        if noncurrent is None and current is None:
            continue
        out[end] = (noncurrent or 0.0) + (current or 0.0)
    return out


def _total_debt(series, ends, borrowings):
    """Borrowings plus the lease liabilities Yahoo's ``Total Debt`` includes."""
    out = {}
    for end in ends:
        leases = 0.0
        for whole, split in _LEASES_COUNTED_AS_DEBT:
            if whole and end in series[whole]:
                leases += series[whole][end]
            else:
                leases += sum(series[key].get(end, 0.0) for key in split)
        if end in borrowings:
            out[end] = borrowings[end] + leases
        elif leases:
            out[end] = leases
    return out


def _cover_page_shares(facts, ends, events):
    """Cover-page share count, assigned to the fiscal year it follows."""
    entries = (
        facts.get("dei", {})
        .get("EntityCommonStockSharesOutstanding", {})
        .get("units", {})
        .get("shares", [])
    )
    out = {}
    for entry in entries:
        if entry.get("form") not in ANNUAL_FORMS or "val" not in entry:
            continue
        stamped = _parse(entry["end"])
        for end in ends:
            gap = (stamped - _parse(end)).days
            if 0 <= gap <= COVER_PAGE_WINDOW_DAYS:
                out[end] = float(entry["val"]) * _split_factor(
                    entry.get("filed", ""), events
                )
    return out


def _frame(rows, ends):
    """Yahoo-shaped statement frame: labels down, fiscal-year ends across."""
    columns = [pd.Timestamp(end) for end in ends]
    data = {
        label: [values.get(end) for end in ends]
        for label, values in rows.items()
        if values
    }
    return pd.DataFrame.from_dict(data, orient="index", columns=columns, dtype=float)


def annual_frames(facts, *, today=None):
    """``(income, balance, cashflow)`` frames from a companyfacts payload.

    Returns ``None`` when the registrant has no usable dollar-denominated annual
    record, which is the caller's cue to try the next source.
    """
    all_facts = (facts or {}).get("facts") or {}
    today = today or date.today()
    for taxonomy, concepts in _TAXONOMIES:
        taxonomy_facts = all_facts.get(taxonomy)
        if not taxonomy_facts:
            continue
        if not _reports_in_dollars(taxonomy_facts, concepts):
            return None
        events = _split_events(taxonomy_facts, concepts)
        series = {
            key: _series(taxonomy_facts, concepts, key, events) for key in _USGAAP
        }
        fiscal_ends = sorted(
            set(series["net_income"]) | set(series["revenue"]) | set(series["ocf"]),
            reverse=True,
        )[:MAX_FISCAL_YEARS]
        if not fiscal_ends:
            continue
        if _parse(fiscal_ends[0]) < today - timedelta(days=MAX_STATEMENT_AGE_DAYS):
            return None
        return _build(all_facts, series, fiscal_ends, events)
    return None


def _build(all_facts, series, ends, events):
    revenue = dict(series["revenue"])
    for end, value in _combine(
        ends, series["net_interest_income"], series["noninterest_income"], required=2
    ).items():
        # A bank that tags no single revenue concept still reports its two halves.
        revenue[end] = max(value, revenue.get(end, value))

    # Reported gross profit only. Revenue less a cost-of-revenue concept was
    # tried and overstated it three- to five-fold for filers whose cost line
    # covers one segment (Caterpillar, UnitedHealth); absent is better than that.
    gross_profit = series["gross_profit"]

    # Yahoo's EBIT is pre-tax income with interest expense added back. Banks are
    # left without one, as on Yahoo: interest is their cost of goods, and the
    # financial quality template is not scored on EBIT.
    is_bank = bool(series["deposits"])
    ebit, ebitda, tax_rate = {}, {}, {}
    for end in ends:
        pretax = series["pretax_income"].get(end)
        if pretax is None:
            continue
        tax = series["income_tax"].get(end)
        if tax is not None and pretax > 0 and 0.0 <= tax / pretax < 1.0:
            tax_rate[end] = tax / pretax
        else:
            tax_rate[end] = US_STATUTORY_TAX_RATE
        if is_bank:
            continue
        ebit[end] = pretax + series["interest_expense"].get(end, 0.0)
        if end in series["depreciation_amortization"]:
            ebitda[end] = ebit[end] + series["depreciation_amortization"][end]

    borrowings = _borrowings(series, ends)
    total_debt = _total_debt(series, ends, borrowings)
    equity = series["equity"]
    # Invested capital is equity plus borrowings, without the lease liabilities
    # that total debt carries -- Yahoo's definition, and the one ROIC was
    # validated on.
    invested_capital = {
        end: equity[end] + borrowings.get(end, 0.0) for end in ends if end in equity
    }

    # Issued shares include treasury stock, which Coca-Cola holds 2.7 billion
    # of; they count only once the treasury holding is known and taken off.
    issued_less_treasury = {
        end: series["shares_issued"][end] - series["treasury_shares"][end]
        for end in ends
        if end in series["shares_issued"] and end in series["treasury_shares"]
    }
    shares = dict(series["shares"])
    for fallback in (
        _cover_page_shares(all_facts, ends, events),
        issued_less_treasury,
        series["shares_weighted"],
    ):
        for end, value in fallback.items():
            shares.setdefault(end, value)
    # A company carved out of a parent reports a nominal share count (often
    # 100 or 1,000) for the years before its listing. That is not a base to
    # measure dilution from.
    newest = shares.get(ends[0])
    if newest:
        shares = {
            end: value
            for end, value in shares.items()
            if value > 0 and 1 / MAX_SHARE_COUNT_RATIO <= value / newest <= MAX_SHARE_COUNT_RATIO
        }

    # XBRL reports a purchase as a positive outflow; Yahoo signs it negative.
    capex = {end: -abs(value) for end, value in series["capex"].items()}
    ocf = series["ocf"]
    fcf = {end: ocf[end] + capex[end] for end in ends if end in ocf and end in capex}

    income = _frame(
        {
            "Total Revenue": revenue,
            "Gross Profit": {} if is_bank else gross_profit,
            "EBIT": ebit,
            "Operating Income": {} if is_bank else series["operating_income"],
            "EBITDA": ebitda,
            "Net Income": series["net_income"],
            "Interest Expense": series["interest_expense"],
            "Tax Rate For Calcs": tax_rate,
            "Diluted EPS": series["eps_diluted"],
            "Basic EPS": series["eps_basic"],
        },
        ends,
    )
    balance = _frame(
        {
            "Total Assets": series["total_assets"],
            "Invested Capital": invested_capital,
            "Stockholders Equity": equity,
            "Total Debt": total_debt,
            "Cash And Cash Equivalents": series["cash"],
            "Ordinary Shares Number": shares,
            "Current Assets": series["current_assets"],
            "Current Liabilities": series["current_liabilities"],
        },
        ends,
    )
    cashflow = _frame(
        {
            "Operating Cash Flow": ocf,
            "Free Cash Flow": fcf,
            "Capital Expenditure": capex,
        },
        ends,
    )
    if income.empty and balance.empty:
        return None
    return income, balance, cashflow


class EdgarClient:
    """Throttled reader for the two EDGAR endpoints the screener needs."""

    def __init__(self, user_agent, *, session=None, timeout_seconds=30,
                 sleep=time.sleep, clock=time.monotonic):
        if not str(user_agent or "").strip():
            raise ValueError(
                "SEC_USER_AGENT is required for EDGAR: SEC's fair-access policy "
                "rejects requests that do not name a contact"
            )
        self.session = session or requests.Session()
        self.headers = {
            "User-Agent": str(user_agent).strip(),
            "Accept-Encoding": "gzip, deflate",
        }
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._clock = clock
        self._last_request = None
        self._ciks = None

    def _get(self, url):
        """JSON body, or ``None`` for a 404. Transient failures are retried."""
        for attempt in range(REQUEST_RETRIES + 1):
            if self._last_request is not None:
                wait = MIN_REQUEST_INTERVAL_SECONDS - (self._clock() - self._last_request)
                if wait > 0:
                    self._sleep(wait)
            self._last_request = self._clock()
            try:
                response = self.session.get(
                    url, headers=self.headers, timeout=self.timeout_seconds
                )
                if response.status_code == 404:
                    return None
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(
                        f"{response.status_code} from {url}", response=response
                    )
                response.raise_for_status()
                return response.json()
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                transient = status is None or status == 429 or status >= 500
                if not transient or attempt == REQUEST_RETRIES:
                    raise
                self._sleep(RETRY_BACKOFF_SECONDS * 2**attempt)
        raise AssertionError("unreachable")

    def cik_for(self, symbol):
        """The registrant's CIK, or ``None`` when SEC lists no such ticker."""
        if self._ciks is None:
            listing = self._get(TICKERS_URL) or {}
            self._ciks = {
                normalise_ticker(row["ticker"]): int(row["cik_str"])
                for row in listing.values()
            }
            logger.info("EDGAR ticker directory loaded: %d tickers", len(self._ciks))
        return self._ciks.get(normalise_ticker(symbol))

    def annual_frames(self, symbol, *, today=None):
        """Statement frames for ``symbol``, or ``None`` when EDGAR has none."""
        cik = self.cik_for(symbol)
        if cik is None:
            return None
        facts = self._get(FACTS_URL.format(cik=cik))
        return annual_frames(facts, today=today) if facts else None
