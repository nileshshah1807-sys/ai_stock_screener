"""Ind-AS XBRL parsing into a point-in-time annual statement panel.

Reads the documents ``tools.backfill_xbrl`` caches and produces the same kind of
per-period facts ``screener.statements.derive_statement_factors`` works from --
except keyed by filing, so a historical cross-section can be rebuilt from what
was actually published.

**Context selection is the whole correctness problem.** NSE's results XBRL
presents several columns, each a separate context:

* ``OneD``  -- the quarter just ended
* ``FourD`` -- the full financial year
* ``OneI``  -- an instant, used for balance-sheet items at period end

And it mislabels them. ``FourD`` *declares* a three-month period
(``2024-01-01`` to ``2024-03-31``) while carrying the twelve-month figure:
revenue 17,585M against the quarter's 3,683M, a 4.8x ratio, verified on three
independent documents. **Selecting a context by its declared duration therefore
silently returns the quarter instead of the year.** Selection is by context id,
which is uniform across the archive -- ``OneD`` in 150 of 150 sampled documents,
``FourD`` in 149.

Dimensional contexts (segment revenue, expense breakdowns) share those prefixes
-- ``FourOperatingExpenses01D``, ``OneReportableSegmentAssets01I`` -- so ids are
matched exactly, never by prefix, or a segment's revenue would be read as the
company's.

What the archive does and does not contain, measured over 12,052 company-years:

* Income statement: **100%** across FY2017-FY2024.
* Cash flow: **60%**.
* Balance sheet: **0-3% before FY2023, then 100%**. NSE only began embedding it
  in results XBRL from FY2023, and it is absent from the September filings too,
  so it cannot be recovered from this source for earlier years.

That asymmetry decides which factor blocks can be validated historically, and it
is recorded in `COVERAGE_NOTE` so the run report states it rather than implying
whole-model coverage.
"""

from __future__ import annotations

from datetime import date, datetime
import gzip
import logging
from pathlib import Path
import re

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

XBRL_SCHEMA_VERSION = 1

# Context ids, matched exactly. See the module docstring for why duration cannot
# be used and why prefix matching is unsafe.
ANNUAL_CONTEXT = "FourD"
QUARTER_CONTEXT = "OneD"
INSTANT_CONTEXT = "OneI"

COVERAGE_NOTE = (
    "Ind-AS results XBRL carries the income statement for ~100% of company-years "
    "from FY2017, cash flow for ~60%, and the balance sheet only from FY2023 "
    "(0-3% before). Quality inputs requiring assets, equity or invested capital "
    "are therefore unavailable for most of the window."
)

