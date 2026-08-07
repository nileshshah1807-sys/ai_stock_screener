"""Reverse DCF valuation enrichment."""

import logging

import numpy as np
import pandas as pd

from .scoring import sort_by_recommendation

logger = logging.getLogger(__name__)

class ReverseDCFModel:
    """Market-implied DCF assumptions for each stock.

    This follows the public institutional reverse-DCF pattern: compare current
    market cap with discounted future free cash flows and solve for the growth
    assumptions required to justify today's price. It is not a proprietary
    Goldman Sachs model; their internal templates are not public.

    The explicit 5-year growth assumption is sector- and size-aware rather than
    a single flat number: mature/defensive sectors (utilities, FMCG) and mega/
    large-cap names get a lower benchmark growth rate, while higher-growth
    sectors (tech, healthcare) and small/mid caps get a higher one. This avoids
    unfairly flagging slow-but-stable compounders as "stretched" just because
    they can't match a generic 15% growth bar, and avoids flattering high-growth
    sectors with too low a bar.
    """

    # Long-run explicit-growth benchmarks by yfinance GICS-style sector name.
    # Values are annual FCF growth rates assumed reasonable for a mature player
    # in that sector over a 5-year explicit forecast window.
    SECTOR_GROWTH_BENCHMARKS = {
        "Technology": 0.18,
        "Communication Services": 0.16,
        "Healthcare": 0.16,
        "Consumer Cyclical": 0.15,
        "Industrials": 0.14,
        "Financial Services": 0.13,
        "Basic Materials": 0.12,
        "Real Estate": 0.12,
        "Energy": 0.10,
        "Consumer Defensive": 0.10,
        "Utilities": 0.08,
    }
    DEFAULT_SECTOR_GROWTH = 0.15  # unknown/missing sector - matches prior flat assumption
    EXPECTED_GROWTH_FLOOR = 0.05
    EXPECTED_GROWTH_CAP = 0.25
    UNSUPPORTED_DCF_SECTORS = {"Financial Services", "Real Estate"}

    def __init__(self, config):
        self.config = config

    def _size_adjustment(self, market_cap):
        """Mega/large caps grow slower at scale; small/mid caps get a premium."""
        if market_cap is None or market_cap <= 0:
            return 0.0
        market_cap_cr = market_cap / 1e7
        if market_cap_cr >= 200_000:      # mega cap (>= ~Rs 2 lakh Cr)
            return -0.03
        if market_cap_cr >= 20_000:       # large cap
            return -0.015
        if market_cap_cr >= 5_000:        # mid cap
            return 0.0
        return 0.02                        # small cap

    def _expected_growth(self, sector, market_cap):
        """Sector- and size-aware benchmark for the explicit 5Y growth assumption."""
        base = self.SECTOR_GROWTH_BENCHMARKS.get(sector, self.DEFAULT_SECTOR_GROWTH)
        adjusted = base + self._size_adjustment(market_cap)
        return round(max(self.EXPECTED_GROWTH_FLOOR, min(adjusted, self.EXPECTED_GROWTH_CAP)), 4)

    @staticmethod
    def _safe_float(val, default=None):
        try:
            if val is None or pd.isna(val):
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _dcf_value(base_fcf, growth_rate, terminal_growth, discount_rate, years):
        if (
            base_fcf is None or base_fcf <= 0
            or discount_rate <= terminal_growth
            or years <= 0
            or growth_rate <= -1
            or terminal_growth <= -1
        ):
            return None
        value = 0.0
        fcf = base_fcf
        for year in range(1, years + 1):
            fcf *= 1 + growth_rate
            value += fcf / ((1 + discount_rate) ** year)
        terminal_value = fcf * (1 + terminal_growth) / (discount_rate - terminal_growth)
        value += terminal_value / ((1 + discount_rate) ** years)
        return value

    def _solve_rate(self, target_value, value_func, low, high):
        low_value = value_func(low)
        high_value = value_func(high)
        if low_value is None or high_value is None:
            return None
        if target_value <= low_value:
            return low
        if target_value > high_value:
            return None
        for _ in range(80):
            mid = (low + high) / 2
            mid_value = value_func(mid)
            if mid_value is None:
                return None
            if mid_value < target_value:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    @staticmethod
    def _clamp(value, low=0.0, high=100.0):
        return max(low, min(high, value))

    def _valuation_score(self, status, implied_fcf_growth, implied_terminal_growth, fcf_yield, expected_growth=None):
        if status == "low_fcf_yield":
            return 15.0
        if status != "OK":
            return 25.0
        if implied_fcf_growth is None or pd.isna(implied_fcf_growth):
            return 20.0

        # Score by how the implied growth compares to the sector/size benchmark,
        # not an absolute number - e.g. 15% implied growth is "reasonable" for a
        # tech stock (18% benchmark) but "demanding" for a utility (8% benchmark).
        benchmark = expected_growth if expected_growth else self.DEFAULT_SECTOR_GROWTH
        ratio = implied_fcf_growth / benchmark if benchmark else None

        if implied_fcf_growth < 0:
            # Low embedded expectations are attractive, but contraction can
            # also be a value trap. Do not award near-perfect valuation points
            # from this fact alone.
            score = 75.0
        elif ratio is None:
            score = 50.0
        elif ratio <= 0.53:
            score = 88.0
        elif ratio <= 0.80:
            score = 78.0
        elif ratio <= 1.20:
            score = 62.0
        elif ratio <= 1.67:
            score = 45.0
        elif ratio <= 2.33:
            score = 30.0
        else:
            score = 18.0

        if implied_terminal_growth is not None and not pd.isna(implied_terminal_growth):
            if implied_terminal_growth <= 0.02:
                score += 8.0
            elif implied_terminal_growth > 0.06:
                score -= 8.0
        else:
            score -= 5.0

        if fcf_yield is not None and not pd.isna(fcf_yield):
            if fcf_yield >= 0.05:
                score += 8.0
            elif fcf_yield >= 0.03:
                score += 4.0
            elif fcf_yield < 0.01:
                score -= 8.0

        return round(self._clamp(score), 2)

    def analyze_row(self, row):
        s = self._safe_float
        market_cap = s(row.get("Market_Cap"))
        revenue = s(row.get("Total_Revenue"))
        fcf = s(row.get("Free_CashFlow"))
        total_debt = s(row.get("Total_Debt"))
        total_cash = s(row.get("Total_Cash"))
        fcf_source = "reported"
        sector = row.get("Sector")
        sector = sector.strip() if isinstance(sector, str) and sector.strip() else None
        expected_growth = self._expected_growth(sector, market_cap)

        # A generic cash-flow DCF is not a decision-useful valuation method for
        # banks/insurers (deposits and debt are operating inputs) or most real
        # estate companies (asset/NAV and project cash-flow timing dominate).
        # Leave these rankings to the main model until a sector-specific model
        # is added; do not publish a false-precision DCF assessment.
        if sector in self.UNSUPPORTED_DCF_SECTORS:
            return self._empty_result(
                "sector_not_supported", fcf, fcf_source, market_cap, revenue, sector, expected_growth
            )

        if (fcf is None or fcf <= 0) and revenue and revenue > 0:
            fcf = revenue * self.config.REVERSE_DCF_FCF_MARGIN_FALLBACK
            fcf_source = "revenue_margin_fallback"

        if market_cap is None or market_cap <= 0:
            return self._empty_result("missing_market_cap", fcf, fcf_source, market_cap, revenue, sector, expected_growth)
        if fcf is None or fcf <= 0:
            return self._empty_result("missing_or_negative_fcf", fcf, fcf_source, market_cap, revenue, sector, expected_growth)

        # Yahoo's generic Free_CashFlow field is operating cash flow less capex,
        # not a constructed FCFF measure. Treat it as an equity cash-flow proxy
        # and compare it with market capitalization. Subtracting net debt after
        # discounting this field would mix FCFE-like cash flow with an FCFF/EV
        # valuation and double-count financing effects.
        if total_debt is not None and total_debt >= 0 and total_cash is not None and total_cash >= 0:
            net_debt = total_debt - total_cash
        else:
            net_debt = None
        enterprise_value = market_cap + net_debt if net_debt is not None else None
        cash_flow_basis = "operating_cash_flow_less_capex_equity_proxy"
        valuation_target = market_cap
        ev_method = "equity_value_proxy"

        fcf_yield = fcf / valuation_target if valuation_target > 0 else None
        revenue_fcf_margin = fcf / revenue if revenue and revenue > 0 else None
        min_valid_fcf_yield = float(getattr(self.config, "REVERSE_DCF_MIN_VALID_FCF_YIELD", 0.005))
        if fcf_yield is not None and fcf_yield < min_valid_fcf_yield:
            return self._unreliable_result(
                "low_fcf_yield",
                fcf,
                fcf_source,
                market_cap,
                revenue,
                fcf_yield,
                revenue_fcf_margin,
                sector,
                expected_growth,
                net_debt,
                enterprise_value,
                ev_method,
            )

        years = int(self.config.REVERSE_DCF_FORECAST_YEARS)
        discount_rate = float(self.config.REVERSE_DCF_DISCOUNT_RATE)
        fixed_terminal_growth = float(self.config.REVERSE_DCF_TERMINAL_GROWTH)
        fixed_growth = expected_growth
        max_terminal_growth = min(
            float(self.config.REVERSE_DCF_MAX_TERMINAL_GROWTH),
            discount_rate - 0.001,
        )

        implied_fcf_growth = self._solve_rate(
            valuation_target,
            lambda growth: self._dcf_value(fcf, growth, fixed_terminal_growth, discount_rate, years),
            float(self.config.REVERSE_DCF_MIN_GROWTH),
            float(self.config.REVERSE_DCF_MAX_GROWTH),
        )
        implied_terminal_growth = self._solve_rate(
            valuation_target,
            lambda terminal: self._dcf_value(fcf, fixed_growth, terminal, discount_rate, years),
            float(self.config.REVERSE_DCF_MIN_TERMINAL_GROWTH),
            max_terminal_growth,
        )

        base_case_value = self._dcf_value(fcf, fixed_growth, fixed_terminal_growth, discount_rate, years)
        value_to_market = (base_case_value / market_cap) if base_case_value is not None and market_cap > 0 else None
        valuation_gap = (value_to_market - 1) if value_to_market is not None else None
        # Revenue times a fixed margin is a rough research placeholder, not
        # reported cash flow. Show the implied assumptions for transparency but
        # never use an estimated FCF result to move the investment ranking.
        if implied_fcf_growth is None:
            status = "growth_above_model_range"
        elif fcf_source == "reported":
            status = "OK"
        else:
            status = "estimated_fcf"
        valuation_score = self._valuation_score(status, implied_fcf_growth, implied_terminal_growth, fcf_yield, expected_growth)

        return {
            "DCF_Status": status,
            "DCF_FCF_Source": fcf_source,
            "DCF_Cash_Flow_Basis": cash_flow_basis,
            "DCF_Sector": sector if sector else "Unknown",
            "DCF_Expected_Growth": expected_growth,
            "DCF_Base_FCF": round(fcf, 2),
            "DCF_Market_Cap": round(market_cap, 2),
            "DCF_Net_Debt": round(net_debt, 2) if net_debt is not None else np.nan,
            "DCF_Enterprise_Value": round(enterprise_value, 2) if enterprise_value is not None else np.nan,
            "DCF_EV_Method": ev_method,
            "DCF_FCF_Yield": round(fcf_yield, 4) if fcf_yield is not None else np.nan,
            "DCF_Revenue_FCF_Margin": round(revenue_fcf_margin, 4) if revenue_fcf_margin is not None else np.nan,
            "DCF_Years": years,
            "DCF_Discount_Rate": discount_rate,
            "DCF_Assumed_Growth": fixed_growth,
            "DCF_Assumed_Terminal_Growth": fixed_terminal_growth,
            "DCF_Implied_FCF_CAGR": round(implied_fcf_growth, 4) if implied_fcf_growth is not None else np.nan,
            "DCF_Implied_Terminal_Growth": round(implied_terminal_growth, 4) if implied_terminal_growth is not None else np.nan,
            "DCF_Base_Case_Value": round(base_case_value, 2) if base_case_value is not None else np.nan,
            "DCF_Value_to_Market_Cap": round(value_to_market, 4) if value_to_market is not None else np.nan,
            "DCF_Base_Case_Gap": round(valuation_gap, 4) if valuation_gap is not None else np.nan,
            "DCF_Base_Case_Upside": round(valuation_gap, 4) if valuation_gap is not None else np.nan,
            "DCF_Valuation_Score": valuation_score,
            "DCF_Assessment": self._assessment(implied_fcf_growth, implied_terminal_growth, expected_growth),
        }

    @staticmethod
    def _empty_result(status, fcf, fcf_source, market_cap, revenue, sector=None, expected_growth=None):
        return {
            "DCF_Status": status,
            "DCF_FCF_Source": fcf_source,
            "DCF_Cash_Flow_Basis": "n/a",
            "DCF_Sector": sector if sector else "Unknown",
            "DCF_Expected_Growth": expected_growth if expected_growth is not None else np.nan,
            "DCF_Base_FCF": fcf if fcf is not None else np.nan,
            "DCF_Market_Cap": market_cap if market_cap is not None else np.nan,
            "DCF_Net_Debt": np.nan,
            "DCF_Enterprise_Value": np.nan,
            "DCF_EV_Method": "n/a",
            "DCF_FCF_Yield": np.nan,
            "DCF_Revenue_FCF_Margin": np.nan if not revenue or not fcf else fcf / revenue,
            "DCF_Years": np.nan,
            "DCF_Discount_Rate": np.nan,
            "DCF_Assumed_Growth": np.nan,
            "DCF_Assumed_Terminal_Growth": np.nan,
            "DCF_Implied_FCF_CAGR": np.nan,
            "DCF_Implied_Terminal_Growth": np.nan,
            "DCF_Base_Case_Value": np.nan,
            "DCF_Value_to_Market_Cap": np.nan,
            "DCF_Base_Case_Gap": np.nan,
            "DCF_Base_Case_Upside": np.nan,
            "DCF_Valuation_Score": 25.0,
            "DCF_Assessment": "Insufficient data",
        }

    def _unreliable_result(self, status, fcf, fcf_source, market_cap, revenue, fcf_yield, revenue_fcf_margin, sector=None, expected_growth=None, net_debt=None, enterprise_value=None, ev_method=None):
        return {
            "DCF_Status": status,
            "DCF_FCF_Source": fcf_source,
            "DCF_Cash_Flow_Basis": "operating_cash_flow_less_capex_equity_proxy",
            "DCF_Sector": sector if sector else "Unknown",
            "DCF_Expected_Growth": expected_growth if expected_growth is not None else np.nan,
            "DCF_Base_FCF": round(fcf, 2),
            "DCF_Market_Cap": round(market_cap, 2),
            "DCF_Net_Debt": round(net_debt, 2) if net_debt is not None else np.nan,
            "DCF_Enterprise_Value": round(enterprise_value, 2) if enterprise_value is not None else np.nan,
            "DCF_EV_Method": ev_method if ev_method is not None else "n/a",
            "DCF_FCF_Yield": round(fcf_yield, 4) if fcf_yield is not None else np.nan,
            "DCF_Revenue_FCF_Margin": round(revenue_fcf_margin, 4) if revenue_fcf_margin is not None else np.nan,
            "DCF_Years": int(self.config.REVERSE_DCF_FORECAST_YEARS),
            "DCF_Discount_Rate": float(self.config.REVERSE_DCF_DISCOUNT_RATE),
            "DCF_Assumed_Growth": expected_growth if expected_growth is not None else float(self.config.REVERSE_DCF_BASE_GROWTH),
            "DCF_Assumed_Terminal_Growth": float(self.config.REVERSE_DCF_TERMINAL_GROWTH),
            "DCF_Implied_FCF_CAGR": np.nan,
            "DCF_Implied_Terminal_Growth": np.nan,
            "DCF_Base_Case_Value": np.nan,
            "DCF_Value_to_Market_Cap": np.nan,
            "DCF_Base_Case_Gap": np.nan,
            "DCF_Base_Case_Upside": np.nan,
            "DCF_Valuation_Score": self._valuation_score(status, None, None, fcf_yield, expected_growth),
            "DCF_Assessment": "FCF too low",
        }

    @staticmethod
    def _assessment(implied_fcf_growth, implied_terminal_growth, expected_growth=None):
        if implied_fcf_growth is None:
            return "Very stretched"
        if implied_fcf_growth < 0:
            return "Low expectation"
        benchmark = expected_growth if expected_growth else ReverseDCFModel.DEFAULT_SECTOR_GROWTH
        ratio = implied_fcf_growth / benchmark if benchmark else None
        terminal_ok = implied_terminal_growth is not None and implied_terminal_growth <= 0.04
        if ratio is not None and ratio <= 0.80 and terminal_ok:
            return "Reasonable"
        if ratio is not None and ratio <= 1.50:
            return "Demanding"
        return "Stretched"

    @staticmethod
    def _rating_from_score(score):
        if score >= 70:
            return "STRONG BUY"
        if score >= 60:
            return "BUY"
        if score >= 50:
            return "HOLD"
        if score >= 40:
            return "REDUCE"
        return "SELL"

    def enrich(self, df):
        if df is None or df.empty or not getattr(self.config, "REVERSE_DCF_ENABLED", True):
            return df
        results = [self.analyze_row(row) for _, row in df.iterrows()]
        dcf_df = pd.DataFrame(results, index=df.index)
        enriched = pd.concat([df.copy(), dcf_df], axis=1)
        weight = self._clamp(float(getattr(self.config, "REVERSE_DCF_RANKING_WEIGHT", 0.10)), 0.0, 1.0)
        if weight > 0 and "Combined_Score" in enriched:
            enriched["Pre_DCF_Rank"] = enriched.get("Rank")
            enriched["Pre_DCF_Combined_Score"] = enriched["Combined_Score"]
            has_rating = "Rating" in enriched
            if has_rating:
                enriched["Pre_DCF_Rating"] = enriched["Rating"]
            # Only blend in the DCF valuation score where the model actually produced
            # a reliable read (DCF_Status == "OK"). Stocks the model can't cleanly value
            # (e.g. banks/NBFCs where FCF isn't a meaningful concept, or missing data)
            # would otherwise get a punitive flat 15-25 score dragging Final_Score down
            # for reasons unrelated to their actual quality - so those rows simply fall
            # back to the pure Combined_Score instead of being blended.
            dcf_ok = enriched["DCF_Status"] == "OK"
            valuation_score = enriched["DCF_Valuation_Score"].clip(0, 100)
            enriched["Final_Score"] = enriched["Combined_Score"]
            blended = (enriched["Combined_Score"] * (1 - weight) + valuation_score * weight).round(2)
            enriched.loc[dcf_ok, "Final_Score"] = blended.loc[dcf_ok]
            enriched["Final_Score"] = enriched["Final_Score"].round(2)
            if has_rating:
                # Recompute the Rating label from the DCF-blended Final_Score so the
                # displayed rating matches the actual rank order shown in reports,
                # instead of leaving it frozen at the pre-DCF Combined_Score rating.
                enriched["Rating"] = enriched["Final_Score"].apply(self._rating_from_score)
                if "Rating_Capped" in enriched:
                    enriched.loc[enriched["Rating_Capped"] == True, "Rating"] = "HOLD"
                # Keep the pre-DCF high-conviction gate intact. Without this,
                # a favorable DCF score can resurrect STRONG BUY for a flat or
                # trendless stock that StockScorer intentionally capped at BUY.
                if "Strong_Buy_Eligible" in enriched:
                    enriched.loc[
                        (enriched["Rating"] == "STRONG BUY")
                        & (enriched["Strong_Buy_Eligible"] != True),
                        "Rating",
                    ] = "BUY"
                enriched = sort_by_recommendation(enriched, "Final_Score")
            else:
                enriched = enriched.sort_values("Final_Score", ascending=False).reset_index(drop=True)
            enriched["Rank"] = range(1, len(enriched) + 1)
        ok_count = int((enriched["DCF_Status"] == "OK").sum())
        logger.info(f"Reverse DCF: {ok_count}/{len(enriched)} stocks modeled")
        return enriched
