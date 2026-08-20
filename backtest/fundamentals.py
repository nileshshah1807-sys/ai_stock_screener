"""Point-in-time fundamental factor inputs from the annual XBRL panel.

Answers one question, and refuses to answer it loosely: *what did this company's
financial history look like to someone deciding on date t?* Only filings whose
``Available_From`` is on or before *t* are visible, so a statement published in
May cannot inform an April decision, and a restatement cannot rewrite a decision
that preceded it.

The arithmetic is **not** reimplemented here.
:func:`screener.statements.derive_statement_factors` is pure, and this module
reshapes the panel into the frames it already expects -- rows labelled the way
the production collector labels them, columns the period ends, newest first.
Calling it unchanged is what guarantees that ``Revenue_CAGR_3Y`` in a backtest
means exactly what it means in production. A parallel implementation would drift,
and the drift would be invisible inside a factor score.

Two derivations exist here because the panel carries different raw material than
Yahoo does:

* **Invested capital** is not a filed line item; it is equity plus total debt,
  the standard definition, so ROIC becomes computable wherever the balance sheet
  exists (FY2023 onward).
* **Free cash flow** is not derivable at all -- the filings carry operating cash
  flow but no capital expenditure -- so it is left absent rather than
  approximated by OCF, which would silently flatter every cash-flow ratio.
"""

from __future__ import annotations

from datetime import date, datetime
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Panel field -> the row label the production collector reads. Keeping the
# production labels means derive_statement_factors needs no modification.
INCOME_ROW_MAP = {
    "Revenue": "Total Revenue",
    "EBIT": "EBIT",
    "EBITDA": "EBITDA",
    "PAT": "Net Income",
    "Finance_Costs": "Interest Expense",
    "Effective_Tax_Rate": "Tax Rate For Calcs",
    "EPS_Diluted": "Diluted EPS",
    "EPS_Basic": "Basic EPS",
}

BALANCE_ROW_MAP = {
    "Total_Assets": "Total Assets",
    "Invested_Capital": "Invested Capital",
    "Equity": "Stockholders Equity",
    "Total_Debt": "Total Debt",
    "Cash": "Cash And Cash Equivalents",
    "Shares_Outstanding": "Ordinary Shares Number",
}

CASHFLOW_ROW_MAP = {
    "OCF": "Operating Cash Flow",
}

# Years of history to hand the derivation. Revenue_CAGR_3Y needs four annual
# periods; five gives the stability measures a little more to work with without
# reaching so far back that a company's business has changed underneath it.
DEFAULT_HISTORY_YEARS = 5


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _age_days(as_of, available_from):
    """Days between the decision date and the evidence behind it."""
    try:
        return (_as_date(as_of) - _as_date(available_from)).days
    except Exception:
        return None


