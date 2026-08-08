"""Auditable liquidity quality gates for high-conviction recommendations."""

from __future__ import annotations

import numpy as np
import pandas as pd


class LiquidityQualityEnricher:
    """Describe execution quality and cap only the high-conviction label.

    The universe pre-filter remains deliberately permissive.  This gate does
    not remove a research candidate or change its score; it prevents a thin or
    spike-dominated stock from being presented as ``STRONG BUY``.
    """

    def __init__(self, config):
        self.config = config

    def enrich(self, scored_df):
        enriched = scored_df.copy()
        median_20d = _numeric_column(enriched, "Median_Turnover_20D_INR")
        median_60d = _numeric_column(enriched, "Median_Turnover_60D_INR")
        p10_20d = _numeric_column(enriched, "Turnover_P10_20D_INR")
        top5_share = _numeric_column(enriched, "Turnover_Top5_Share_60D")

        minimum_median = max(
            0.0,
            _number(
                getattr(
                    self.config,
                    "STRONG_BUY_MIN_MEDIAN_TURNOVER_INR",
                    5_00_00_000.0,
                ),
                5_00_00_000.0,
            ),
        )
        maximum_concentration = min(
            1.0,
            max(
                0.0,
                _number(
                    getattr(
                        self.config,
                        "STRONG_BUY_MAX_TURNOVER_TOP5_SHARE",
                        0.50,
                    ),
                    0.50,
                ),
            ),
        )
        participation_rate = min(
            1.0,
            max(
                0.0,
                _number(
                    getattr(self.config, "LIQUIDITY_POSITION_PARTICIPATION_RATE", 0.01),
                    0.01,
                ),
            ),
        )

        observed = median_20d.notna() & top5_share.notna()
        median_ok = median_20d.ge(minimum_median)
        concentration_ok = top5_share.le(maximum_concentration)
        eligible = observed & median_ok & concentration_ok

        enriched["Liquidity_20D_Median_Cr"] = (median_20d / 1_00_00_000.0).round(2)
        enriched["Liquidity_60D_Median_Cr"] = (median_60d / 1_00_00_000.0).round(2)
        enriched["Liquidity_20D_P10_Cr"] = (p10_20d / 1_00_00_000.0).round(2)
        enriched["Liquidity_Top5_Share_60D"] = top5_share.round(4)
        enriched["Liquidity_Suggested_Max_Position_INR"] = (
            median_20d * participation_rate
        ).round(0)
        enriched["Liquidity_Conviction_Eligible"] = eligible
        enriched["Liquidity_Status"] = "Liquid"
        enriched.loc[~observed, "Liquidity_Status"] = "Unknown"
        enriched.loc[observed & ~median_ok, "Liquidity_Status"] = "Thin"
        enriched.loc[
            observed & median_ok & ~concentration_ok,
            "Liquidity_Status",
        ] = "Spike-concentrated"

        reasons = pd.Series("", index=enriched.index, dtype=object)
        reasons.loc[~observed] = "robust turnover history unavailable"
        reasons.loc[observed & ~median_ok] = median_20d.loc[
            observed & ~median_ok
        ].map(
            lambda value: (
                f"20D median turnover Rs{value / 1_00_00_000:.2f}cr below "
                f"Rs{minimum_median / 1_00_00_000:.2f}cr"
            )
        )
        concentrated = observed & ~concentration_ok
        concentration_reason = top5_share.loc[concentrated].map(
            lambda value: (
                f"top 5 days are {value:.0%} of 60D turnover "
                f"(limit {maximum_concentration:.0%})"
            )
        )
        both = concentrated & reasons.ne("")
        reasons.loc[concentrated & ~both] = concentration_reason.loc[
            concentrated & ~both
        ]
        reasons.loc[both] = (
            reasons.loc[both] + "; " + concentration_reason.loc[both]
        )

        gate_enabled = bool(
            getattr(self.config, "LIQUIDITY_CONVICTION_GATE_ENABLED", True)
        )
        strong_buy = enriched.get(
            "Rating", pd.Series("", index=enriched.index, dtype=object)
        ).eq("STRONG BUY")
        capped = gate_enabled & strong_buy & ~eligible
        enriched["Liquidity_Rating_Capped"] = capped
        enriched["Liquidity_Cap_Reason"] = reasons
        if "Rating" in enriched:
            enriched.loc[capped, "Rating"] = "BUY"
        return enriched


def _numeric_column(frame, column):
    return pd.to_numeric(
        frame.get(column, pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