# Tags taken from the annual (``FourD``) context. Coverage measured over 120
# sampled documents; all of these sit at 99% except where noted.
INCOME_TAGS = {
    "revenue": ("RevenueFromOperations",),
    "other_income": ("OtherIncome",),
    "total_income": ("Income",),
    "total_expenses": ("Expenses",),
    "employee_cost": ("EmployeeBenefitExpense",),
    "finance_costs": ("FinanceCosts",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "pbt_before_exceptional": ("ProfitBeforeExceptionalItemsAndTax",),
    "exceptional_items": ("ExceptionalItemsBeforeTax",),
    "pbt": ("ProfitBeforeTax",),
    "tax_expense": ("TaxExpense",),
    "current_tax": ("CurrentTax",),
    "pat": (
        "ProfitLossForPeriodFromContinuingOperations",
        "ProfitLossForPeriod",
    ),
    "eps_basic": (
        "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsLossPerShare",
    ),
    "eps_diluted": (
        "DilutedEarningsLossPerShareFromContinuingOperations",
        "DilutedEarningsLossPerShare",
    ),
    "paid_up_equity": ("PaidUpValueOfEquityShareCapital",),
    "face_value": ("FaceValueOfEquityShareCapital",),
    # ~78%: present when a cash-flow statement is included.
    "cash_from_cashflow": ("CashAndCashEquivalentsCashFlowStatement",),
    "ocf": ("CashFlowsFromUsedInOperatingActivities",),
}

# Balance-sheet tags, taken from the instant (``OneI``) context. Present only
# from FY2023 onward for most filers.
BALANCE_TAGS = {
    "total_assets": ("Assets",),
    "equity": ("Equity",),
    "cash": ("CashAndCashEquivalents",),
    "borrowings_noncurrent": ("BorrowingsNoncurrent",),
    "borrowings_current": ("BorrowingsCurrent",),
    "current_assets": ("CurrentAssets",),
    "current_liabilities": ("CurrentLiabilities",),
}

PANEL_COLUMNS = (
    "Security_ID",
    "ISIN",
    "Symbol",
    "Period_End",
    "Fiscal_Year",
    "Available_From",
    "Filing_Timestamp",
    "Seq_Number",
    "Is_Consolidated",
    "Revenue",
    "Other_Income",
    "Total_Expenses",
    "Finance_Costs",
    "Depreciation",
    "EBIT",
    "EBITDA",
    "PBT",
    "Tax_Expense",
    "PAT",
    "EPS_Basic",
    "EPS_Diluted",
    "Shares_Outstanding",
    "Operating_Margin",
    "Interest_Coverage",
    "Effective_Tax_Rate",
    "OCF",
    "Total_Assets",
    "Equity",
    "Cash",
    "Total_Debt",
    "Has_Balance_Sheet",
    "Has_Cash_Flow",
)


def _fact_pattern(tag):
    """Match one fact regardless of namespace prefix or attribute order.

    The prefix class is ``[\\w.-]+`` rather than ``\\w+`` because NSE's namespace
    prefix is ``in-bse-fin``, and hyphens are not word characters -- a ``\\w+``
    prefix silently matches nothing and every field parses as absent.

    Attribute order is not guaranteed, so ``contextRef`` is captured from the
    whole attribute run rather than assumed to come first.
    """
    return re.compile(
        rf"<(?:[\w.-]+:)?{tag}\s+([^>]*?)>\s*([^<]*?)\s*</(?:[\w.-]+:)?{tag}>",
        re.IGNORECASE,
    )


_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _pattern_for(tag):
    pattern = _PATTERN_CACHE.get(tag)
    if pattern is None:
        pattern = _PATTERN_CACHE[tag] = _fact_pattern(tag)
    return pattern


_CONTEXT_REF_RE = re.compile(r'contextRef\s*=\s*"([^"]+)"', re.IGNORECASE)


def extract_fact(text, tags, context_id):
    """First numeric value of any of ``tags`` in exactly ``context_id``.

    Returns None when absent. A tag present only in a dimensional context (a
    business segment, an expense line) is deliberately not matched, because its
    value is a component and not the company total.
    """
    for tag in tags:
        for match in _pattern_for(tag).finditer(text):
            attributes, value = match.group(1), match.group(2)
            reference = _CONTEXT_REF_RE.search(attributes)
            if reference is None or reference.group(1) != context_id:
                continue
            try:
                return float(str(value).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
    return None


def parse_document(text):
    """Extract the annual and instant facts from one XBRL document."""
    annual = {
        field: extract_fact(text, tags, ANNUAL_CONTEXT)
        for field, tags in INCOME_TAGS.items()
    }
    instant = {
        field: extract_fact(text, tags, INSTANT_CONTEXT)
        for field, tags in BALANCE_TAGS.items()
    }
    # A few filers report the cash-flow line against the instant context.
    if annual.get("ocf") is None:
        annual["ocf"] = extract_fact(text, INCOME_TAGS["ocf"], INSTANT_CONTEXT)
    return {"annual": annual, "instant": instant}


def _safe_divide(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    try:
        value = float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None if not np.isfinite(value) else value


def derive_record(parsed):
    """Turn raw facts into the derived fields the factor blocks consume."""
    annual = parsed["annual"]
    instant = parsed["instant"]

    revenue = annual.get("revenue")
    finance_costs = annual.get("finance_costs")
    depreciation = annual.get("depreciation")
    pbt = annual.get("pbt")
    pbt_before = annual.get("pbt_before_exceptional")

    # EBIT from the operating line where available. Exceptional items are
    # excluded deliberately: a one-off gain flowing into EBIT would make the
    # margin-stability and interest-coverage inputs measure the exception rather
    # than the business.
    operating_profit = pbt_before if pbt_before is not None else pbt
    ebit = (
        operating_profit + finance_costs
        if operating_profit is not None and finance_costs is not None
        else operating_profit
    )
    ebitda = (
        ebit + depreciation if ebit is not None and depreciation is not None else None
    )

    paid_up = annual.get("paid_up_equity")
    face_value = annual.get("face_value")
    shares = _safe_divide(paid_up, face_value)

    borrowings = [
        instant.get("borrowings_noncurrent"),
        instant.get("borrowings_current"),
    ]
    observed_borrowings = [value for value in borrowings if value is not None]
    total_debt = sum(observed_borrowings) if observed_borrowings else None

    has_balance_sheet = instant.get("total_assets") is not None
    has_cash_flow = annual.get("ocf") is not None

    return {
        "Revenue": revenue,
        "Other_Income": annual.get("other_income"),
        "Total_Expenses": annual.get("total_expenses"),
        "Finance_Costs": finance_costs,
        "Depreciation": depreciation,
        "EBIT": ebit,
        "EBITDA": ebitda,
        "PBT": pbt,
        "Tax_Expense": annual.get("tax_expense"),
        "PAT": annual.get("pat"),
        "EPS_Basic": annual.get("eps_basic"),
        "EPS_Diluted": annual.get("eps_diluted"),
        "Shares_Outstanding": shares,
        "Operating_Margin": _safe_divide(ebit, revenue),
        "Interest_Coverage": _safe_divide(ebit, finance_costs),
        "Effective_Tax_Rate": _safe_divide(annual.get("tax_expense"), pbt),
        "OCF": annual.get("ocf"),
        "Total_Assets": instant.get("total_assets"),
        "Equity": instant.get("equity"),
        "Cash": instant.get("cash"),
        "Total_Debt": total_debt,
        "Has_Balance_Sheet": has_balance_sheet,
        "Has_Cash_Flow": has_cash_flow,
    }


def read_document(path):
    """Read a cached gzipped document, or None when unreadable."""
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except Exception as exc:
        logger.debug("Unreadable XBRL document %s: %s", path, exc)
        return None


def parse_filing(path, metadata):
    """Parse one cached document into a panel row, or None."""
    text = read_document(path)
    if not text:
        return None
    record = derive_record(parse_document(text))
    if record["Revenue"] is None and record["PAT"] is None:
        # Neither top nor bottom line: nothing downstream can use this row, and
        # keeping it would inflate apparent coverage.
        return None

    period_end = str(metadata.get("Period_End") or "")[:10]
    record.update(
        {
            "Security_ID": metadata.get("Security_ID"),
            "ISIN": metadata.get("ISIN"),
            "Symbol": metadata.get("Symbol"),
            "Period_End": period_end,
            "Fiscal_Year": _fiscal_year(period_end),
            "Available_From": metadata.get("Available_From"),
            "Filing_Timestamp": metadata.get("Filing_Timestamp"),
            "Seq_Number": metadata.get("Seq_Number"),
            "Is_Consolidated": metadata.get("Is_Consolidated"),
        }
    )
    return record


def _fiscal_year(period_end):
    """Indian fiscal year label: FY ending 31 March 2024 is 2024."""
    try:
        parsed = date.fromisoformat(str(period_end)[:10])
    except (TypeError, ValueError):
        return None
    return parsed.year if parsed.month >= 4 else parsed.year


def build_panel(filings, document_path_fn, *, workers=8, on_progress=None):
    """Parse every cached filing into one long annual panel.

    ``filings`` is the filing-metadata frame; ``document_path_fn`` maps a row to
    its cached document path. Parsing is IO-bound, so it is threaded.
    """
    from concurrent.futures import ThreadPoolExecutor

    records = filings.to_dict("records")
    paths = [
        document_path_fn(record.get("Seq_Number"), record.get("Period_End"))
        for record in records
    ]
    jobs = [
        (path, record)
        for path, record in zip(paths, records)
        if Path(path).exists()
    ]
    logger.info(
        "Parsing %d cached documents of %d filings", len(jobs), len(records)
    )

    rows = []
    with ThreadPoolExecutor(max_workers=int(workers)) as pool:
        for index, row in enumerate(
            pool.map(lambda job: parse_filing(job[0], job[1]), jobs), start=1
        ):
            if row is not None:
                rows.append(row)
            if on_progress is not None and index % 2000 == 0:
                on_progress(index, len(jobs), len(rows))

    if not rows:
        return pd.DataFrame(columns=list(PANEL_COLUMNS))
    frame = pd.DataFrame(rows)
    ordered = [column for column in PANEL_COLUMNS if column in frame.columns]
    remaining = [column for column in frame.columns if column not in ordered]
    return frame.loc[:, ordered + remaining]


def deduplicate_panel(panel):
    """One row per security and fiscal year, preferring the richest filing.

    A company files the same year more than once -- standalone and consolidated,
    originals and revisions. Consolidated is preferred where present because it
    is what the factor model treats as the company, then a row carrying a balance
    sheet, then the latest filing.
    """
    if panel is None or len(panel) == 0:
        return panel
    working = panel.copy()
    working["_consolidated"] = (
        working.get("Is_Consolidated", pd.Series(False, index=working.index))
        .fillna(False)
        .astype(bool)
        .astype(int)
    )
    working["_balance"] = (
        working.get("Has_Balance_Sheet", pd.Series(False, index=working.index))
        .fillna(False)
        .astype(bool)
        .astype(int)
    )
    working["_available"] = pd.to_datetime(
        working.get("Available_From"), errors="coerce"
    )
    working = working.sort_values(
        ["Security_ID", "Fiscal_Year", "_consolidated", "_balance", "_available"],
        ascending=[True, True, False, False, False],
    )
    deduped = working.drop_duplicates(
        subset=["Security_ID", "Fiscal_Year"], keep="first"
    )
    return deduped.drop(
        columns=["_consolidated", "_balance", "_available"]
    ).reset_index(drop=True)


def coverage_summary(panel):
    """Field coverage, so the run report can state what was actually available."""
    if panel is None or len(panel) == 0:
        return {"company_years": 0}
    total = len(panel)
    summary = {
        "company_years": int(total),
        "securities": int(panel["Security_ID"].nunique()),
        "fiscal_years": sorted(
            int(year) for year in panel["Fiscal_Year"].dropna().unique()
        ),
        "note": COVERAGE_NOTE,
    }
    for column in (
        "Revenue",
        "PAT",
        "EPS_Basic",
        "EBIT",
        "Shares_Outstanding",
        "OCF",
        "Total_Assets",
        "Equity",
        "Total_Debt",
    ):
        if column in panel:
            summary[f"pct_{column.lower()}"] = round(
                100.0 * float(panel[column].notna().mean()), 2
            )
    return summary