class FundamentalPanel:
    """Point-in-time access to the annual statement panel."""

    def __init__(self, frame):
        self.frame = frame.copy() if frame is not None else pd.DataFrame()
        self._by_security: dict[str, list] = {}
        self._factor_cache: dict[tuple, dict] = {}
        if self.frame.empty:
            return

        working = self.frame
        working["_available"] = pd.to_datetime(
            working.get("Available_From"), errors="coerce"
        )
        # A row with no availability date cannot be placed in time. Dropping it
        # is the only safe choice: keeping it would mean guessing when it became
        # knowable, which is precisely the bias this module exists to prevent.
        unavailable = working["_available"].isna().sum()
        if unavailable:
            logger.warning(
                "Dropping %d panel rows with no Available_From; they cannot be "
                "placed in time",
                int(unavailable),
            )
        working = working[working["_available"].notna()]

        working = working.sort_values(["Security_ID", "Fiscal_Year"], ascending=[True, False])
        for security_id, group in working.groupby("Security_ID", sort=False):
            self._by_security[str(security_id)] = group.to_dict("records")

    @classmethod
    def load(cls, path):
        from pathlib import Path

        path = Path(path)
        if not path.exists():
            return cls(pd.DataFrame())
        return cls(pd.read_csv(path, dtype={"ISIN": str, "Seq_Number": str}))

    def __len__(self):
        return len(self._by_security)

    def securities(self):
        return list(self._by_security)

    def history_as_of(self, security_id, as_of, *, years=DEFAULT_HISTORY_YEARS):
        """Annual records visible on ``as_of``, newest fiscal year first.

        One row per fiscal year. Where a year appears more than once -- an
        original and a later restatement -- the newest version that was *already
        published* on ``as_of`` wins, so a June-2023 decision sees the original
        figure even though a 2024 revision exists in the panel.
        """
        records = self._by_security.get(str(security_id))
        if not records:
            return []
        cutoff = pd.Timestamp(_as_date(as_of))

        visible = [r for r in records if r["_available"] <= cutoff]
        if not visible:
            return []

        best_by_year: dict = {}
        for record in visible:
            year = record.get("Fiscal_Year")
            if year is None or (isinstance(year, float) and np.isnan(year)):
                continue
            current = best_by_year.get(year)
            if current is None or record["_available"] > current["_available"]:
                best_by_year[year] = record

        ordered = sorted(
            best_by_year.values(), key=lambda r: r["Fiscal_Year"], reverse=True
        )
        return ordered[: int(years)]

    def statement_frames(self, security_id, as_of, *, years=DEFAULT_HISTORY_YEARS):
        """Income, balance and cash-flow frames shaped for the production code."""
        history = self.history_as_of(security_id, as_of, years=years)
        if not history:
            return None, None, None

        periods = [str(record.get("Period_End") or "")[:10] for record in history]

        def build(mapping):
            rows = {}
            for field, label in mapping.items():
                values = [record.get(field) for record in history]
                numeric = pd.to_numeric(pd.Series(values), errors="coerce")
                if numeric.notna().any():
                    rows[label] = numeric.tolist()
            if not rows:
                return None
            return pd.DataFrame(rows, index=periods).T

        income = build(INCOME_ROW_MAP)
        cashflow = build(CASHFLOW_ROW_MAP)

        # Invested capital is not a filed line. Equity plus total debt is the
        # standard construction and makes ROIC computable wherever the balance
        # sheet exists at all.
        enriched = []
        for record in history:
            row = dict(record)
            equity = record.get("Equity")
            debt = record.get("Total_Debt")
            row["Invested_Capital"] = (
                float(equity) + float(debt)
                if equity is not None
                and debt is not None
                and not pd.isna(equity)
                and not pd.isna(debt)
                else None
            )
            enriched.append(row)

        balance_rows = {}
        for field, label in BALANCE_ROW_MAP.items():
            values = [record.get(field) for record in enriched]
            numeric = pd.to_numeric(pd.Series(values), errors="coerce")
            if numeric.notna().any():
                balance_rows[label] = numeric.tolist()
        balance = (
            pd.DataFrame(balance_rows, index=periods).T if balance_rows else None
        )

        return income, balance, cashflow

    def factors_as_of(self, security_id, as_of, *, years=DEFAULT_HISTORY_YEARS):
        """Derived factor inputs, via the production derivation.

        Memoised on the *evidence*, not the date. A security's derived factors
        cannot change while the newest visible filing stays the same, so the key
        is the availability date of that filing. Across monthly rebalances a
        company files once or twice a year, so almost every lookup after the
        first is a hit -- and the key makes the cache provably safe rather than
        merely fast, since any new filing changes it.
        """
        from screener.statements import derive_statement_factors

        history = self.history_as_of(security_id, as_of, years=years)
        if not history:
            return None
        latest = history[0]
        cache_key = (str(security_id), str(latest.get("Available_From")), int(years))
        cached = self._factor_cache.get(cache_key)
        if cached is not None:
            # Age depends on the decision date, so it is recomputed per call
            # rather than served from the cache.
            record = dict(cached)
            record["Statement_Age_Days"] = _age_days(as_of, latest.get("Available_From"))
            return record

        income, balance, cashflow = self.statement_frames(
            security_id, as_of, years=years
        )
        if income is None and balance is None:
            return None
        derived = derive_statement_factors(income, balance, cashflow)
        if not derived.get("Statement_Years"):
            return None
        derived["Security_ID"] = str(security_id)
        derived["Statement_Fiscal_Year"] = latest.get("Fiscal_Year")
        derived["Statement_Available_From"] = str(latest.get("Available_From"))
        derived["Statement_Filing_Timestamp"] = str(latest.get("Filing_Timestamp"))
        # Lag between the decision date and the evidence behind it. A stale
        # statement is weaker evidence, and this makes that visible instead of
        # letting a two-year-old filing look as current as a two-month-old one.
        derived["Statement_Age_Days"] = _age_days(as_of, latest.get("Available_From"))
        derived["Statement_Has_Balance_Sheet"] = bool(latest.get("Has_Balance_Sheet"))
        derived["Latest_PAT"] = latest.get("PAT")
        derived["Latest_EPS"] = latest.get("EPS_Basic")
        derived["Latest_Shares"] = latest.get("Shares_Outstanding")
        derived["Latest_Equity"] = latest.get("Equity")
        derived["Latest_Total_Debt"] = latest.get("Total_Debt")
        derived["Latest_Cash"] = latest.get("Cash")
        derived["Latest_EBIT"] = latest.get("EBIT")
        derived["Latest_Revenue"] = latest.get("Revenue")
        self._factor_cache[cache_key] = derived
        return dict(derived)

    def cross_section(self, security_ids, as_of, *, years=DEFAULT_HISTORY_YEARS,
                      max_age_days=None):
        """Factor inputs for many securities on one date.

        ``max_age_days`` drops evidence older than a chosen staleness bound. It
        defaults to off because the right bound is a policy question, but a
        statement two or more years old is common in this archive's tail and
        should usually be excluded rather than scored as current.
        """
        rows = []
        for security_id in security_ids:
            derived = self.factors_as_of(security_id, as_of, years=years)
            if derived is None:
                continue
            if max_age_days is not None:
                age = derived.get("Statement_Age_Days")
                if age is None or age > int(max_age_days):
                    continue
            rows.append(derived)
        if not rows:
            return pd.DataFrame(columns=["Security_ID"])
        return pd.DataFrame(rows)


