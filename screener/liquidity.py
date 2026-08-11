"""Exchange-backed liquidity and portfolio-sized execution evidence."""

from __future__ import annotations

import io
import logging
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests


logger = logging.getLogger(__name__)

NSE_MONTHLY_REPORTS_URL = "https://www.nseindia.com/api/monthly-reports?key=CM"
NSE_REPORT_REFERER = "https://www.nseindia.com/all-reports"
NSE_IMPACT_COST_FILE_KEY = "CM_SECURITY_CATEGORY_IMPACT_COST"
NSE_IMPACT_COST_REFERENCE_ORDER_INR = 1_00_000.0


class NSELiquidityProvider:
    """Join NSE's monthly security category and mean impact-cost file once.

    NSE/SEBI category I is based on at least 80% six-month trading frequency
    and mean impact cost no greater than 1% for a Rs1 lakh order. The exchange
    file is stronger execution evidence than a daily-turnover heuristic. A
    local cache keeps the daily scan to zero network calls in most runs.
    """

    CACHE_FILE = "nse_liquidity_categories.csv"

    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests

    def enrich(self, frame):
        source = frame.copy()
        if not bool(getattr(self.config, "NSE_LIQUIDITY_ENABLED", True)):
            return self._empty_columns(source, "Disabled")

        categories = self._load_categories()
        if categories.empty:
            return self._empty_columns(source, "Unavailable")

        official_columns = [
            "NSE_Liquidity_Category",
            "NSE_Impact_Cost_Pct",
            "NSE_Liquidity_Group",
            "NSE_Liquidity_As_Of",
            "NSE_Liquidity_Source_Status",
            "NSE_Liquidity_Source_URL",
        ]
        source = source.drop(columns=[c for c in official_columns if c in source], errors="ignore")
        merged = source.merge(categories, on="Symbol", how="left", validate="many_to_one")
        missing = merged["NSE_Liquidity_Category"].isna()
        merged.loc[missing, "NSE_Liquidity_Group"] = "Unavailable"
        merged.loc[missing, "NSE_Liquidity_Source_Status"] = "No EQ category"
        logger.info(
            "NSE liquidity evidence joined: %d/%d EQ symbol(s), %d Group I",
            int((~missing).sum()),
            len(merged),
            int(pd.to_numeric(merged["NSE_Liquidity_Category"], errors="coerce").eq(1).sum()),
        )
        return merged

    def _cache_path(self):
        return Path(getattr(self.config, "OUTPUT_DIR", "reports_advanced")) / self.CACHE_FILE

    def _load_categories(self):
        cache_path = self._cache_path()
        max_age_days = max(
            1.0,
            _number(getattr(self.config, "NSE_LIQUIDITY_CACHE_MAX_AGE_DAYS", 35), 35),
        )
        cached = self._read_cache(cache_path)
        cache_fresh = (
            cache_path.exists()
            and (time.time() - cache_path.stat().st_mtime) / 86400 <= max_age_days
        )
        if cache_fresh and not cached.empty:
            return cached

        try:
            fetched = self._fetch_categories()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            fetched.to_csv(cache_path, index=False)
            return fetched
        except Exception as exc:
            if not cached.empty:
                logger.warning("NSE liquidity refresh failed; using stale cache: %s", exc)
                cached["NSE_Liquidity_Source_Status"] = "Stale cache"
                return cached
            logger.warning("NSE liquidity evidence unavailable: %s", exc)
            return pd.DataFrame()

    @staticmethod
    def _read_cache(path):
        try:
            cached = pd.read_csv(path)
            required = {
                "Symbol",
                "NSE_Liquidity_Category",
                "NSE_Impact_Cost_Pct",
                "NSE_Liquidity_Group",
                "NSE_Liquidity_As_Of",
                "NSE_Liquidity_Source_Status",
                "NSE_Liquidity_Source_URL",
            }
            return cached if required.issubset(cached.columns) else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    def _fetch_categories(self):
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": NSE_REPORT_REFERER,
        }
        timeout = max(5, int(getattr(self.config, "NSE_LIQUIDITY_TIMEOUT_SECONDS", 20)))
        metadata_response = self.session.get(
            NSE_MONTHLY_REPORTS_URL,
            headers=headers,
            timeout=timeout,
        )
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        report = next(
            item for item in metadata
            if item.get("fileKey") == NSE_IMPACT_COST_FILE_KEY
        )
        source_url = f"{report['filePath']}{report['fileActlName']}"
        file_response = self.session.get(source_url, headers=headers, timeout=timeout)
        file_response.raise_for_status()
        return self._parse_file(
            file_response.text,
            source_url=source_url,
            as_of=str(report.get("tradingDate") or "")[:10],
        )

    @staticmethod
    def _parse_file(text, source_url, as_of):
        raw = pd.read_csv(
            io.StringIO(text),
            header=None,
            names=["record", "symbol", "series", "isin", "category", "impact_cost"],
            dtype=str,
            on_bad_lines="skip",
        )
        equities = raw[
            raw["record"].eq("20") & raw["series"].eq("EQ")
        ].copy()
        equities["NSE_Liquidity_Category"] = pd.to_numeric(
            equities["category"], errors="coerce"
        )
        equities["NSE_Impact_Cost_Pct"] = pd.to_numeric(
            equities["impact_cost"], errors="coerce"
        )
        equities = equities[equities["NSE_Liquidity_Category"].isin([1, 2, 3])]
        if len(equities) < 500:
            raise ValueError("NSE liquidity file did not contain enough EQ records")
        labels = {
            1: "Group I - liquid",
            2: "Group II - less liquid",
            3: "Group III - illiquid",
        }
        result = pd.DataFrame({
            "Symbol": equities["symbol"].astype(str).str.strip().str.upper(),
            "NSE_Liquidity_Category": equities["NSE_Liquidity_Category"].astype(int),
            "NSE_Impact_Cost_Pct": equities["NSE_Impact_Cost_Pct"],
        })
        result["NSE_Liquidity_Group"] = result["NSE_Liquidity_Category"].map(labels)
        result["NSE_Liquidity_As_Of"] = as_of
        result["NSE_Liquidity_Source_Status"] = "Official NSE"
        result["NSE_Liquidity_Source_URL"] = source_url
        return result.drop_duplicates("Symbol", keep="last").reset_index(drop=True)

    @staticmethod
    def _empty_columns(frame, status):
        frame["NSE_Liquidity_Category"] = np.nan
        frame["NSE_Impact_Cost_Pct"] = np.nan
        frame["NSE_Liquidity_Group"] = "Unavailable"
        frame["NSE_Liquidity_As_Of"] = ""
        frame["NSE_Liquidity_Source_Status"] = status
        frame["NSE_Liquidity_Source_URL"] = ""
        return frame


