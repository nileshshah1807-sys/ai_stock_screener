"""Model 5.0 factor blocks: quality, growth, value, momentum, risk.

The 4.x core score merges value, profitability, balance-sheet strength, growth
and accounting stability into one undifferentiated fundamental number, then adds
a ten-component technical score whose members largely re-describe the same
recent price path. This module replaces both with five economically separable
blocks, each a coverage-shrunk percentile composite of its own inputs.

Design rules this module enforces:

* **Rank, don't threshold.** Every input is scored by its cross-sectional
  percentile rather than a hand-set ladder, so a PE of 18 is judged against the
  companies actually being scored today instead of a universal bar.
* **Sector-neutral by default.** A utility and a software company do not share a
  normal ROIC, growth rate or earnings yield. Ranking inside the sector keeps a
  sector bet from masquerading as stock selection.
* **Absence lowers confidence, never asserts the worst.** An unobserved input
  leaves both the numerator and the denominator; the block is then shrunk toward
  neutral 50 by its own coverage.
* **No block publishes a rating.** This module only produces evidence.
  ``RecommendationPolicy`` remains the sole writer of the canonical decision.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .numeric import round_half_up

logger = logging.getLogger(__name__)

FINANCIAL_MODELS = {
    "Bank Equity Quality Model",
    "NBFC Equity Quality Model",
    "Capital Markets Earnings Quality Model",
    "Insurance Equity Quality Model",
    "Financial Services Data-Limited Model",
}
# Sectors where book value is a meaningful valuation anchor. Applying a book
# yield to an asset-light services company rewards accounting history rather
# than economics, so the input is simply not offered there.
BOOK_YIELD_SECTORS = {"FINANCIAL SERVICES", "REAL ESTATE", "UTILITIES"}

# (column, weight, higher_is_better)
QUALITY_GENERIC = (
    ("ROIC", 0.20, True),
    ("Gross_Profit_To_Assets", 0.15, True),
    ("OCF_To_Assets", 0.13, True),
    ("FCF_To_Assets", 0.09, True),
    ("Accruals_To_Assets", 0.10, False),
    ("Interest_Coverage", 0.05, True),
    ("Net_Debt_To_EBITDA", 0.05, False),
    ("Operating_Margin_Stability", 0.08, False),
    ("Earnings_Stability", 0.08, False),
    ("Asset_Growth_1Y", 0.04, False),
    ("Share_Dilution_3Y", 0.03, False),
)
# Financials are scored on what their statements actually report. EBIT, gross
# profit, current assets and (for banks) operating cash flow are absent by
# construction, so an industrial-company template would score them as missing
# rather than as different.
QUALITY_FINANCIAL = (
    ("ROE_Statement", 0.28, True),
    ("ROA_Statement", 0.22, True),
    ("Equity_To_Assets", 0.20, True),
    ("Earnings_Stability", 0.15, False),
    ("Profit_Margin", 0.15, True),
)
GROWTH_FEATURES = (
    ("Revenue_CAGR_3Y", 0.25, True),
    ("EPS_CAGR_3Y", 0.20, True),
    ("Revenue_Acceleration", 0.15, True),
    ("EPS_Acceleration", 0.15, True),
    ("Margin_Direction", 0.15, True),
    # The proposal asks for forward/guidance evidence. No point-in-time
    # consensus feed is wired in, and approximating one would be a look-ahead
    # hazard, so the defensible substitute is the cash confirmation the same
    # proposal requires for high reported earnings growth.
    ("Cash_Conversion", 0.10, True),
)
VALUE_FEATURES = (
    ("Earnings_Yield", 0.25, True),
    ("FCF_Yield", 0.25, True),
    ("EBIT_To_EV", 0.20, True),
    ("Book_Yield", 0.15, True),
    ("DCF_Valuation_Score", 0.15, True),
)
MOMENTUM_FEATURES = (
    ("RiskAdj_Momentum_12_1", 0.30, True),
    ("RiskAdj_Momentum_6_1", 0.25, True),
    ("RS_Sector_6M_Pct", 0.20, True),
    ("RS_Market_6M_Pct", 0.15, True),
    ("Trend_Quality_R2", 0.10, True),
)
RISK_FEATURES = (
    ("Volatility_Ann_Pct", 0.25, False),
    # Drawdown is stored as a negative percentage, so a shallower drawdown is
    # the larger number and higher genuinely is better here.
    ("Max_Drawdown_1Y_Pct", 0.20, True),
    ("Trading_Frequency_60D", 0.20, True),
    ("Downside_Deviation_Pct", 0.15, False),
    ("Gap_Risk_Pct", 0.10, False),
    ("Return_Concentration_1Y", 0.10, False),
)

BLOCKS = {
    "Quality": None,  # resolved per row: generic or financial
    "Growth": GROWTH_FEATURES,
    "Value": VALUE_FEATURES,
    "Momentum": MOMENTUM_FEATURES,
    "Risk": RISK_FEATURES,
}


def _as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _numeric(frame, column):
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def cross_sectional_percentile(
    values, groups=None, *, higher_is_better=True, min_group=8
):
    """Percentile-rank ``values`` on [0, 100], inside ``groups`` where possible.

    Uses the symmetric ``(rank - 1) / (n - 1)`` transform so the best and worst
    observations map to the full range. pandas' ``rank(pct=True)`` maps onto
    ``[1/n, 1]``, which denies the best value full credit and biases every
    lower-is-better metric once inverted.

    A group too small to be a distribution falls back to the market-wide
    ranking, which is a weaker but honest comparison; it is never dropped.
    """
    values = pd.to_numeric(pd.Series(values), errors="coerce")

    def rank_within(series):
        count = series.notna().sum()
        if count < 2:
            # A single observation has no percentile. Neutral is the only
            # defensible reading; it also cannot win a ranking by itself.
            return pd.Series(
                np.where(series.notna(), 50.0, np.nan), index=series.index
            )
        raw = series.rank(method="average")
        pct = (raw - 1.0) / (count - 1.0)
        if not higher_is_better:
            pct = 1.0 - pct
        return pct * 100.0

    market = rank_within(values)
    if groups is None:
        return market

    groups = pd.Series(groups, index=values.index).fillna("Unknown").astype(str)
    sizes = values.groupby(groups).transform("count")
    sector = values.groupby(groups).transform(rank_within)
    usable = sizes >= int(min_group)
    return sector.where(usable, market)


def _block_score(frame, features, groups, *, min_group, min_coverage):
    """Coverage-shrunk weighted percentile composite for one factor block."""
    total_weight = float(sum(weight for _, weight, _ in features)) or 1.0
    weighted_sum = pd.Series(0.0, index=frame.index)
    observed_weight = pd.Series(0.0, index=frame.index)
    percentiles = {}

    for column, weight, higher_is_better in features:
        values = _numeric(frame, column)
        if values.notna().sum() == 0:
            percentiles[column] = values
            continue
        pct = cross_sectional_percentile(
            values,
            groups,
            higher_is_better=higher_is_better,
            min_group=min_group,
        )
        percentiles[column] = pct
        present = pct.notna()
        weighted_sum = weighted_sum.add(pct.fillna(0.0) * weight, fill_value=0.0)
        observed_weight = observed_weight.add(
            present.astype(float) * weight, fill_value=0.0
        )

    coverage = observed_weight / total_weight
    observed_score = (weighted_sum / observed_weight.where(observed_weight > 0))
    observed_score = observed_score.fillna(50.0)
    # Identical in spirit to the technical/fundamental shrinkage already used by
    # the 4.x scorer: partial evidence moves proportionally away from neutral
    # instead of asserting a confident score built from one input.
    score = (50.0 + coverage * (observed_score - 50.0)).clip(0.0, 100.0)
    sufficient = coverage >= float(min_coverage)
    return score, coverage, sufficient, percentiles


class FactorModel:
    """Compute Model 5.0 factor blocks and the blended research score."""

    def __init__(self, config):
        self.config = config

    # -- derived inputs ---------------------------------------------------
    def _derive_inputs(self, frame, market_context):
        """Build the ratio inputs the blocks rank. Never mutates the caller."""
        frame = frame.copy()
        price = _numeric(frame, "Current_Price")
        market_cap = _numeric(frame, "Market_Cap")

        eps = _numeric(frame, "EPS")
        frame["Earnings_Yield"] = (eps / price.where(price > 0)).replace(
            [np.inf, -np.inf], np.nan
        )
        fcf = _numeric(frame, "Free_CashFlow")
        frame["FCF_Yield"] = (
            fcf / market_cap.where(market_cap > 0)
        ).replace([np.inf, -np.inf], np.nan)

        # EV/EBIT is the preferred capital-structure-neutral multiple; EV/EBITDA
        # is the fallback where depreciation is not separable. Expressed as a
        # yield so that, like every other value input, higher is better.
        enterprise_value = (
            market_cap + _numeric(frame, "Total_Debt") - _numeric(frame, "Total_Cash")
        )
        ebit = _numeric(frame, "EBIT_Latest")
        ebit_to_ev = ebit / enterprise_value.where(enterprise_value > 0)
        ev_ebitda = _numeric(frame, "EV_EBITDA")
        ebitda_yield = (1.0 / ev_ebitda.where(ev_ebitda > 0)).replace(
            [np.inf, -np.inf], np.nan
        )
        frame["EBIT_To_EV"] = ebit_to_ev.replace(
            [np.inf, -np.inf], np.nan
        ).fillna(ebitda_yield)

        sector = (
            frame.get("Sector", pd.Series("", index=frame.index))
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )
        book_yield = _numeric(frame, "Book_Value") / price.where(price > 0)
        frame["Book_Yield"] = book_yield.where(
            sector.isin(BOOK_YIELD_SECTORS)
        ).replace([np.inf, -np.inf], np.nan)

        # --- momentum ----------------------------------------------------
        volatility = _numeric(frame, "Volatility_Ann_Pct")
        safe_volatility = volatility.where(volatility > 1.0)
        for horizon in ("12_1", "6_1"):
            raw = _numeric(frame, f"Momentum_{horizon}_Pct")
            frame[f"RiskAdj_Momentum_{horizon}"] = (
                raw / safe_volatility
            ).replace([np.inf, -np.inf], np.nan)

        return_6m = _numeric(frame, "Pct_Change_6M")
        return_12m = _numeric(frame, "Pct_Change_12M")
        benchmark_6m = float(
            (market_context or {}).get("Benchmark_Return_6M_Pct", np.nan) or np.nan
        )
        benchmark_12m = float(
            (market_context or {}).get("Benchmark_Return_12M_Pct", np.nan) or np.nan
        )
        frame["RS_Market_6M_Pct"] = return_6m - benchmark_6m
        frame["RS_Market_12M_Pct"] = return_12m - benchmark_12m
        # Sector-relative strength uses the median so one runaway constituent
        # cannot define its whole sector's baseline.
        sector_median_6m = return_6m.groupby(sector).transform("median")
        sector_count = return_6m.groupby(sector).transform("count")
        min_peers = int(getattr(self.config, "FACTOR_MIN_SECTOR_PEERS", 8))
        frame["RS_Sector_6M_Pct"] = (return_6m - sector_median_6m).where(
            (sector_count >= min_peers) & sector.ne("")
        )
        return frame

    # -- public API -------------------------------------------------------
    def score(self, frame, market_context=None):
        """Attach factor blocks, percentiles and ``Research_Score``."""
        if frame is None or len(frame) == 0:
            return frame

        working = self._derive_inputs(frame, market_context)
        sector_neutral = bool(getattr(self.config, "FACTOR_SECTOR_NEUTRAL", True))
        sector = (
            working.get("Sector", pd.Series("", index=working.index))
            .fillna("Unknown")
            .astype(str)
            .str.strip()
            .replace("", "Unknown")
        )
        groups = sector if sector_neutral else None
        min_group = int(getattr(self.config, "FACTOR_MIN_SECTOR_PEERS", 8))
        min_coverage = float(getattr(self.config, "FACTOR_MIN_BLOCK_COVERAGE", 0.50))

        # Quality is scored on two templates. Splitting the frame keeps each
        # population ranked against companies whose statements mean the same
        # thing, instead of ranking a bank's absent EBIT against a manufacturer's.
        model = (
            working.get("Fundamental_Model", pd.Series("", index=working.index))
            .fillna("")
            .astype(str)
        )
        is_financial = model.isin(FINANCIAL_MODELS)
        quality = pd.Series(np.nan, index=working.index, dtype=float)
        quality_coverage = pd.Series(0.0, index=working.index, dtype=float)
        quality_sufficient = pd.Series(False, index=working.index, dtype=bool)
        for mask, features, label in (
            (~is_financial, QUALITY_GENERIC, "generic"),
            (is_financial, QUALITY_FINANCIAL, "financial"),
        ):
            if not mask.any():
                continue
            subset = working.loc[mask]
            score, coverage, sufficient, _ = _block_score(
                subset,
                features,
                groups.loc[mask] if groups is not None else None,
                min_group=min_group,
                min_coverage=min_coverage,
            )
            quality.loc[mask] = score
            quality_coverage.loc[mask] = coverage
            quality_sufficient.loc[mask] = sufficient
            logger.info(
                "Quality block (%s template): %d rows, mean coverage %.2f",
                label,
                int(mask.sum()),
                float(coverage.mean()),
            )
        working["Quality_Score"] = quality
        working["Quality_Coverage"] = quality_coverage
        working["Quality_Coverage_Sufficient"] = quality_sufficient

        for name, features in (
            ("Growth", GROWTH_FEATURES),
            ("Value", VALUE_FEATURES),
            ("Momentum", MOMENTUM_FEATURES),
            ("Risk", RISK_FEATURES),
        ):
            score, coverage, sufficient, _ = _block_score(
                working,
                features,
                groups if name != "Momentum" else None,
                min_group=min_group,
                min_coverage=min_coverage,
            )
            working[f"{name}_Score"] = score
            working[f"{name}_Coverage"] = coverage
            working[f"{name}_Coverage_Sufficient"] = sufficient

        # --- value trap guard ------------------------------------------
        # A cheap multiple on a bottom-decile business is the classic value
        # trap. Cap the contribution rather than deleting the evidence, and
        # record that the cap fired so the export explains the difference.
        quality_percentile = cross_sectional_percentile(
            working["Quality_Score"], None, higher_is_better=True
        )
        working["Quality_Percentile"] = round_series(quality_percentile, 2)
        floor = float(getattr(self.config, "FACTOR_VALUE_QUALITY_FLOOR_PCT", 30.0))
        ceiling = float(
            getattr(self.config, "FACTOR_VALUE_CEILING_WHEN_LOW_QUALITY", 50.0)
        )
        low_quality = quality_percentile.notna() & quality_percentile.lt(floor)
        capped = low_quality & working["Value_Score"].gt(ceiling)
        working["Value_Score_Uncapped"] = round_series(working["Value_Score"], 2)
        working.loc[capped, "Value_Score"] = ceiling
        working["Value_Quality_Cap_Applied"] = capped

        # --- blend -------------------------------------------------------
        weights = {
            "Quality": float(getattr(self.config, "FACTOR_WEIGHT_QUALITY", 0.35)),
            "Growth": float(getattr(self.config, "FACTOR_WEIGHT_GROWTH", 0.20)),
            "Value": float(getattr(self.config, "FACTOR_WEIGHT_VALUE", 0.15)),
            "Momentum": float(getattr(self.config, "FACTOR_WEIGHT_MOMENTUM", 0.25)),
            "Risk": float(getattr(self.config, "FACTOR_WEIGHT_RISK", 0.05)),
        }
        total = sum(weights.values()) or 1.0
        research = pd.Series(0.0, index=working.index)
        for name, weight in weights.items():
            research = research + working[f"{name}_Score"].fillna(50.0) * (
                weight / total
            )
        working["Research_Score_Raw"] = round_series(research.clip(0.0, 100.0), 2)

        # Re-rank the blend onto a percentile before publishing it.
        #
        # Each block is already a percentile, so each is roughly uniform on
        # [0, 100]. Averaging five of them is a diversifying operation: the
        # composite collapses toward 50 (measured std ~10 against ~14-23 for the
        # individual blocks). The 70/60/50/40 rating bands were calibrated for
        # the 4.x absolute-threshold score, so applied to the raw blend they
        # make STRONG BUY almost unreachable -- one name in a 39-stock large-cap
        # universe cleared 70, and none was rated BUY.
        #
        # Ranking the blend restores the bands' meaning: >=70 is the top 30% of
        # the cross-section, >=60 the top 40%. The consequence is that Model 5.0
        # ratings are explicitly RELATIVE. What stops "top 30% of a collapsing
        # market" from being published as STRONG BUY is not the score -- it is
        # the regime overlay and the hard trend/quality/liquidity gates, which
        # are absolute and fail closed.
        if _as_bool(getattr(self.config, "FACTOR_SCORE_AS_PERCENTILE", True)):
            working["Research_Score"] = round_series(
                cross_sectional_percentile(
                    working["Research_Score_Raw"], None, higher_is_better=True
                ),
                2,
            )
            working["Research_Score_Basis"] = "cross_sectional_percentile"
        else:
            working["Research_Score"] = working["Research_Score_Raw"]
            working["Research_Score_Basis"] = "weighted_block_average"
        for name, weight in weights.items():
            working[f"{name}_Weight"] = round(weight / total, 6)
            working[f"{name}_Score"] = round_series(working[f"{name}_Score"], 2)
            working[f"{name}_Coverage"] = round_series(working[f"{name}_Coverage"], 4)
            # Percentile of the block itself, which the STRONG BUY gates use.
            working[f"{name}_Percentile"] = round_series(
                cross_sectional_percentile(
                    working[f"{name}_Score"], None, higher_is_better=True
                ),
                2,
            )

        # The factor model replaces the 4.x core score for downstream stages.
        working["Factor_Model_Applied"] = True
        working["Combined_Score"] = working["Research_Score"]
        working["Core_Score"] = working["Research_Score"]
        # Reverse-DCF evidence is already a weighted input to the Value block.
        # The finalizer would otherwise apply it a second time as a centered
        # adjustment, counting the same valuation signal twice. Zero the blend
        # weight rather than clearing the eligibility flag, so the DCF audit
        # columns stay intact in the export.
        working["DCF_Blend_Weight"] = 0.0
        working["DCF_In_Value_Block"] = True
        # Overall factor coverage drives the data-limited diagnostics.
        coverage_columns = [f"{name}_Coverage" for name in weights]
        working["Factor_Coverage"] = round_series(
            working[coverage_columns].mean(axis=1), 4
        )
        logger.info(
            "Factor model scored %d rows (mean research score %.2f, mean coverage %.2f)",
            len(working),
            float(working["Research_Score"].mean()),
            float(working["Factor_Coverage"].mean()),
        )
        return working


def round_series(series, digits):
    """Half-up rounding for a float series, preserving explicit missing values."""
    values = pd.to_numeric(series, errors="coerce")
    return values.map(
        lambda value: round_half_up(value, digits) if pd.notna(value) else np.nan
    )
