"""The cross-sectional scoring engine.

StockScorer turns a merged fundamentals/technicals frame into scored rows. The
per-metric curves live in the sibling modules; this one owns orchestration and
the technical component scores.
"""

import logging

import numpy as np
import pandas as pd

from ..numeric import round_half_up
from ..numeric import safe_float as _safe_float
from ..runtime import Config
from .constants import (
    CANONICAL_DECISION_COLUMNS,
    FINANCIAL_MODEL_NAMES,
    FINANCIAL_SPECIALIZED_FIELDS,
    GENERIC_FUNDAMENTAL_FIELDS,
    RATING_ORDER,
)
from .fundamental import (
    fundamental_anomalies,
    fundamental_model_for_row,
    fundamental_score_details,
    score_fundamentals,
    sector_relative_fund_scores,
    specialized_quality_gate,
)
from .sector_models import score_financial_services, score_real_estate
from .technical import (
    DEMAND_CMF_SCALE,
    DEMAND_RETURN_SCALE_PCT,
    DEMAND_VOLUME_SCALE,
    MAX_TECH_SCORE,
    score_technical,
    technical_score_details,
)

logger = logging.getLogger(__name__)

def sort_by_recommendation(df, score_column):
    """Order recommendation classes first, then score within each class."""
    return (
        df.assign(_Rating_Order=df["Rating"].map(RATING_ORDER).fillna(len(RATING_ORDER)))
        .sort_values(["_Rating_Order", score_column], ascending=[True, False])
        .drop(columns="_Rating_Order")
        .reset_index(drop=True)
    )


def _as_bool(value, default=False):
    try:
        if value is None or pd.isna(value):
            return default
    except (TypeError, ValueError):
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
    return bool(value)


