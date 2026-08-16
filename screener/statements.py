"""Annual financial-statement collection and factor-input derivation.

Yahoo's quote metadata (``Ticker.info``) is a single-period snapshot. It has no
total assets, no EBIT, no gross profit, no cash-flow history and no multi-year
series at all, and it omits ``returnOnEquity``/``returnOnAssets`` outright for
part of the NSE universe. Every quality, accrual and multi-year growth input the
factor model needs therefore has to come from the annual statements.

Statements restate at most quarterly, so this module caches aggressively and
backfills a bounded number of symbols per run. In steady state the marginal cost
of a daily run is close to zero; only the first cold build is expensive.

Every derived value is point-in-time with respect to the statements Yahoo
publishes today. This module deliberately does not attempt to reconstruct what
was known on a past date, so the outputs are suitable for a forward screen but
NOT for a look-ahead-free historical backtest.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Bump whenever a derived column's meaning changes so an older cache cannot mix
# incompatible definitions into a live cross-section.
STATEMENT_SCHEMA_VERSION = 2

# Yahoo row labels. Several are absent for banks and other financials, which is
# expected: those sectors are routed to the specialist quality path instead of
# being scored on an industrial-company template.
INCOME_ROWS = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "gross_profit": ("Gross Profit",),
    "ebit": ("EBIT", "Operating Income"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
    "tax_rate": ("Tax Rate For Calcs",),
    "eps": ("Diluted EPS", "Basic EPS"),
}
BALANCE_ROWS = {
    "total_assets": ("Total Assets",),
    "invested_capital": ("Invested Capital",),
    "equity": ("Stockholders Equity", "Common Stock Equity"),
    "total_debt": ("Total Debt",),
    "cash": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
    "shares": ("Ordinary Shares Number", "Share Issued"),
    "current_assets": ("Current Assets",),
    "current_liabilities": ("Current Liabilities",),
}
CASHFLOW_ROWS = {
    "ocf": ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
    "fcf": ("Free Cash Flow",),
    "capex": ("Capital Expenditure", "Capital Expenditure Reported"),
}

# Columns written to the cache. Order is stable so the CSV diff stays readable.
DERIVED_COLUMNS = (
    "Statement_Years",
    "Statement_Latest_Period",
    "ROIC",
    "ROE_Statement",
    "ROA_Statement",
    "Equity_To_Assets",
    "Statement_Total_Revenue",
    "Statement_Total_Debt",
    "Statement_Total_Cash",
    "Statement_Shares_Outstanding",
    "Statement_Current_Assets",
    "Statement_Current_Liabilities",
    "Statement_Current_Ratio",
    "Statement_Debt_To_Equity_Pct",
    "Statement_Free_Cash_Flow",
    "Statement_Free_Cash_Flow_Source",
    "EBIT_Latest",
    "EBITDA_Latest",
    "Gross_Profit_To_Assets",
    "OCF_To_Assets",
    "FCF_To_Assets",
    "Accruals_To_Assets",
    "Cash_Conversion",
    "Interest_Coverage",
    "Net_Debt_To_EBITDA",
    "Operating_Margin_Latest",
    "Operating_Margin_Stability",
    "Earnings_Stability",
    "Revenue_CAGR_3Y",
    "EPS_CAGR_3Y",
    "Revenue_YoY_Latest",
    "EPS_YoY_Latest",
    "Revenue_Acceleration",
    "EPS_Acceleration",
    "Margin_Direction",
    "Asset_Growth_1Y",
    "Share_Dilution_3Y",
    "Statement_Negative_Base_Flags",
)


STATEMENT_FALLBACKS = {
    # target column: (statement-derived column, unit/source note)
    "ROA": ("ROA_Statement", "annual statements"),
    "Current_Ratio": ("Statement_Current_Ratio", "annual statements"),
    "Debt_to_Equity": (
        "Statement_Debt_To_Equity_Pct",
        "annual statements; percentage points",
    ),
    "Free_CashFlow": ("Statement_Free_Cash_Flow", "annual cash-flow statement"),
    "Total_Debt": ("Statement_Total_Debt", "annual balance sheet"),
    "Total_Cash": ("Statement_Total_Cash", "annual balance sheet"),
    "Shares_Outstanding": (
        "Statement_Shares_Outstanding",
        "annual balance sheet",
    ),
    "Total_Revenue": ("Statement_Total_Revenue", "annual income statement"),
    "EBITDA": ("EBITDA_Latest", "annual income statement"),
}


def apply_statement_fallbacks(frame):
    """Fill absent Yahoo quote fields from the same issuer's statements.

    Quote metadata is convenient but sparse for NSE listings. Annual statement
    rows are already collected for Model 5.0, so use them only where the quote
    field is absent and publish a per-field source marker. A reported quote
    value always wins; this function never blends or silently overwrites two
    providers' definitions.
    """
    if frame is None or frame.empty:
        return frame
    result = frame.copy()
    for target, (fallback_column, fallback_note) in STATEMENT_FALLBACKS.items():
        current = pd.to_numeric(
            result.get(target, pd.Series(index=result.index, dtype=float)),
            errors="coerce",
        )
        fallback = pd.to_numeric(
            result.get(
                fallback_column, pd.Series(index=result.index, dtype=float)
            ),
            errors="coerce",
        )
        use_fallback = current.isna() & fallback.notna()
        result[target] = current.where(~use_fallback, fallback)
        source = pd.Series("unavailable", index=result.index, dtype="object")
        source.loc[current.notna()] = "Yahoo Finance quote metadata"
        source.loc[use_fallback] = f"Yahoo Finance {fallback_note}"
        if target == "Free_CashFlow" and "Statement_Free_Cash_Flow_Source" in result:
            detail = result["Statement_Free_Cash_Flow_Source"].fillna("").astype(str)
            source.loc[use_fallback & detail.eq("reported_free_cash_flow")] = (
                "Yahoo Finance annual cash-flow statement; reported free cash flow"
            )
            source.loc[
                use_fallback
                & detail.eq("operating_cash_flow_plus_capital_expenditure")
            ] = (
                "Yahoo Finance annual cash-flow statement; "
                "operating cash flow plus capital expenditure"
            )
        result[f"{target}_Source"] = source
    return result


def _first_available(frame, labels):
    """Return the first present, non-empty row as a newest-first float series."""
    if frame is None or getattr(frame, "empty", True):
        return None
    for label in labels:
        if label in frame.index:
            series = pd.to_numeric(frame.loc[label], errors="coerce").dropna()
            if not series.empty:
                # yfinance orders statement columns newest-first; make that
                # explicit rather than relying on the vendor's ordering.
                return series.sort_index(ascending=False)
    return None


def _value(series, position=0):
    if series is None or len(series) <= position:
        return None
    value = float(series.iloc[position])
    return value if np.isfinite(value) else None


def _ratio(numerator, denominator, *, denominator_must_be_positive=True):
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    if denominator_must_be_positive and denominator <= 0:
        return None
    result = numerator / denominator
    return float(result) if np.isfinite(result) else None


def _cagr(series, years):
    """Compound annual growth over ``years``, or None from a non-positive base.

    A CAGR measured from a negative or zero base is arithmetically defined but
    economically meaningless, and it is the single most common way a screen ends
    up ranking a loss-making company as its fastest grower. Return None and let
    the caller record the reason.
    """
    if series is None or len(series) < years + 1:
        return None
    latest = _value(series, 0)
    base = _value(series, years)
    if latest is None or base is None or base <= 0:
        return None
    if latest <= 0:
        # A collapse into losses is real evidence; floor it rather than
        # returning a complex root.
        return -1.0
    result = (latest / base) ** (1.0 / years) - 1.0
    return float(result) if np.isfinite(result) else None


def _yoy(series):
    if series is None or len(series) < 2:
        return None
    latest, prior = _value(series, 0), _value(series, 1)
    if latest is None or prior is None or prior <= 0:
        return None
    result = latest / prior - 1.0
    return float(result) if np.isfinite(result) else None


def _stability(series, *, as_growth=False):
    """Dispersion of a series. Lower is more stable; None when unmeasurable."""
    if series is None or len(series) < 3:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    if as_growth:
        # Oldest-first so pct_change reads forward in time.
        ordered = values.sort_index(ascending=True)
        base = ordered.shift(1)
        growth = (ordered - base) / base.abs().where(base.abs() > 0)
        values = growth.replace([np.inf, -np.inf], np.nan).dropna()
        if len(values) < 2:
            return None
    result = float(values.std(ddof=1))
    return result if np.isfinite(result) else None


def derive_statement_factors(income, balance, cashflow):
    """Derive every factor input the model needs from three annual statements.

    Pure and side-effect free so the arithmetic can be unit-tested against
    hand-built frames without touching the network.
    """
    revenue = _first_available(income, INCOME_ROWS["revenue"])
    gross_profit = _first_available(income, INCOME_ROWS["gross_profit"])
    ebit = _first_available(income, INCOME_ROWS["ebit"])
    ebitda = _first_available(income, INCOME_ROWS["ebitda"])
    net_income = _first_available(income, INCOME_ROWS["net_income"])
    interest = _first_available(income, INCOME_ROWS["interest_expense"])
    tax_rate = _first_available(income, INCOME_ROWS["tax_rate"])
    eps = _first_available(income, INCOME_ROWS["eps"])

    total_assets = _first_available(balance, BALANCE_ROWS["total_assets"])
    invested_capital = _first_available(balance, BALANCE_ROWS["invested_capital"])
    equity = _first_available(balance, BALANCE_ROWS["equity"])
    total_debt = _first_available(balance, BALANCE_ROWS["total_debt"])
    cash = _first_available(balance, BALANCE_ROWS["cash"])
    shares = _first_available(balance, BALANCE_ROWS["shares"])
    current_assets = _first_available(balance, BALANCE_ROWS["current_assets"])
    current_liabilities = _first_available(
        balance, BALANCE_ROWS["current_liabilities"]
    )

    ocf = _first_available(cashflow, CASHFLOW_ROWS["ocf"])
    fcf = _first_available(cashflow, CASHFLOW_ROWS["fcf"])
    capex = _first_available(cashflow, CASHFLOW_ROWS["capex"])

    negative_base = []
    out = {column: None for column in DERIVED_COLUMNS}

    year_counts = [len(s) for s in (revenue, total_assets, ocf) if s is not None]
    out["Statement_Years"] = max(year_counts) if year_counts else 0
    for candidate in (revenue, total_assets, ocf):
        if candidate is not None and len(candidate):
            out["Statement_Latest_Period"] = str(candidate.index[0])[:10]
            break

    # --- return on invested capital ---------------------------------------
    # NOPAT over average invested capital. Averaging the opening and closing
    # balance avoids crediting a full year of profit to a capital base that was
    # only raised at the very end of it.
    ebit_latest = _value(ebit, 0)
    rate = _value(tax_rate, 0)
    if rate is None or not (0.0 <= rate < 1.0):
        rate = 0.25  # documented fallback; Indian statutory rate is ~25%
    invested_now = _value(invested_capital, 0)
    invested_prior = _value(invested_capital, 1)
    if invested_now is not None and invested_prior is not None:
        invested_avg = (invested_now + invested_prior) / 2.0
    else:
        invested_avg = invested_now
    if ebit_latest is not None and invested_avg is not None and invested_avg > 0:
        out["ROIC"] = float(ebit_latest * (1.0 - rate) / invested_avg)

    # --- statement-derived returns -----------------------------------------
    # Banks and other financials have no EBIT, gross profit or current-asset
    # lines in Yahoo's income statement, and Yahoo's quote metadata omits
    # returnOnEquity/returnOnAssets for part of the universe. These three are
    # reported for effectively the whole market and are what the specialist
    # quality block is scored on.
    net_income_latest_raw = _value(net_income, 0)
    equity_now, equity_prior = _value(equity, 0), _value(equity, 1)
    equity_avg = (
        (equity_now + equity_prior) / 2.0
        if equity_now is not None and equity_prior is not None
        else equity_now
    )
    out["ROE_Statement"] = _ratio(net_income_latest_raw, equity_avg)
    assets_now, assets_prior = _value(total_assets, 0), _value(total_assets, 1)
    assets_avg = (
        (assets_now + assets_prior) / 2.0
        if assets_now is not None and assets_prior is not None
        else assets_now
    )
    out["ROA_Statement"] = _ratio(net_income_latest_raw, assets_avg)
    out["Equity_To_Assets"] = _ratio(equity_now, assets_now)
    out["Statement_Total_Revenue"] = _value(revenue, 0)
    out["Statement_Total_Debt"] = _value(total_debt, 0)
    out["Statement_Total_Cash"] = _value(cash, 0)
    out["Statement_Shares_Outstanding"] = _value(shares, 0)
    out["Statement_Current_Assets"] = _value(current_assets, 0)
    out["Statement_Current_Liabilities"] = _value(current_liabilities, 0)
    out["Statement_Current_Ratio"] = _ratio(
        out["Statement_Current_Assets"],
        out["Statement_Current_Liabilities"],
    )
    statement_debt_to_equity = _ratio(out["Statement_Total_Debt"], equity_now)
    out["Statement_Debt_To_Equity_Pct"] = (
        statement_debt_to_equity * 100.0
        if statement_debt_to_equity is not None
        else None
    )
    reported_fcf = _value(fcf, 0)
    latest_ocf = _value(ocf, 0)
    latest_capex = _value(capex, 0)
    if reported_fcf is not None:
        out["Statement_Free_Cash_Flow"] = reported_fcf
        out["Statement_Free_Cash_Flow_Source"] = "reported_free_cash_flow"
    elif latest_ocf is not None and latest_capex is not None:
        # Yahoo reports capital expenditure as a negative cash-flow line.
        out["Statement_Free_Cash_Flow"] = latest_ocf + latest_capex
        out["Statement_Free_Cash_Flow_Source"] = (
            "operating_cash_flow_plus_capital_expenditure"
        )
    out["EBIT_Latest"] = ebit_latest
    out["EBITDA_Latest"] = _value(ebitda, 0)

    # --- asset-scaled profitability and cash generation --------------------
    assets_latest = _value(total_assets, 0)
    out["Gross_Profit_To_Assets"] = _ratio(_value(gross_profit, 0), assets_latest)
    out["OCF_To_Assets"] = _ratio(_value(ocf, 0), assets_latest)
    out["FCF_To_Assets"] = _ratio(_value(fcf, 0), assets_latest)

    # Sloan accruals: earnings not backed by operating cash. Signed so that a
    # LOWER value is better, matching the direction the factor model expects.
    net_income_latest = _value(net_income, 0)
    ocf_latest = _value(ocf, 0)
    if net_income_latest is not None and ocf_latest is not None and assets_latest:
        accruals = (net_income_latest - ocf_latest) / assets_latest
        if np.isfinite(accruals):
            out["Accruals_To_Assets"] = float(accruals)
    out["Cash_Conversion"] = _ratio(ocf_latest, net_income_latest)

    # --- solvency ----------------------------------------------------------
    interest_latest = _value(interest, 0)
    if ebit_latest is not None and interest_latest:
        coverage = ebit_latest / abs(interest_latest)
        if np.isfinite(coverage):
            # Bound the tail: 500x and 5000x coverage are the same evidence.
            out["Interest_Coverage"] = float(np.clip(coverage, -100.0, 100.0))
    debt_latest = _value(total_debt, 0)
    cash_latest = _value(cash, 0)
    ebitda_latest = _value(ebitda, 0)
    if debt_latest is not None and ebitda_latest and ebitda_latest > 0:
        net_debt = debt_latest - (cash_latest or 0.0)
        ratio = net_debt / ebitda_latest
        if np.isfinite(ratio):
            out["Net_Debt_To_EBITDA"] = float(np.clip(ratio, -20.0, 50.0))

    # --- margins and stability ---------------------------------------------
    operating_margin = None
    if ebit is not None and revenue is not None:
        aligned = pd.DataFrame({"ebit": ebit, "revenue": revenue}).dropna()
        aligned = aligned[aligned["revenue"] > 0]
        if not aligned.empty:
            operating_margin = aligned["ebit"] / aligned["revenue"]
            out["Operating_Margin_Latest"] = float(operating_margin.iloc[0])
            out["Operating_Margin_Stability"] = _stability(operating_margin)
            if len(operating_margin) >= 3:
                prior_mean = float(operating_margin.iloc[1:].mean())
                out["Margin_Direction"] = float(
                    operating_margin.iloc[0] - prior_mean
                )
    out["Earnings_Stability"] = _stability(net_income, as_growth=True)

    # --- growth ------------------------------------------------------------
    out["Revenue_CAGR_3Y"] = _cagr(revenue, 3)
    if out["Revenue_CAGR_3Y"] is None and revenue is not None and len(revenue) >= 4:
        negative_base.append("revenue_base")
    out["EPS_CAGR_3Y"] = _cagr(eps, 3)
    if out["EPS_CAGR_3Y"] is None and eps is not None and len(eps) >= 4:
        negative_base.append("eps_base")
    out["Revenue_YoY_Latest"] = _yoy(revenue)
    out["EPS_YoY_Latest"] = _yoy(eps)
    # Acceleration compares the most recent year against the medium-term trend.
    if out["Revenue_YoY_Latest"] is not None and out["Revenue_CAGR_3Y"] is not None:
        out["Revenue_Acceleration"] = float(
            out["Revenue_YoY_Latest"] - out["Revenue_CAGR_3Y"]
        )
    if out["EPS_YoY_Latest"] is not None and out["EPS_CAGR_3Y"] is not None:
        out["EPS_Acceleration"] = float(out["EPS_YoY_Latest"] - out["EPS_CAGR_3Y"])

    # --- capital discipline -------------------------------------------------
    # Aggressive asset growth and repeated dilution both predict weak future
    # returns; they enter the quality block as penalties.
    out["Asset_Growth_1Y"] = _yoy(total_assets)
    if shares is not None and len(shares) >= 4:
        latest_shares, base_shares = _value(shares, 0), _value(shares, 3)
        if latest_shares and base_shares and base_shares > 0:
            dilution = (latest_shares / base_shares) ** (1.0 / 3.0) - 1.0
            if np.isfinite(dilution):
                out["Share_Dilution_3Y"] = float(dilution)

    out["Statement_Negative_Base_Flags"] = ",".join(sorted(set(negative_base)))
    return out


class FinancialStatementCollector:
    """Fetch, cache and derive annual-statement factor inputs per symbol."""

    def __init__(self, config, *, ticker_factory=None, clock=None):
        self.config = config
        # Injectable so tests never touch the network.
        self._ticker_factory = ticker_factory
        self._clock = clock or (lambda: datetime.now())

    def _cache_path(self):
        return self.config.OUTPUT_DIR / "statement_cache.csv"

    def _make_ticker(self, symbol):
        if self._ticker_factory is not None:
            return self._ticker_factory(symbol)
        import yfinance as yf

        return yf.Ticker(symbol)

    def _load_cache(self):
        path = self._cache_path()
        if not path.exists():
            return pd.DataFrame(), set()
        try:
            cached = pd.read_csv(path)
        except Exception as exc:
            logger.warning("Statement cache load failed: %s", exc)
            return pd.DataFrame(), set()
        if cached.empty or "Symbol" not in cached.columns:
            return pd.DataFrame(), set()
        version = pd.to_numeric(
            cached.get("Statement_Schema_Version"), errors="coerce"
        )
        if version.isna().any() or not version.eq(STATEMENT_SCHEMA_VERSION).all():
            logger.info(
                "Statement cache uses an older schema version - rebuilding it"
            )
            return pd.DataFrame(), set()
        max_age = int(getattr(self.config, "STATEMENT_CACHE_MAX_AGE_DAYS", 90))
        fetched = pd.to_datetime(cached.get("Statement_Cached_Date"), errors="coerce")
        cutoff = pd.Timestamp(self._clock()).normalize() - pd.Timedelta(days=max_age)
        fresh_mask = fetched.notna() & (fetched >= cutoff)
        cached["Symbol"] = cached["Symbol"].astype(str).str.strip().str.upper()
        fresh_symbols = set(cached.loc[fresh_mask, "Symbol"])
        return cached, fresh_symbols

    def fetch_symbol(self, symbol):
        """Return derived factors for one symbol, or None when unavailable."""
        try:
            ticker = self._make_ticker(f"{symbol}.NS")
            derived = derive_statement_factors(
                ticker.income_stmt, ticker.balance_sheet, ticker.cashflow
            )
        except Exception as exc:
            logger.debug("Statement fetch failed for %s: %s", symbol, exc)
            return None
        if not derived.get("Statement_Years"):
            return None
        derived["Symbol"] = symbol
        derived["Statement_Schema_Version"] = STATEMENT_SCHEMA_VERSION
        derived["Statement_Cached_Date"] = pd.Timestamp(
            self._clock()
        ).strftime("%Y-%m-%d")
        derived["Statement_Source"] = "Yahoo Finance annual statements"
        return derived

    def collect(self, symbols):
        """Return a per-symbol statement frame, reusing cache where fresh.

        Only ``STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN`` misses are fetched per run.
        A cold universe therefore fills in over several runs instead of turning
        one run into a multi-hour job; symbols still missing are simply reported
        as having no statement evidence and the policy fails them closed.
        """
        # Caller order is a PRIORITY order and is preserved. Sorting here would
        # make the per-run budget fetch alphabetically, and because the factor
        # model's coverage gate treats statement data as a prerequisite for BUY
        # eligibility, that let a symbol's first letter decide whether it could
        # be rated at all. A partial build must cover the most investable names
        # first, not the ones nearest the front of the alphabet.
        wanted = list(
            dict.fromkeys(
                str(s).strip().upper() for s in symbols if str(s).strip()
            )
        )
        if not wanted or not getattr(
            self.config, "STATEMENT_COLLECTION_ENABLED", True
        ):
            return pd.DataFrame(columns=["Symbol"])

        cached, fresh_symbols = self._load_cache()
        reusable = [s for s in wanted if s in fresh_symbols]
        missing = [s for s in wanted if s not in fresh_symbols]
        budget = int(
            getattr(self.config, "STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN", 400)
        )
        to_fetch = missing[:budget] if budget > 0 else []
        logger.info(
            "Statements: %d fresh-cached, %d missing, %d will be fetched this run",
            len(reusable),
            len(missing),
            len(to_fetch),
        )

        fetched_records = []
        per_minute = max(1, int(getattr(self.config, "STATEMENT_REQUESTS_PER_MINUTE", 40)))
        window_start = time.time()
        in_window = 0
        for index, symbol in enumerate(to_fetch):
            in_window += 1
            if in_window >= per_minute:
                elapsed = time.time() - window_start
                if elapsed < 60:
                    time.sleep(62 - elapsed)
                in_window = 0
                window_start = time.time()
            record = self.fetch_symbol(symbol)
            if record is not None:
                fetched_records.append(record)
            if (index + 1) % 100 == 0:
                logger.info("Statements fetched %d/%d", index + 1, len(to_fetch))

        fetched_symbols = {record["Symbol"] for record in fetched_records}
        frames = []
        if not cached.empty:
            # Keep every cached row, not just this run's universe: dropping rows
            # for symbols absent today would force a refetch tomorrow.
            frames.append(cached[~cached["Symbol"].isin(fetched_symbols)])
        if fetched_records:
            frames.append(pd.DataFrame(fetched_records))
        if not frames:
            return pd.DataFrame(columns=["Symbol"])
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.drop_duplicates(subset="Symbol", keep="last")
        try:
            self._cache_path().parent.mkdir(parents=True, exist_ok=True)
            combined.to_csv(self._cache_path(), index=False)
            logger.info(
                "Statement cache saved (%d records) -> %s",
                len(combined),
                self._cache_path(),
            )
        except Exception as exc:
            logger.warning("Statement cache save failed: %s", exc)

        # Persistence and scoring have different contracts. Expired rows stay
        # in the cache so a later run can retry them, but only fresh cached rows
        # and successful refreshes may contribute evidence to today's model.
        # In particular, a stale row outside this run's budget (or one whose
        # refresh failed) must not silently pass the statement-coverage gates.
        usable_symbols = fresh_symbols | fetched_symbols
        result = combined[
            combined["Symbol"].isin(wanted)
            & combined["Symbol"].isin(usable_symbols)
        ].copy()
        keep = ["Symbol", "Statement_Cached_Date", "Statement_Source"] + [
            column for column in DERIVED_COLUMNS if column in result.columns
        ]
        return result[[column for column in keep if column in result.columns]]

    @staticmethod
    def _priority_order(frame):
        """Most-traded symbols first, so a partial build covers what matters.

        Falls back to market cap, then to the frame's own order. Never sorts
        alphabetically: see the note in ``collect``.
        """
        for column in ("Median_Turnover_20D_INR", "Avg_Turnover_INR", "Market_Cap"):
            if column in frame:
                ranked = pd.to_numeric(frame[column], errors="coerce")
                if ranked.notna().any():
                    order = ranked.sort_values(
                        ascending=False, na_position="last", kind="mergesort"
                    ).index
                    return frame.loc[order, "Symbol"].astype(str).tolist()
        return frame["Symbol"].astype(str).tolist()

    @staticmethod
    def _record_coverage(enriched):
        """Attach and report run-level statement coverage."""
        available = int(enriched["Statement_Record_Available"].sum())
        share = available / len(enriched) if len(enriched) else 0.0
        logger.info(
            "Statement evidence attached for %d/%d symbol(s) (%.0f%%)",
            available,
            len(enriched),
            share * 100,
        )
        # A partial build is not a neutral degradation. The factor model's
        # coverage gate makes statement data a prerequisite for BUY
        # eligibility, so a half-built cache does not merely weaken the quality
        # block -- it decides which symbols can be rated at all, and the
        # cross-sectional percentiles are computed over the covered subset.
        # Say so loudly rather than publishing a confident-looking ranking of
        # whichever names happened to be fetched first.
        if share < 0.90:
            logger.warning(
                "Statement coverage is %.0f%% (%d/%d). The factor model's "
                "quality and growth blocks are unobserved for the remainder, "
                "and only covered symbols can clear the BUY coverage gate. "
                "This ranking is NOT representative of the full universe; "
                "raise STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN or re-run until the "
                "cache is built before comparing models.",
                share * 100,
                available,
                len(enriched),
            )
        enriched["Statement_Universe_Coverage"] = round(share, 4)
        return enriched

    def enrich(self, frame):
        """Left-join derived statement factors onto a scored/merged frame."""
        if frame is None or frame.empty or "Symbol" not in frame:
            return frame
        statements = self.collect(self._priority_order(frame))
        if statements.empty:
            enriched = frame.copy()
            enriched["Statement_Record_Available"] = False
            for column in DERIVED_COLUMNS:
                if column not in enriched:
                    enriched[column] = np.nan
            return self._record_coverage(enriched)
        enriched = frame.merge(
            statements, on="Symbol", how="left", validate="one_to_one"
        )
        enriched["Statement_Record_Available"] = (
            pd.to_numeric(enriched.get("Statement_Years"), errors="coerce")
            .fillna(0)
            .gt(0)
        )
        return self._record_coverage(enriched)