class LiquidityQualityEnricher:
    """Keep investment conviction separate from portfolio execution capacity."""

    def __init__(self, config):
        self.config = config

    def enrich(self, scored_df):
        enriched = scored_df.copy()
        median_20d = _numeric_column(enriched, "Median_Turnover_20D_INR")
        median_60d = _numeric_column(enriched, "Median_Turnover_60D_INR")
        p10_20d = _numeric_column(enriched, "Turnover_P10_20D_INR")
        top5_share = _numeric_column(enriched, "Turnover_Top5_Share_60D")
        trading_frequency = _numeric_column(enriched, "Trading_Frequency_60D")
        nse_category = _numeric_column(enriched, "NSE_Liquidity_Category")
        nse_impact_cost = _numeric_column(enriched, "NSE_Impact_Cost_Pct")
        source_status = enriched.get(
            "NSE_Liquidity_Source_Status",
            pd.Series("Unavailable", index=enriched.index),
        ).fillna("Unavailable").astype(str)

        target_position = max(
            1.0,
            _number(getattr(self.config, "PORTFOLIO_TARGET_POSITION_INR", 1_00_000.0), 1_00_000.0),
        )
        participation_rate = min(
            1.0,
            max(
                0.0001,
                _number(
                    getattr(self.config, "LIQUIDITY_POSITION_PARTICIPATION_RATE", 0.01),
                    0.01,
                ),
            ),
        )
        minimum_frequency = min(
            1.0,
            max(
                0.0,
                _number(getattr(self.config, "LIQUIDITY_MIN_TRADING_FREQUENCY", 0.80), 0.80),
            ),
        )
        maximum_concentration = min(
            1.0,
            max(
                0.0,
                _number(
                    getattr(self.config, "LIQUIDITY_MAX_TURNOVER_TOP5_SHARE", 0.50),
                    0.50,
                ),
            ),
        )

        max_one_day_order = median_20d * participation_rate
        build_days = pd.Series(np.nan, index=enriched.index, dtype=float)
        valid_capacity = max_one_day_order.gt(0)
        build_days.loc[valid_capacity] = np.ceil(
            target_position / max_one_day_order.loc[valid_capacity]
        )

        official_observed = nse_category.isin([1, 2, 3])
        official_liquid = nse_category.eq(1)
        direct_reference = target_position <= NSE_IMPACT_COST_REFERENCE_ORDER_INR
        official_direct_evidence = (
            official_liquid & nse_impact_cost.notna() & nse_impact_cost.le(1.0)
        )
        turnover_fits = max_one_day_order.ge(target_position)
        frequency_ok = trading_frequency.ge(minimum_frequency)
        concentration_ok = top5_share.le(maximum_concentration)
        fallback_observed = median_20d.notna() & trading_frequency.notna() & top5_share.notna()
        fallback_actionable = (
            ~official_observed
            & fallback_observed
            & turnover_fits
            & frequency_ok
            & concentration_ok
        )
        official_actionable = official_liquid & (
            (direct_reference & official_direct_evidence)
            | (turnover_fits & concentration_ok)
        )
        actionable = official_actionable | fallback_actionable

        # Derived compatibility alias: never preserve a stale rating from an
        # earlier model/replay stage.
        enriched["Investment_Rating"] = enriched.get(
            "Rating", pd.Series("", index=enriched.index)
        )
        enriched["Portfolio_Target_Position_INR"] = round(target_position)
        enriched["Liquidity_Participation_Rate"] = participation_rate
        enriched["Liquidity_20D_Median_Cr"] = (median_20d / 1_00_00_000.0).round(2)
        enriched["Liquidity_60D_Median_Cr"] = (median_60d / 1_00_00_000.0).round(2)
        enriched["Liquidity_20D_P10_Cr"] = (p10_20d / 1_00_00_000.0).round(2)
        enriched["Liquidity_Top5_Share_60D"] = top5_share.round(4)
        enriched["Liquidity_Trading_Frequency_60D"] = trading_frequency.round(4)
        enriched["Liquidity_Max_One_Day_Order_INR"] = max_one_day_order.round(0)
        # Compatibility alias retained for existing CSV consumers.
        enriched["Liquidity_Suggested_Max_Position_INR"] = max_one_day_order.round(0)
        enriched["Turnover_Proxy_Estimated_Build_Days"] = build_days
        effective_build_days = build_days.copy()
        # NSE directly measures a Rs1 lakh order in the order book. When that
        # evidence fits the configured target, do not simultaneously label the
        # same order as multi-day only because the conservative turnover proxy
        # assumes a 1% daily participation limit.
        effective_build_days.loc[official_direct_evidence & direct_reference] = 1.0
        enriched["Portfolio_Estimated_Build_Days"] = effective_build_days
        enriched["Portfolio_Actionable"] = actionable
        enriched["Liquidity_Conviction_Eligible"] = actionable
        enriched["Liquidity_Rating_Capped"] = False
        enriched["Liquidity_Cap_Reason"] = ""

        enriched["Liquidity_Grade"] = "Proxy only"
        enriched.loc[nse_category.eq(1), "Liquidity_Grade"] = "Group I - liquid"
        enriched.loc[nse_category.eq(2), "Liquidity_Grade"] = "Group II - less liquid"
        enriched.loc[nse_category.eq(3), "Liquidity_Grade"] = "Group III - illiquid"
        enriched.loc[~official_observed & ~fallback_observed, "Liquidity_Grade"] = "Unknown"
        enriched["Liquidity_Status"] = enriched["Liquidity_Grade"]

        actionability = pd.Series("Unknown", index=enriched.index, dtype=object)
        actionability.loc[nse_category.isin([2, 3])] = "Restricted by NSE liquidity group"
        actionability.loc[official_direct_evidence & direct_reference] = (
            "Fits target; NSE Rs1 lakh impact-cost evidence"
        )
        category_without_impact = (
            official_liquid
            & direct_reference
            & ~official_direct_evidence
            & turnover_fits
            & concentration_ok
        )
        actionability.loc[category_without_impact] = (
            "Fits target using turnover proxy; NSE Group I impact value unavailable"
        )
        actionability.loc[official_liquid & (not direct_reference) & turnover_fits & concentration_ok] = (
            "Fits target using turnover proxy; NSE Group I confirms Rs1 lakh only"
        )
        actionability.loc[fallback_actionable] = (
            "Fits target using turnover proxy; official impact cost unavailable"
        )
        multi_day = official_liquid & ~actionable & build_days.notna()
        actionability.loc[multi_day] = build_days.loc[multi_day].map(
            lambda days: f"Build over about {int(days)} trading days at configured participation"
        )
        fallback_multi_day = ~official_observed & fallback_observed & ~actionable & build_days.notna()
        actionability.loc[fallback_multi_day] = build_days.loc[fallback_multi_day].map(
            lambda days: f"Proxy suggests about {int(days)} build days; impact cost unavailable"
        )
        enriched["Portfolio_Actionability"] = actionability

        warnings = pd.Series("", index=enriched.index, dtype=object)
        concentrated = top5_share.gt(maximum_concentration)
        warnings.loc[concentrated] = top5_share.loc[concentrated].map(
            lambda value: f"top 5 sessions supplied {value:.0%} of 60D turnover"
        )
        low_frequency = trading_frequency.lt(minimum_frequency)
        warnings.loc[low_frequency] = _append_reason(
            warnings.loc[low_frequency],
            trading_frequency.loc[low_frequency].map(
                lambda value: f"traded on {value:.0%} of observed 60D sessions"
            ),
        )
        larger_than_reference = official_liquid & (not direct_reference)
        warnings.loc[larger_than_reference] = _append_reason(
            warnings.loc[larger_than_reference],
            pd.Series(
                "NSE impact cost is measured for Rs1 lakh; larger target uses a turnover proxy",
                index=enriched.index,
            ).loc[larger_than_reference],
        )
        stale_source = source_status.str.contains("stale", case=False, na=False)
        warnings.loc[stale_source] = _append_reason(
            warnings.loc[stale_source],
            pd.Series(
                "NSE category refresh failed; using visibly stale exchange cache",
                index=enriched.index,
            ).loc[stale_source],
        )
        enriched["Liquidity_Warning"] = warnings
        enriched["Liquidity_Methodology"] = (
            "NSE monthly six-month liquidity group/mean impact cost for Rs1 lakh; "
            "larger or unavailable cases use median Close*Volume participation proxy"
        )
        return enriched