class StockScorer:
    MAX_FUND_SCORE = 100.0

    # Technical scoring lives in .technical; these names stay on the class
    # because callers and tests use StockScorer.technical_score_details(row)
    # and StockScorer.MAX_TECH_SCORE.
    MAX_TECH_SCORE = MAX_TECH_SCORE
    DEMAND_CMF_SCALE = DEMAND_CMF_SCALE
    DEMAND_RETURN_SCALE_PCT = DEMAND_RETURN_SCALE_PCT
    DEMAND_VOLUME_SCALE = DEMAND_VOLUME_SCALE
    technical_score_details = staticmethod(technical_score_details)
    score_technical = staticmethod(score_technical)

    def __init__(self, config=None):
        self.config = config or Config

    # Callers and tests reach for StockScorer.safe_float, so the name stays on
    # the class. The implementation lives in screener.numeric so the sibling
    # scoring modules can share it without importing the engine.
    safe_float = staticmethod(_safe_float)

    def score_all_stocks(self, merged_df):
        """Score every row and return the frame ordered by Core_Score_Rank.

        The stages below run in a fixed order: each one may depend on columns
        an earlier stage wrote, and the peer reference must be settled before
        any row is scored relative to it.
        """

        # P2: empty-input guard
        if merged_df is None or len(merged_df) == 0:
            logger.warning("score_all_stocks: empty input - nothing to score")
            return merged_df

        merged_df = self._purge_stale_decisions(merged_df)
        logger.info(f"Scoring {len(merged_df)} stocks...")

        self._derive_missing_roe(merged_df)
        specialized_sectors, peer_reference_eligible = self._mark_peer_reference(merged_df)
        sector_rel_df, sector_relative_weight = self._sector_relative_inputs(
            merged_df, peer_reference_eligible
        )

        for idx, row in merged_df.iterrows():
            self._score_row(
                merged_df,
                idx,
                row,
                sector_rel_df=sector_rel_df,
                sector_relative_weight=sector_relative_weight,
                specialized_sectors=specialized_sectors,
            )

        return self._finalize_ranking(merged_df)

    @staticmethod
    def _purge_stale_decisions(merged_df):
        """Return a copy with any previous run's decision columns dropped.

        Returns rather than mutates: dropping columns rebinds the frame, so an
        in-place helper would silently do nothing to the caller's copy.
        """

        # A rescored export must not leak an earlier run's decisions. This
        # layer owns components and Core_* diagnostics only; the versioned
        # recommendation policy is the sole writer of canonical decisions.
        merged_df = merged_df.copy()
        stale_decisions = [
            column for column in CANONICAL_DECISION_COLUMNS if column in merged_df
        ]
        if stale_decisions:
            merged_df = merged_df.drop(columns=stale_decisions)
        return merged_df

    @staticmethod
    def _derive_missing_roe(merged_df):
        """Fill an unreported ROE from EPS / book value where both are present."""

        # Yahoo intermittently omits ROE even when per-share earnings and book
        # value are present. EPS / book value is a conservative end-period ROE
        # proxy; using it is materially better than treating an unknown ROE as
        # zero. Keep the source visible so downstream reports can audit it.
        if "ROE" not in merged_df:
            merged_df["ROE"] = np.nan
        if "ROE_Source" not in merged_df:
            merged_df["ROE_Source"] = ""
        reported_roe = pd.to_numeric(merged_df["ROE"], errors="coerce")
        eps = pd.to_numeric(
            merged_df.get("EPS", pd.Series(np.nan, index=merged_df.index)),
            errors="coerce",
        )
        book_value = pd.to_numeric(
            merged_df.get("Book_Value", pd.Series(np.nan, index=merged_df.index)),
            errors="coerce",
        )
        derived_roe = eps / book_value
        derived_roe_valid = (
            reported_roe.isna()
            & eps.notna()
            & book_value.gt(0)
            & derived_roe.between(-1.0, 1.0)
        )
        merged_df.loc[reported_roe.notna(), "ROE_Source"] = "reported"
        merged_df.loc[derived_roe_valid, "ROE"] = derived_roe.loc[derived_roe_valid]
        merged_df.loc[derived_roe_valid, "ROE_Source"] = "eps_to_book_proxy"
        if derived_roe_valid.any():
            logger.info(
                "Derived ROE from EPS/book value for %d stock(s) with missing reported ROE",
                int(derived_roe_valid.sum()),
            )

    def _mark_peer_reference(self, merged_df):
        """Flag which rows may act as a sector peer reference.

        Returns the specialized-model sectors and the eligibility mask, which
        the sector-relative stage needs to build its peer groups.
        """

        specialized_sectors = {
            str(sector).strip().upper()
            for sector in getattr(self.config, "SPECIALIZED_FUNDAMENTAL_SECTORS", [])
            if str(sector).strip()
        }

        # Relative ranks describe the current peer reference, so that
        # reference must contain only usable point-in-time records. Excluded
        # rows remain in the model and fall back to absolute scoring/caps; they
        # simply cannot move a fresh company's percentile.
        if "Fundamental_Record_Available" in merged_df:
            fundamental_available = merged_df["Fundamental_Record_Available"].map(
                lambda value: _as_bool(value, True)
            )
        else:
            fundamental_available = pd.Series(True, index=merged_df.index)
        if "Fund_Data_Stale" in merged_df:
            fundamental_stale = merged_df["Fund_Data_Stale"].map(
                lambda value: _as_bool(value, False)
            )
        else:
            fundamental_stale = pd.Series(False, index=merged_df.index)
        severe_peer_anomaly = merged_df.apply(
            lambda candidate: len(fundamental_anomalies(candidate)) >= 2,
            axis=1,
        )
        peer_reference_eligible = (
            fundamental_available & ~fundamental_stale & ~severe_peer_anomaly
        ).astype(bool)
        peer_sector = (
            merged_df.get("Sector", pd.Series("Unknown", index=merged_df.index))
            .fillna("Unknown")
            .astype(str)
            .str.strip()
            .replace("", "Unknown")
        )
        valid_peer_sector = peer_sector.ne("Unknown")
        peer_reference_eligible &= valid_peer_sector
        peer_reference_count = peer_reference_eligible.groupby(peer_sector).transform(
            "sum"
        )
        merged_df["Sector_Peer_Reference_Eligible"] = peer_reference_eligible
        merged_df["Sector_Peer_Reference_Count"] = (
            peer_reference_count.where(valid_peer_sector, 0).astype(int)
        )

        return specialized_sectors, peer_reference_eligible

    def _sector_relative_inputs(self, merged_df, peer_reference_eligible):
        """Return the sector-relative score frame and its blend weight."""

        sector_rel_df = None
        if getattr(self.config, "SECTOR_RELATIVE_FUND_SCORING_ENABLED", True):
            min_peers = getattr(self.config, "MIN_SECTOR_PEERS", 5)
            sector_rel_df = sector_relative_fund_scores(
                merged_df,
                min_peers=min_peers,
                reference_eligible=peer_reference_eligible,
            )
        sector_relative_weight = getattr(self.config, "SECTOR_RELATIVE_FUND_WEIGHT", 0.5)

        return sector_rel_df, sector_relative_weight

    def _score_row(
        self,
        merged_df,
        idx,
        row,
        *,
        sector_rel_df,
        sector_relative_weight,
        specialized_sectors,
    ):
        """Score one row in place, writing its components back to merged_df."""

        sector_relative = sector_rel_df.loc[idx] if sector_rel_df is not None else None
        fundamental_model = fundamental_model_for_row(row)
        if fundamental_model in FINANCIAL_MODEL_NAMES:
            fund_components = score_financial_services(
                row, fundamental_model=fundamental_model, return_components=True
            )
        elif fundamental_model == "Real Estate Asset Model":
            fund_components = score_real_estate(row, return_components=True)
        else:
            fund_components = score_fundamentals(
                row, sector_relative, sector_relative_weight, return_components=True
            )
        f_raw = sum(fund_components.values())
        fundamental = fundamental_score_details(
            row, fundamental_model, fund_components
        )
        technical = self.technical_score_details(row)
        t_raw = technical["adjusted_raw"]

        # Both sides are coverage-normalised: a component whose input was
        # never reported is dropped from the denominator and the score is
        # shrunk toward neutral, rather than being scored as the worst
        # possible observation.
        f_score = round_half_up(
            max(0.0, min(100.0, fundamental["adjusted_score"])), 2
        )
        t_score = round_half_up(
            max(0.0, min(100.0, t_raw / self.MAX_TECH_SCORE * 100)), 2
        )

        # ATR already contributes an explicit volatility penalty inside the
        # technical score. Keep model weights stable rather than letting the
        # same noisy input also change the blend regime.
        technical_price = StockScorer.safe_float(row.get("Technical_Price"))
        atr = StockScorer.safe_float(row.get("ATR_14"))
        atr_pct = (
            atr / technical_price * 100
            if technical_price is not None
            and technical_price > 0
            and atr is not None
            and atr >= 0
            else np.nan
        )

        weight_fund, weight_tech = 0.70, 0.30
        combined = round_half_up(
            f_score * weight_fund + t_score * weight_tech, 2
        )

        # P2: data-completeness gate - thin-data stocks can't be rated above HOLD
        expected_fund_fields = FINANCIAL_SPECIALIZED_FIELDS.get(
            fundamental_model, GENERIC_FUNDAMENTAL_FIELDS
        )
        present_fund_fields = [
            field
            for field in expected_fund_fields
            if StockScorer.safe_float(row.get(field)) is not None
        ]
        missing_fund_fields = [
            field for field in expected_fund_fields if field not in present_fund_fields
        ]
        fields_present = len(present_fund_fields)
        fundamental_coverage = (
            fields_present / len(expected_fund_fields) if expected_fund_fields else 0.0
        )
        buy_fund_coverage = float(
            getattr(self.config, "FUNDAMENTAL_MIN_COVERAGE_FOR_BUY", 0.55)
        )
        strong_fund_coverage = float(
            getattr(
                self.config,
                "FUNDAMENTAL_MIN_COVERAGE_FOR_STRONG_BUY",
                0.75,
            )
        )
        buy_tech_coverage = float(
            getattr(self.config, "TECHNICAL_MIN_COVERAGE_FOR_BUY", 0.75)
        )
        strong_tech_coverage = float(
            getattr(
                self.config,
                "TECHNICAL_MIN_COVERAGE_FOR_STRONG_BUY",
                0.90,
            )
        )
        data_quality = (
            "FULL"
            if fundamental_coverage >= 0.80
            else "LIMITED"
            if fundamental_coverage >= 0.50
            else "LOW"
        )
        fundamental_coverage_eligible = fundamental_coverage >= buy_fund_coverage
        technical_coverage_eligible = technical["coverage"] >= buy_tech_coverage
        strong_coverage_eligible = (
            fundamental_coverage >= strong_fund_coverage
            and technical["coverage"] >= strong_tech_coverage
        )
        sector = str(row.get("Sector") or "").strip().upper()
        specialized_fundamental_model_required = (
            sector in specialized_sectors
            and fundamental_model in {
                "Generic Fundamental Model",
                "Financial Services Data-Limited Model",
            }
        )
        anomalies = fundamental_anomalies(row)
        severe_fundamental_anomaly = len(anomalies) >= 2
        specialized_quality_eligible, specialized_quality_reason = specialized_quality_gate(
            row, fundamental_model
        )

        # Provisional core diagnostics explain what the pre-evidence model
        # sees. They are never the published recommendation.
        if combined >= 70:
            rating = "STRONG BUY"
        elif combined >= 60:
            rating = "BUY"
        elif combined >= 50:
            rating = "HOLD"
        elif combined >= 40:
            rating = "REDUCE"
        else:
            rating = "SELL"

        rating_cap_reason = ""
        rating_capped = bool(
            not fundamental_coverage_eligible and combined >= 60
        )
        if rating_capped:
            rating_cap_reason = "insufficient fundamental coverage"
        if not technical_coverage_eligible and combined >= 60:
            rating_capped = True
            rating_cap_reason = "; ".join(
                reason
                for reason in (
                    rating_cap_reason,
                    "insufficient technical coverage",
                )
                if reason
            )
        if specialized_fundamental_model_required and combined >= 60:
            rating_capped = True
            rating_cap_reason = "sector requires specialized model"
        fund_data_stale = str(row.get("Fund_Data_Stale", "")).strip().lower() in {
            "1", "true", "yes"
        }
        if fund_data_stale and combined >= 60:
            rating_capped = True
            rating_cap_reason = "stale fundamental fallback"
        if severe_fundamental_anomaly and combined >= 60:
            rating_capped = True
            rating_cap_reason = "multiple fundamental data anomalies"
        # A high score assembled from valuation ratios and neutral indicators
        # is not a current buy signal. BUY requires basic positive price
        # structure; STRONG BUY additionally requires directional strength.
        growth_floor = float(getattr(self.config, "STRONG_BUY_MIN_GROWTH", 0.05))
        tech_floor = float(getattr(self.config, "STRONG_BUY_MIN_TECH_SCORE", 55.0))
        adx_floor = float(getattr(self.config, "STRONG_BUY_MIN_ADX", 20.0))
        buy_ma50_slope_floor = float(getattr(self.config, "BUY_MIN_MA50_SLOPE", 0.0))
        buy_3m_return_floor = float(getattr(self.config, "BUY_MIN_3M_RETURN", 0.0))
        revenue_growth = StockScorer.safe_float(row.get("Revenue_Growth"))
        earnings_growth = StockScorer.safe_float(row.get("Earnings_Growth"))
        has_growth = (
            (revenue_growth is not None and revenue_growth >= growth_floor)
            or (earnings_growth is not None and earnings_growth >= growth_floor)
        )
        ma50 = StockScorer.safe_float(row.get("MA50"))
        ma50_slope = StockScorer.safe_float(row.get("MA50_Slope_Pct"))
        pct_3m = StockScorer.safe_float(row.get("Pct_Change_3M"))
        adx = StockScorer.safe_float(row.get("ADX_14"))
        plus_di = StockScorer.safe_float(row.get("ADX_Plus_DI"))
        minus_di = StockScorer.safe_float(row.get("ADX_Minus_DI"))
        buy_gate_failures = []
        if technical_price is None or technical_price <= 0 or ma50 is None:
            buy_gate_failures.append("price/MA50 unavailable")
        elif technical_price <= ma50:
            buy_gate_failures.append("price not above MA50")
        if ma50_slope is None:
            buy_gate_failures.append("MA50 slope unavailable")
        elif ma50_slope < buy_ma50_slope_floor:
            buy_gate_failures.append("MA50 falling")
        if pct_3m is None:
            buy_gate_failures.append("3M return unavailable")
        elif pct_3m <= buy_3m_return_floor:
            buy_gate_failures.append("3M return not positive")

        buy_eligible = not buy_gate_failures
        trend_confirmed = buy_eligible and all([
            adx is not None and adx >= adx_floor,
            plus_di is not None and minus_di is not None and plus_di > minus_di,
        ])
        require_uptrend_for_buy = bool(getattr(self.config, "REQUIRE_UPTREND_FOR_BUY", True))
        technical_rating_capped = bool(
            require_uptrend_for_buy and combined >= 60 and not buy_eligible
        )
        if technical_rating_capped:
            technical_reason = "buy trend not confirmed: " + ", ".join(buy_gate_failures)
            rating_cap_reason = "; ".join(
                reason for reason in (rating_cap_reason, technical_reason) if reason
            )
            rating_capped = True
        if rating_capped:
            rating = "HOLD"

        strong_buy_eligible = bool(
            has_growth
            and trend_confirmed
            and t_score >= tech_floor
            and specialized_quality_eligible
            and strong_coverage_eligible
            and not anomalies
            and not rating_capped
        )
        strong_buy_gate_reason = ""
        strong_buy_gate_failures = []
        if not specialized_quality_eligible:
            strong_buy_gate_failures.append(specialized_quality_reason)
        if not strong_coverage_eligible:
            strong_buy_gate_failures.append("insufficient evidence coverage")
        if anomalies:
            strong_buy_gate_failures.append(
                "fundamental anomaly: " + ", ".join(anomalies)
            )
        if not has_growth:
            strong_buy_gate_failures.append("growth below threshold")
        if not trend_confirmed:
            strong_buy_gate_failures.append("trend not confirmed")
        if t_score < tech_floor:
            strong_buy_gate_failures.append("technical score below threshold")
        if specialized_fundamental_model_required:
            strong_buy_gate_failures.append("sector requires specialized model")
        if rating_capped and rating_cap_reason:
            strong_buy_gate_failures.append(rating_cap_reason)
        strong_buy_gate_reason = "; ".join(
            dict.fromkeys(reason for reason in strong_buy_gate_failures if reason)
        )
        if rating == "STRONG BUY" and not strong_buy_eligible:
            rating = "BUY"

        merged_df.at[idx, "Fundamental_Score"] = f_score
        merged_df.at[idx, "Technical_Score"] = t_score
        merged_df.at[idx, "ATR_Pct"] = (
            round(atr_pct, 2) if pd.notna(atr_pct) else np.nan
        )
        merged_df.at[idx, "Dynamic_Weight_Fund"] = weight_fund
        merged_df.at[idx, "Dynamic_Weight_Tech"] = weight_tech
        merged_df.at[idx, "Combined_Score"] = combined
        merged_df.at[idx, "Core_Score"] = combined
        merged_df.at[idx, "Fund_Fields_Present"] = fields_present
        merged_df.at[idx, "Fund_Fields_Expected"] = len(expected_fund_fields)
        merged_df.at[idx, "Fundamental_Coverage"] = round(fundamental_coverage, 4)
        merged_df.at[idx, "Fundamental_Missing_Fields"] = ", ".join(missing_fund_fields)
        merged_df.at[idx, "Fundamental_Coverage_Eligible"] = fundamental_coverage_eligible
        # Capacity coverage weights each component by the points it can
        # contribute; the field-count coverage above still drives the gates.
        merged_df.at[idx, "Fundamental_Observed_Score"] = round(
            fundamental["observed_score"], 2
        )
        merged_df.at[idx, "Fundamental_Capacity_Coverage"] = round(
            fundamental["coverage"], 4
        )
        merged_df.at[idx, "Fundamental_Missing_Components"] = ", ".join(
            fundamental["missing_components"]
        )
        merged_df.at[idx, "Fundamental_Raw_Points"] = round(f_raw, 2)
        merged_df.at[idx, "Technical_Coverage"] = round(technical["coverage"], 4)
        merged_df.at[idx, "Technical_Observed_Score"] = round(
            technical["observed_score"], 2
        )
        merged_df.at[idx, "Technical_Missing_Components"] = ", ".join(
            technical["missing_components"]
        )
        merged_df.at[idx, "Technical_Coverage_Eligible"] = technical_coverage_eligible
        merged_df.at[idx, "Coverage_Eligible"] = bool(
            fundamental_coverage_eligible and technical_coverage_eligible
        )
        merged_df.at[idx, "Data_Quality"] = data_quality
        merged_df.at[idx, "Core_Rating_Capped"] = rating_capped
        merged_df.at[idx, "Core_Rating_Cap_Reason"] = rating_cap_reason
        merged_df.at[idx, "Specialized_Fundamental_Model_Required"] = specialized_fundamental_model_required
        merged_df.at[idx, "Fundamental_Model"] = fundamental_model
        valuation_keys = {"PE", "PB", "PB_ROE", "EV"}
        growth_keys = {"RG", "EG"}
        income_keys = {"DY"}
        valuation_points = sum(
            value for key, value in fund_components.items() if key in valuation_keys
        )
        growth_points = sum(
            value for key, value in fund_components.items() if key in growth_keys
        )
        income_points = sum(
            value for key, value in fund_components.items() if key in income_keys
        )
        quality_points = f_raw - valuation_points - growth_points - income_points
        merged_df.at[idx, "Fund_Valuation_Points"] = round(valuation_points, 2)
        merged_df.at[idx, "Fund_Quality_Points"] = round(quality_points, 2)
        merged_df.at[idx, "Fund_Growth_Points"] = round(growth_points, 2)
        merged_df.at[idx, "Fund_Income_Points"] = round(income_points, 2)
        merged_df.at[idx, "Fund_Component_Summary"] = (
            f"Val {valuation_points:.1f} | Quality {quality_points:.1f} | "
            f"Growth {growth_points:.1f} | Income {income_points:.1f}"
        )
        for component, points in fund_components.items():
            merged_df.at[idx, f"Fund_Component_{component}"] = round(points, 2)
        for component, points in technical["components"].items():
            merged_df.at[idx, f"Tech_Component_{component}"] = (
                round(points, 2) if points is not None else np.nan
            )
        merged_df.at[idx, "Demand_Proxy_Points"] = technical["components"].get("VOL")
        merged_df.at[idx, "Demand_Proxy_Continuous_Signal"] = (
            round(technical["demand_proxy_signal"], 6)
            if technical["demand_proxy_signal"] is not None else np.nan
        )
        merged_df.at[idx, "Demand_Proxy_CMF_Signal"] = (
            round(technical["demand_proxy_cmf_signal"], 6)
            if technical["demand_proxy_cmf_signal"] is not None else np.nan
        )
        merged_df.at[idx, "Demand_Proxy_Return_Signal"] = (
            round(technical["demand_proxy_return_signal"], 6)
            if technical["demand_proxy_return_signal"] is not None else np.nan
        )
        merged_df.at[idx, "Demand_Proxy_Volume_Weight"] = (
            round(technical["demand_proxy_volume_weight"], 6)
            if technical["demand_proxy_volume_weight"] is not None else np.nan
        )
        merged_df.at[idx, "Demand_Proxy_Input_Complete"] = technical[
            "demand_proxy_input_complete"
        ]
        merged_df.at[idx, "Fundamental_Anomaly"] = bool(anomalies)
        merged_df.at[idx, "Fundamental_Anomaly_Reason"] = ", ".join(anomalies)
        merged_df.at[idx, "Specialized_Quality_Eligible"] = specialized_quality_eligible
        merged_df.at[idx, "Specialized_Quality_Gate_Reason"] = specialized_quality_reason
        merged_df.at[idx, "Core_Buy_Eligible"] = buy_eligible
        merged_df.at[idx, "Core_Buy_Gate_Reason"] = ", ".join(buy_gate_failures)
        merged_df.at[idx, "Core_Strong_Buy_Eligible"] = strong_buy_eligible
        merged_df.at[idx, "Core_Strong_Buy_Gate_Reason"] = strong_buy_gate_reason
        merged_df.at[idx, "Core_Trend_Confirmed"] = trend_confirmed
        merged_df.at[idx, "Core_Rating"] = rating

    @staticmethod
    def _finalize_ranking(merged_df):
        """Sort deterministically, assign Core_Score_Rank and log any caps."""

        # Core order is deterministic and score-first. Recommendation classes
        # and execution constraints are applied only after all evidence stages.
        sort_columns = ["Combined_Score"]
        ascending = [False]
        if "Symbol" in merged_df:
            sort_columns.append("Symbol")
            ascending.append(True)
        merged_df = merged_df.sort_values(
            sort_columns,
            ascending=ascending,
            na_position="last",
            kind="mergesort",
        ).reset_index(drop=True)
        merged_df["Core_Score_Rank"] = range(1, len(merged_df) + 1)

        n_capped = int(merged_df["Core_Rating_Capped"].sum())
        if n_capped:
            logger.info(
                "Core diagnostic cap: %d stock(s) would be capped at HOLD before evidence",
                n_capped,
            )

        return merged_df