def attach_valuation_inputs(frame, *, price_column="Close"):
    """Add the price-dependent value-block inputs.

    Market cap is derived from the filed share count and the point-in-time price,
    never from a vendor's current market cap, which would be a look-ahead in the
    denominator of every valuation ratio.
    """
    if frame is None or len(frame) == 0:
        return frame
    working = frame.copy()
    price = pd.to_numeric(working.get(price_column), errors="coerce")
    shares = pd.to_numeric(working.get("Latest_Shares"), errors="coerce")

    working["Market_Cap"] = (price * shares).where(price.gt(0) & shares.gt(0))
    working["Current_Price"] = price
    working["EPS"] = pd.to_numeric(working.get("Latest_EPS"), errors="coerce")

    equity = pd.to_numeric(working.get("Latest_Equity"), errors="coerce")
    working["Book_Value"] = (equity / shares.where(shares > 0)).replace(
        [np.inf, -np.inf], np.nan
    )
    working["Total_Debt"] = pd.to_numeric(working.get("Latest_Total_Debt"), errors="coerce")
    working["Total_Cash"] = pd.to_numeric(working.get("Latest_Cash"), errors="coerce")
    working["EBIT_Latest"] = pd.to_numeric(working.get("Latest_EBIT"), errors="coerce")
    working["Total_Revenue"] = pd.to_numeric(working.get("Latest_Revenue"), errors="coerce")

    # Free cash flow is genuinely unavailable: the filings carry operating cash
    # flow but no capital expenditure. Left absent so the coverage machinery
    # shrinks the block honestly rather than treating OCF as FCF.
    working["Free_CashFlow"] = np.nan
    working["EV_EBITDA"] = np.nan
    return working


def coverage_report(frame):
    """Which factor inputs actually arrived, for the run report."""
    if frame is None or len(frame) == 0:
        return {"rows": 0}
    report = {"rows": int(len(frame))}
    for column in (
        "Revenue_CAGR_3Y",
        "EPS_CAGR_3Y",
        "Earnings_Stability",
        "Operating_Margin_Stability",
        "Interest_Coverage",
        "Share_Dilution_3Y",
        "Cash_Conversion",
        "ROIC",
        "ROE_Statement",
        "Gross_Profit_To_Assets",
        "OCF_To_Assets",
        "Accruals_To_Assets",
        "Market_Cap",
        "EPS",
        "Book_Value",
    ):
        if column in frame:
            report[column] = round(
                100.0 * float(pd.to_numeric(frame[column], errors="coerce").notna().mean()),
                1,
            )
    return report
