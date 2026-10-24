"""What a valuation ratio divides the price by, kept apart from the price.

Every price ratio is the price over something the company reported: P/E over
trailing profit, P/B over book equity, EV/EBITDA over trailing EBITDA, the
yield over the dividend. The reported side changes when a result is filed;
the price changes every few minutes. Stored as a finished ratio, either change
leaves it stale, so the company's side is stored on its own -- the
``valuation_basis`` table, one row per market and symbol -- and the ratios are
worked out wherever a price is at hand:

* the evening run, against the completed close, for scoring
  (`price_ratios`, called by
  `screener.data_collection.align_valuation_to_completed_price_bar`);
* the ``live_valuation`` view, against the live quote, for display
  (storage/valuation_basis_schema.sql). The two share one definition, held
  equal by tests/test_valuation_basis.py.

Two jobs write the basis. The evening run publishes every symbol's, from the
same frame it scored (`attach_basis`, then the dashboard publisher). The
quarterly filings worker replaces the trailing-year lines the moment a
company files (`trailing_year`), so a result moves P/E within minutes of the
filing rather than at the next run.

The basis holds company totals, not per-share figures, so the filings worker
needs no share count to update it; per share is total over
``Shares_Outstanding``, the count market cap is worked out from.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FILINGS_SOURCE = "NSE integrated filings"

# Provenance of the trailing-year lines on the scored frame; the dashboard
# publisher writes them with the basis. Rows the filings did not supply keep
# the vendor's figures and name the vendor's source.
BASIS_SOURCE_COLUMN = "Basis_Source"
BASIS_PERIOD_COLUMN = "Basis_Period_End"
BASIS_STATEMENT_COLUMN = "Basis_Statement"

# The trailing year, summed from the latest four filed quarters on one basis
# (`trailing_year`).
TTM_COLUMNS = (
    "Symbol",
    "TTM_Period_End",
    "TTM_Basis",
    "TTM_Revenue",
    "TTM_Net_Profit",
    "TTM_EBITDA",
    "TTM_Operating_Income",
)


def trailing_year(facts, symbols, *, today, max_age_days):
    """Trailing-year sums per symbol from its latest four filed quarters.

    The four must be consecutive and on one basis, and the latest no older
    than ``max_age_days``; consolidated wins a tie. A line missing from any
    of the four leaves that sum unreported, never a three-quarter total.
    Operating income is EBIT without other income, as the vendor's operating
    margin measures it.
    """
    empty = pd.DataFrame(columns=list(TTM_COLUMNS))
    if facts is None or len(facts) == 0:
        return empty
    wanted = {str(symbol) for symbol in symbols}
    working = facts[facts["Symbol"].isin(wanted) & (facts["Filed_On"] <= today)].copy()
    if working.empty:
        return empty
    for column in ("Revenue", "Net_Profit", "EBITDA", "PBT", "Interest", "Other_Income"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working["Operating_Income"] = (
        working["PBT"] + working["Interest"] - working["Other_Income"]
    )
    working["Quarter"] = pd.to_datetime(working["Period_End"]).dt.to_period("Q")
    oldest = (pd.Timestamp(today) - pd.Timedelta(days=int(max_age_days))).date()

    rows = []
    for symbol, group in working.groupby("Symbol", sort=False):
        best = None
        for basis in (True, False):
            quarters = group[group["Is_Consolidated"] == basis].set_index("Quarter")
            if quarters.empty:
                continue
            latest = quarters.index.max()
            window = [latest - step for step in range(4)]
            if not set(window) <= set(quarters.index):
                continue
            if quarters.loc[latest, "Period_End"] < oldest:
                continue
            if best is None or latest > best[0]:
                best = (latest, basis, quarters.loc[window])
        if best is None:
            continue
        latest, basis, window = best
        rows.append(
            {
                "Symbol": symbol,
                "TTM_Period_End": window["Period_End"].max().isoformat(),
                "TTM_Basis": "consolidated" if basis else "standalone",
                "TTM_Revenue": window["Revenue"].sum(min_count=4),
                "TTM_Net_Profit": window["Net_Profit"].sum(min_count=4),
                "TTM_EBITDA": window["EBITDA"].sum(min_count=4),
                "TTM_Operating_Income": window["Operating_Income"].sum(min_count=4),
            }
        )
    return pd.DataFrame(rows, columns=list(TTM_COLUMNS)) if rows else empty


def apply_trailing_year(frame, keys, trailing, served):
    """Replace the vendor's trailing-year figures with filed ones on ``served`` rows.

    ``trailing`` is `trailing_year` indexed by symbol; ``keys`` the frame's
    normalised symbols. A figure the filings cannot support (a line missing
    from a quarter, no share count) keeps the vendor's value.
    """
    enriched = frame.copy()

    def vendor(column):
        return pd.to_numeric(
            enriched.get(column, pd.Series(np.nan, index=enriched.index)),
            errors="coerce",
        )

    def filed(column):
        return keys.map(trailing[column]).astype(float)

    revenue = filed("TTM_Revenue").where(lambda v: v > 0)
    profit = filed("TTM_Net_Profit")
    shares = vendor("Shares_Outstanding").where(lambda v: v > 0)
    equity = (vendor("Book_Value") * shares).where(lambda v: v > 0)
    # Profit per share is profit over the current share count, as market cap
    # is, so a split between the four quarters does not move it.
    overlay = {
        "EPS": profit / shares,
        "EBITDA": filed("TTM_EBITDA"),
        "Total_Revenue": filed("TTM_Revenue"),
        "Profit_Margin": profit / revenue,
        "Operating_Margin": filed("TTM_Operating_Income") / revenue,
        "ROE": profit / equity,
    }
    for column, value in overlay.items():
        enriched[column] = value.where(served & value.notna(), vendor(column))
    enriched[BASIS_SOURCE_COLUMN] = pd.Series(FILINGS_SOURCE, index=enriched.index).where(
        served, enriched.get(BASIS_SOURCE_COLUMN)
    )
    enriched[BASIS_PERIOD_COLUMN] = keys.map(trailing["TTM_Period_End"]).where(
        served, enriched.get(BASIS_PERIOD_COLUMN)
    )
    enriched[BASIS_STATEMENT_COLUMN] = keys.map(trailing["TTM_Basis"]).where(
        served, enriched.get(BASIS_STATEMENT_COLUMN)
    )
    return enriched


def price_ratios(price, *, eps, book_value, shares, ebitda, debt, cash):
    """The price ratios, each where its inputs allow, else NaN.

    The one definition of the arithmetic; ``live_valuation`` repeats it in SQL
    and tests/test_valuation_basis.py holds the two equal. A zero denominator
    has no ratio; a negative one does (a loss-making P/E), as before.
    """
    valid_price = price.gt(0)
    market_cap = (price * shares).where(valid_price & shares.gt(0))
    return {
        "PE_Ratio": (price / eps).where(valid_price & eps.ne(0)),
        "PB_Ratio": (price / book_value).where(valid_price & book_value.ne(0)),
        "Market_Cap": market_cap,
        "EV_EBITDA": ((market_cap + debt - cash) / ebitda).where(ebitda.ne(0)),
    }


def attach_basis(frame):
    """Add the company totals the ``valuation_basis`` row stores.

    Called on the final scored frame, so the basis is exactly what the run's
    own ratios were worked out from.
    """
    out = frame.copy()

    def numeric(column):
        return pd.to_numeric(
            out.get(column, pd.Series(np.nan, index=out.index)), errors="coerce"
        )

    shares = numeric("Shares_Outstanding").where(lambda v: v > 0)
    out["Basis_Net_Profit_TTM"] = numeric("EPS") * shares
    out["Basis_Book_Equity"] = numeric("Book_Value") * shares
    # The rate the run's yield was worked out from, vendor rate or derived.
    out["Basis_Dividend_Per_Share"] = numeric("Dividend_Yield_Ratio") * numeric(
        "Current_Price"
    )
    if BASIS_SOURCE_COLUMN not in out:
        out[BASIS_SOURCE_COLUMN] = np.nan
    out[BASIS_SOURCE_COLUMN] = out[BASIS_SOURCE_COLUMN].where(
        out[BASIS_SOURCE_COLUMN].notna(), out.get("Fundamental_Source")
    )
    for column in (BASIS_PERIOD_COLUMN, BASIS_STATEMENT_COLUMN):
        if column not in out:
            out[column] = np.nan
    return out
