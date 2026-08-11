"""Reverse-DCF evidence for the recommendation policy.

This module deliberately stops at evidence.  It does not blend the evidence
into a final score, assign a rating, or rank rows; those policy decisions live
in :mod:`screener.recommendation`.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math

import numpy as np
import pandas as pd

from .numeric import round_half_up


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateSolve:
    """Result of solving a monotonic valuation function for a rate.

    A rate outside the configured model interval is represented as a censored
    bound, not as an exact value at that bound.
    """

    state: str
    point: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None


class ReverseDCFModel:
    """Build transparent reverse-DCF evidence for each stock."""

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
    DEFAULT_SECTOR_GROWTH = 0.15
    EXPECTED_GROWTH_FLOOR = 0.05
    EXPECTED_GROWTH_CAP = 0.25
    UNSUPPORTED_DCF_SECTORS = {"Financial Services", "Real Estate"}

    def __init__(self, config):
        self.config = config

    def _size_adjustment(self, market_cap):
        if market_cap is None or market_cap <= 0:
            return 0.0
        market_cap_cr = market_cap / 1e7
        if market_cap_cr >= 200_000:
            return -0.03
        if market_cap_cr >= 20_000:
            return -0.015
        if market_cap_cr >= 5_000:
            return 0.0
        return 0.02

    def _expected_growth(self, sector, market_cap):
        base = self.SECTOR_GROWTH_BENCHMARKS.get(
            sector, self.DEFAULT_SECTOR_GROWTH
        )
        adjusted = base + self._size_adjustment(market_cap)
        return round(
            max(self.EXPECTED_GROWTH_FLOOR, min(adjusted, self.EXPECTED_GROWTH_CAP)),
            4,
        )

    @staticmethod
    def _safe_float(value, default=None):
        try:
            if value is None or pd.isna(value):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _dcf_value(base_fcf, growth_rate, terminal_growth, discount_rate, years):
        if (
            base_fcf is None
            or base_fcf <= 0
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
        terminal_value = fcf * (1 + terminal_growth) / (
            discount_rate - terminal_growth
        )
        return value + terminal_value / ((1 + discount_rate) ** years)

    def _solve_rate(self, target_value, value_func, low, high):
        """Solve inside ``[low, high]`` or return a symmetric censored bound."""

        if target_value is None or target_value <= 0 or high <= low:
            return RateSolve("invalid")
        low_value = value_func(low)
        high_value = value_func(high)
        if (
            low_value is None
            or high_value is None
            or not np.isfinite(low_value)
            or not np.isfinite(high_value)
            or high_value < low_value
        ):
            return RateSolve("invalid")
        if target_value < low_value and not math.isclose(
            target_value, low_value, rel_tol=1e-12, abs_tol=1e-12
        ):
            return RateSolve("below_range", upper_bound=float(low))
        if target_value > high_value and not math.isclose(
            target_value, high_value, rel_tol=1e-12, abs_tol=1e-12
        ):
            return RateSolve("above_range", lower_bound=float(high))

        left, right = float(low), float(high)
        for _ in range(80):
            mid = (left + right) / 2
            mid_value = value_func(mid)
            if mid_value is None or not np.isfinite(mid_value):
                return RateSolve("invalid")
            if mid_value < target_value:
                left = mid
            else:
                right = mid
        point = (left + right) / 2
        return RateSolve(
            "within_range",
            point=point,
            lower_bound=point,
            upper_bound=point,
        )

    def _valuation_score(self, value_to_market):
        """Smooth, non-duplicative score from one valuation relationship.

        A ratio of one is neutral (50). Reciprocal ratios receive symmetric
        scores around 50.  ``tanh`` avoids hard buckets while bounding the
        result without awarding exact 0/100 for finite inputs.
        """

        if value_to_market is None or value_to_market <= 0:
            return None
        scale = self._safe_float(
            getattr(self.config, "REVERSE_DCF_SCORE_LOG_SCALE", 1.0), 1.0
        )
        if scale is None or scale <= 0:
            scale = 1.0
        score = 50.0 + 50.0 * math.tanh(math.log(value_to_market) / scale)
        # Keep finite evidence away from exact endpoints after rounding; 0 and
        # 100 would imply certainty and recreate the old score saturation.
        return round_half_up(max(0.01, min(99.99, score)), 2)

    def _signal_direction(self, value_to_market):
        if value_to_market is None or value_to_market <= 0:
            return "unknown"
        band = self._safe_float(
            getattr(self.config, "REVERSE_DCF_NEUTRAL_LOG_BAND", 0.05), 0.05
        )
        band = max(0.0, band or 0.0)
        log_ratio = math.log(value_to_market)
        if log_ratio > band:
            return "favorable"
        if log_ratio < -band:
            return "adverse"
        return "neutral"

    @staticmethod
    def _solve_columns(prefix, solve):
        return {
            f"{prefix}_Solve_State": solve.state,
            f"{prefix}": (
                round(solve.point, 4) if solve.point is not None else np.nan
            ),
            f"{prefix}_Lower_Bound": (
                round(solve.lower_bound, 4)
                if solve.lower_bound is not None
                else np.nan
            ),
            f"{prefix}_Upper_Bound": (
                round(solve.upper_bound, 4)
                if solve.upper_bound is not None
                else np.nan
            ),
        }

    def analyze_row(self, row):
        safe = self._safe_float
        market_cap = safe(row.get("Market_Cap"))
        revenue = safe(row.get("Total_Revenue"))
        reported_fcf = safe(row.get("Free_CashFlow"))
        total_debt = safe(row.get("Total_Debt"))
        total_cash = safe(row.get("Total_Cash"))
        sector = row.get("Sector")
        sector = sector.strip() if isinstance(sector, str) and sector.strip() else None
        expected_growth = self._expected_growth(sector, market_cap)
        supported = sector not in self.UNSUPPORTED_DCF_SECTORS

        if reported_fcf is not None and reported_fcf > 0:
            fcf = reported_fcf
            source_type = "reported"
            legacy_fcf_source = "reported"
        elif reported_fcf is not None:
            # A reported financing deficit is observed evidence, not a missing
            # field. Do not silently replace it with a fixed revenue margin;
            # a defensible valuation would need an explicit normalization and
            # transition model that this screener does not yet have.
            fcf = reported_fcf
            source_type = "observed_negative"
            legacy_fcf_source = "reported_nonpositive"
        elif revenue is not None and revenue > 0:
            fcf = revenue * float(self.config.REVERSE_DCF_FCF_MARGIN_FALLBACK)
            source_type = "estimated"
            legacy_fcf_source = "revenue_margin_fallback"
        else:
            fcf = reported_fcf
            source_type = "missing"
            legacy_fcf_source = "reported"

        if total_debt is not None and total_debt >= 0 and total_cash is not None and total_cash >= 0:
            net_debt = total_debt - total_cash
        else:
            net_debt = None
        enterprise_value = (
            market_cap + net_debt
            if market_cap is not None and net_debt is not None
            else None
        )

        years = int(self.config.REVERSE_DCF_FORECAST_YEARS)
        discount_rate = float(self.config.REVERSE_DCF_DISCOUNT_RATE)
        fixed_terminal_growth = float(self.config.REVERSE_DCF_TERMINAL_GROWTH)
        max_terminal_growth = min(
            float(self.config.REVERSE_DCF_MAX_TERMINAL_GROWTH),
            discount_rate - 0.001,
        )
        can_model = bool(
            supported
            and market_cap is not None
            and market_cap > 0
            and fcf is not None
            and fcf > 0
        )

        if can_model:
            fcf_solve = self._solve_rate(
                market_cap,
                lambda growth: self._dcf_value(
                    fcf, growth, fixed_terminal_growth, discount_rate, years
                ),
                float(self.config.REVERSE_DCF_MIN_GROWTH),
                float(self.config.REVERSE_DCF_MAX_GROWTH),
            )
            terminal_solve = self._solve_rate(
                market_cap,
                lambda terminal: self._dcf_value(
                    fcf, expected_growth, terminal, discount_rate, years
                ),
                float(self.config.REVERSE_DCF_MIN_TERMINAL_GROWTH),
                max_terminal_growth,
            )
            base_case_value = self._dcf_value(
                fcf,
                expected_growth,
                fixed_terminal_growth,
                discount_rate,
                years,
            )
        else:
            fcf_solve = RateSolve("not_applicable")
            terminal_solve = RateSolve("not_applicable")
            base_case_value = None

        value_to_market = (
            base_case_value / market_cap
            if base_case_value is not None and market_cap is not None and market_cap > 0
            else None
        )
        valuation_gap = value_to_market - 1 if value_to_market is not None else None
        fcf_yield = (
            fcf / market_cap
            if fcf is not None and market_cap is not None and market_cap > 0
            else None
        )
        revenue_fcf_margin = (
            fcf / revenue
            if fcf is not None and revenue is not None and revenue > 0
            else None
        )
        direction = self._signal_direction(value_to_market)
        blend_eligible = bool(
            can_model
            and source_type == "reported"
            and value_to_market is not None
            and direction in {"favorable", "neutral", "adverse"}
        )
        configured_weight = max(
            0.0,
            min(
                1.0,
                float(getattr(self.config, "REVERSE_DCF_RANKING_WEIGHT", 0.10)),
            ),
        )
        score = self._valuation_score(value_to_market) if blend_eligible else 50.0

        min_valid_yield = float(
            getattr(self.config, "REVERSE_DCF_MIN_VALID_FCF_YIELD", 0.005)
        )
        if not supported:
            status = "sector_not_supported"
            reliability = "unsupported"
            blend_reason = "sector requires a dedicated valuation model"
        elif market_cap is None or market_cap <= 0:
            status = "missing_market_cap"
            reliability = "unavailable"
            blend_reason = "market capitalization unavailable"
        elif source_type == "observed_negative":
            status = "negative_fcf"
            reliability = "reported_unmodeled"
            blend_reason = (
                "reported non-positive cash flow requires an explicit "
                "normalization model"
            )
        elif source_type == "missing":
            status = "missing_or_negative_fcf"
            reliability = "unavailable"
            blend_reason = "positive cash flow unavailable"
        elif source_type == "estimated":
            status = "estimated_fcf"
            reliability = "estimated"
            blend_reason = "estimated cash flow is audit-only"
        elif fcf_solve.state not in {
            "within_range",
            "below_range",
            "above_range",
        }:
            status = "solve_unavailable"
            reliability = "unavailable"
            blend_eligible = False
            score = 50.0
            blend_reason = "valuation solve unavailable"
        elif fcf_yield is not None and fcf_yield < min_valid_yield:
            status = "low_fcf_yield"
            reliability = "reported"
            blend_reason = "reliable reported adverse evidence"
        elif fcf_solve.state == "above_range":
            status = "growth_above_model_range"
            reliability = "reported"
            blend_reason = "reliable reported censored evidence"
        elif fcf_solve.state == "below_range":
            status = "growth_below_model_range"
            reliability = "reported"
            blend_reason = "reliable reported censored evidence"
        elif fcf_solve.state == "within_range":
            status = "OK"
            reliability = "reported"
            blend_reason = "reliable reported evidence"

        result = {
            # Backward-compatible audit fields.
            "DCF_Status": status,
            "DCF_FCF_Source": legacy_fcf_source,
            "DCF_Cash_Flow_Basis": "operating_cash_flow_less_capex_equity_proxy" if can_model else "n/a",
            "DCF_Sector": sector if sector else "Unknown",
            "DCF_Expected_Growth": expected_growth,
            "DCF_Base_FCF": round(fcf, 2) if fcf is not None else np.nan,
            "DCF_Market_Cap": round(market_cap, 2) if market_cap is not None else np.nan,
            "DCF_Net_Debt": round(net_debt, 2) if net_debt is not None else np.nan,
            "DCF_Enterprise_Value": round(enterprise_value, 2) if enterprise_value is not None else np.nan,
            "DCF_EV_Method": "equity_value_proxy" if can_model else "n/a",
            "DCF_FCF_Yield": round(fcf_yield, 4) if fcf_yield is not None else np.nan,
            "DCF_Revenue_FCF_Margin": round(revenue_fcf_margin, 4) if revenue_fcf_margin is not None else np.nan,
            "DCF_Years": years if can_model else np.nan,
            "DCF_Discount_Rate": discount_rate if can_model else np.nan,
            "DCF_Assumed_Growth": expected_growth if can_model else np.nan,
            "DCF_Assumed_Terminal_Growth": fixed_terminal_growth if can_model else np.nan,
            "DCF_Base_Case_Value": round(base_case_value, 2) if base_case_value is not None else np.nan,
            "DCF_Value_to_Market_Cap": round(value_to_market, 4) if value_to_market is not None else np.nan,
            "DCF_Base_Case_Gap": round(valuation_gap, 4) if valuation_gap is not None else np.nan,
            "DCF_Base_Case_Upside": round(valuation_gap, 4) if valuation_gap is not None else np.nan,
            "DCF_Valuation_Score": score,
            "DCF_Assessment": direction.title() if direction != "unknown" else "Insufficient data",
            # Orthogonal evidence contract.
            "DCF_Source_Type": source_type,
            "DCF_Reliability": reliability,
            "DCF_Signal_Direction": direction,
            "DCF_Blend_Eligible": blend_eligible,
            "DCF_Blend_Weight": configured_weight if blend_eligible else 0.0,
            "DCF_Blend_Reason": blend_reason,
            "DCF_Review_Required": source_type == "observed_negative",
            "DCF_Cash_Flow_Quality": (
                "reported_positive"
                if source_type == "reported"
                else "reported_nonpositive"
                if source_type == "observed_negative"
                else source_type
            ),
        }
        result.update(self._solve_columns("DCF_Implied_FCF_CAGR", fcf_solve))
        result.update(
            self._solve_columns("DCF_Implied_Terminal_Growth", terminal_solve)
        )
        # A short generic alias is convenient for consumers that do not care
        # which diagnostic solve supplied the state.
        result["DCF_Solve_State"] = fcf_solve.state
        return result

    @staticmethod
    def _rating_from_score(score):
        """Deprecated compatibility helper; final ratings live elsewhere."""

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
        """Attach DCF evidence without changing score, rating, order, or rank."""

        if df is None or df.empty or not getattr(
            self.config, "REVERSE_DCF_ENABLED", True
        ):
            return df
        results = [self.analyze_row(row) for _, row in df.iterrows()]
        dcf_df = pd.DataFrame(results, index=df.index)
        base = df.copy()
        # Re-enrichment replaces evidence rather than creating duplicate-named
        # columns, which keeps retries and notebook audits deterministic.
        existing_evidence = [column for column in dcf_df if column in base]
        if existing_evidence:
            base = base.drop(columns=existing_evidence)
        enriched = pd.concat([base, dcf_df], axis=1)

        # Retain legacy pre-DCF aliases while sourcing them from explicitly
        # provisional Core_* diagnostics, never canonical decision columns.
        if "Combined_Score" in enriched:
            enriched["Pre_DCF_Combined_Score"] = enriched["Combined_Score"]
        if "Core_Rating" in enriched:
            enriched["Pre_DCF_Rating"] = enriched["Core_Rating"]
        elif "Rating" in enriched:
            enriched["Pre_DCF_Rating"] = enriched["Rating"]
        if "Core_Score_Rank" in enriched:
            enriched["Pre_DCF_Rank"] = enriched["Core_Score_Rank"]
        elif "Rank" in enriched:
            enriched["Pre_DCF_Rank"] = enriched["Rank"]

        eligible_count = int(enriched["DCF_Blend_Eligible"].fillna(False).sum())
        logger.info(
            "Reverse DCF evidence: %s/%s stocks eligible for policy blending",
            eligible_count,
            len(enriched),
        )
        return enriched