def filter_execution_universe(frame, config):
    """Use official NSE category first and turnover only when it is unavailable."""
    if frame is None or frame.empty:
        return frame
    price = _numeric_column(frame, "Current_Price")
    mean_turnover = _numeric_column(frame, "Avg_Turnover_INR")
    median_turnover = _numeric_column(frame, "Median_Turnover_20D_INR")
    nse_category = _numeric_column(frame, "NSE_Liquidity_Category")
    official_liquid = nse_category.eq(1)
    turnover_fallback = (
        nse_category.isna()
        & mean_turnover.ge(_number(getattr(config, "MIN_AVG_TURNOVER_INR", 50_00_000), 50_00_000))
        & median_turnover.ge(
            _number(getattr(config, "MIN_MEDIAN_TURNOVER_20D_INR", 50_00_000), 50_00_000)
        )
    )
    keep = price.ge(_number(getattr(config, "MIN_PRICE_INR", 0), 0)) & (
        official_liquid | turnover_fallback
    )
    return frame.loc[keep].reset_index(drop=True)


def _append_reason(existing, addition):
    existing = existing.fillna("").astype(str)
    addition = addition.fillna("").astype(str)
    return np.where(existing.str.len().gt(0), existing + "; " + addition, addition)


def _numeric_column(frame, column):
    return pd.to_numeric(
        frame.get(column, pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )


def _number(value, default):
    try:
        number = float(value)
        return number if math.isfinite(number) else float(default)
    except (TypeError, ValueError):
        return float(default)
