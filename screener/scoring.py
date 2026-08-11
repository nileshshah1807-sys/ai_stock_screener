"""Fundamental and technical scoring models."""

import logging

import numpy as np
import pandas as pd

from .numeric import round_half_up
from .runtime import Config

logger = logging.getLogger(__name__)

# =====================================================
FUND_KEY_FIELDS = ("PE_Ratio", "ROE", "Profit_Margin", "Revenue_Growth")

# Metrics eligible for sector-relative (percentile-rank) fundamental scoring, mapped
# to the "scores" dict key used in score_fundamentals(), the metric's max points in
# that function, and whether a HIGHER raw value is better (False = lower is better,
# e.g. PE/Debt-to-Equity/EV-EBITDA where cheaper/less-levered scores higher).
SECTOR_RELATIVE_FIELDS = {
    "PE_Ratio":        ("PE", 15, False),
    "PB_Ratio":        ("PB", 8, False),
    "ROE":             ("ROE", 15, True),
    "ROA":             ("ROA", 5, True),
    "Debt_to_Equity":  ("DE", 10, False),
    "Current_Ratio":   ("CR", 7, True),
    "Profit_Margin":   ("PM", 10, True),
    "Revenue_Growth":  ("RG", 10, True),
    "Earnings_Growth": ("EG", 10, True),
    "Dividend_Yield":  ("DY", 5, True),
    "EV_EBITDA":       ("EV", 5, False),
}
# Reverse lookup: scores-dict key -> source column, used inside score_fundamentals()
SECTOR_RELATIVE_COLUMN_BY_KEY = {key: col for col, (key, _, _) in SECTOR_RELATIVE_FIELDS.items()}
SECTOR_RELATIVE_MINIMUMS = {
    "PE_Ratio": 0.0,
    "PB_Ratio": 0.0,
    "EV_EBITDA": 0.0,
    "Debt_to_Equity": 0.0,
    "Current_Ratio": 0.0,
    "Dividend_Yield": 0.0,
}
RATING_ORDER = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "REDUCE": 3, "SELL": 4}
CANONICAL_DECISION_COLUMNS = {
    "Rating",
    "Rank",
    "Buy_Eligible",
    "Buy_Gate_Reason",
    "Buy_Gate_Failures",
    "Buy_Gate_Failure_Count",
    "Strong_Buy_Eligible",
    "Strong_Buy_Gate_Reason",
    "Strong_Buy_Gate_Failures",
    "Strong_Buy_Gate_Failure_Count",
    "Trend_Confirmed",
    "Rating_Capped",
    "Rating_Cap_Reason",
    "Gate_Failures",
    "Gate_Failure_Count",
    "Evidence_Score",
    "Evidence_Rating",
    "Decision_Score",
    "Decision_Rating",
    "Decision_Score_Ceiling",
    "Decision_Cap_Applied",
    "Decision_Cap_Reason",
    "Final_Score",
    "Score_Rank",
    "Recommendation_Rank",
    "Investment_Rank",
    "Actionable_Rank",
}
FINANCIAL_MODEL_NAMES = {
    "Bank Equity Quality Model",
    "NBFC Equity Quality Model",
    "Capital Markets Earnings Quality Model",
    "Insurance Equity Quality Model",
    "Financial Services Data-Limited Model",
}

# Technical evidence is scored component-by-component. Missing evidence has no
# hidden default points; the observed score is confidence-shrunk toward 50 by
# coverage. This makes an empty technical row exactly neutral with zero
# confidence instead of the previous implicit 62.12/100.
TECH_COMPONENT_MAX = {
    "RSI": 12.0,
    "MA20": 15.0,
    "MA50": 15.0,
    "MACD": 15.0,
    "VOL": 15.0,
    "MOM": 20.0,
    "BB": 8.0,
    "ADX": 12.0,
    "STOCH": 12.0,
    "ATR": 8.0,
}

GENERIC_FUNDAMENTAL_FIELDS = tuple(SECTOR_RELATIVE_FIELDS)
FINANCIAL_SPECIALIZED_FIELDS = {
    "Bank Equity Quality Model": (
        "PB_Ratio", "ROE", "Gross_NPA", "Net_NPA", "Capital_Adequacy",
        "Profit_Margin", "Revenue_Growth", "Earnings_Growth",
    ),
    "NBFC Equity Quality Model": (
        "PB_Ratio", "ROE", "Gross_NPA", "Net_NPA", "Capital_Adequacy",
        "Profit_Margin", "Revenue_Growth", "Earnings_Growth",
    ),
    "Insurance Equity Quality Model": (
        "PB_Ratio", "ROE", "Solvency_Ratio", "Profit_Margin",
        "Revenue_Growth", "Earnings_Growth",
    ),
    "Capital Markets Earnings Quality Model": (
        "PE_Ratio", "PB_Ratio", "ROE", "ROA", "Profit_Margin",
        "Revenue_Growth", "Earnings_Growth", "Dividend_Yield",
    ),
    "Financial Services Data-Limited Model": (
        "PE_Ratio", "PB_Ratio", "ROE", "Profit_Margin",
        "Revenue_Growth", "Earnings_Growth",
    ),
    "Real Estate Asset Model": (
        "PB_Ratio", "ROE", "Debt_to_Equity", "Current_Ratio",
        "Profit_Margin", "Revenue_Growth", "Earnings_Growth",
    ),
}


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


def sector_relative_fund_scores(
    merged_df, min_peers=5, *, reference_eligible=None
):
    """Percentile-rank each fundamental metric against same-sector peers in the
    current scan, instead of a single fixed absolute threshold.

    A PE of 18 might be cheap for an IT stock but expensive for a Utility - this
    compares each stock to the other same-sector names actually being scored
    today rather than one universal bar. Returns a DataFrame (same index as
    merged_df) of per-column scores already expressed on that column's normal
    point scale (see SECTOR_RELATIVE_FIELDS); cells are NaN wherever the stock's
    own value is missing or its sector has fewer than ``min_peers`` members, so
    the caller can fall back to the absolute-threshold score for those cases.
    ``reference_eligible`` can exclude stale, unavailable, or anomalous records
    from both the reference distribution and relative scoring without removing
    those stocks from the broader model.
    """
    if merged_df is None or len(merged_df) == 0:
        return pd.DataFrame(index=merged_df.index if merged_df is not None else None)

    sector = merged_df.get("Sector")
    if sector is None:
        sector = pd.Series("Unknown", index=merged_df.index)
    sector = sector.fillna("Unknown").astype(str).str.strip().replace("", "Unknown")
    # "Unknown" is not a sector. Ranking every missing-sector company against
    # every other missing-sector company silently compares banks, manufacturers,
    # and microcaps as if they were peers; fall back to absolute scoring instead.
    valid_sector = sector != "Unknown"
    if reference_eligible is None:
        reference_eligible = pd.Series(True, index=merged_df.index, dtype=bool)
    elif isinstance(reference_eligible, pd.Series):
        reference_eligible = reference_eligible.reindex(merged_df.index).fillna(False)
    else:
        reference_eligible = pd.Series(
            reference_eligible, index=merged_df.index, dtype=bool
        )
    reference_eligible = reference_eligible.astype(bool) & valid_sector

    out = pd.DataFrame(index=merged_df.index)
    for column, (_, max_pts, higher_is_better) in SECTOR_RELATIVE_FIELDS.items():
        if column not in merged_df:
            out[column] = np.nan
            continue
        values = pd.to_numeric(merged_df[column], errors="coerce")
        if column in SECTOR_RELATIVE_MINIMUMS:
            minimum = SECTOR_RELATIVE_MINIMUMS[column]
            if column in {"PE_Ratio", "PB_Ratio", "EV_EBITDA"}:
                values = values.where(values > minimum)
            else:
                values = values.where(values >= minimum)
        reference_values = values.where(reference_eligible)
        group_size = reference_values.groupby(sector).transform("count")
        raw_rank = reference_values.groupby(sector).rank(method="average")
        # Map every peer group symmetrically onto [0, 1]. pandas rank(pct=True)
        # maps ranks to [1/n, 1], so inverting it gives lower-is-better metrics
        # [0, (n-1)/n] and unfairly prevents the best value from scoring full
        # points. The explicit (rank - 1) / (n - 1) transform avoids that bias.
        pct_rank = (raw_rank - 1.0) / (group_size - 1.0)
        if not higher_is_better:
            pct_rank = 1.0 - pct_rank
        score = pct_rank * max_pts
        score = score.where(
            (group_size >= min_peers) & valid_sector & reference_eligible
        )
        out[column] = score
    return out


class StockScorer:
    MAX_FUND_SCORE = 100.0
    MAX_TECH_SCORE = sum(TECH_COMPONENT_MAX.values())
    DEMAND_CMF_SCALE = 0.10
    DEMAND_RETURN_SCALE_PCT = 10.0
    DEMAND_VOLUME_SCALE = 1.50

    def __init__(self, config=None):
        self.config = config or Config

    @staticmethod
    def safe_float(val, default=None):
        try:
            if val is None or pd.isna(val):
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    def score_all_stocks(self, merged_df):
        # P2: empty-input guard
        if merged_df is None or len(merged_df) == 0:
            logger.warning("score_all_stocks: empty input - nothing to score")
            return merged_df

        # A rescored export must not leak an earlier run's decisions. This
        # layer owns components and Core_* diagnostics only; the versioned
        # recommendation policy is the sole writer of canonical decisions.
        merged_df = merged_df.copy()
        stale_decisions = [
            column for column in CANONICAL_DECISION_COLUMNS if column in merged_df
        ]
        if stale_decisions:
            merged_df = merged_df.drop(columns=stale_decisions)

        logger.info(f"Scoring {len(merged_df)} stocks...")
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

        sector_rel_df = None
        if getattr(self.config, "SECTOR_RELATIVE_FUND_SCORING_ENABLED", True):
            min_peers = getattr(self.config, "MIN_SECTOR_PEERS", 5)
            sector_rel_df = sector_relative_fund_scores(
                merged_df,
                min_peers=min_peers,
                reference_eligible=peer_reference_eligible,
            )
        sector_relative_weight = getattr(self.config, "SECTOR_RELATIVE_FUND_WEIGHT", 0.5)

        for idx, row in merged_df.iterrows():
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
            technical = self.technical_score_details(row)
            t_raw = technical["adjusted_raw"]

            # normalize both to 0-100
            f_score = round_half_up(
                max(0.0, min(100.0, f_raw / self.MAX_FUND_SCORE * 100)), 2
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

    @staticmethod
    def _interpolate(value, knots):
        xs, ys = zip(*knots)
        return float(np.interp(float(value), xs, ys))

    @classmethod
    def technical_score_details(cls, row):
        """Return continuous component scores plus explicit evidence coverage."""
        s = cls.safe_float
        scores = {name: None for name in TECH_COMPONENT_MAX}
        # Every price-relative indicator below is derived from adjusted OHLC.
        # Current_Price intentionally remains raw for valuation/display only.
        price = s(row.get("Technical_Price"))

        rsi = s(row.get("RSI_14"))
        if rsi is not None:
            scores["RSI"] = cls._interpolate(
                rsi,
                [(0, 3), (20, 4), (30, 8), (40, 11), (50, 12),
                 (60, 11), (70, 8), (80, 5), (100, 3)],
            )

        ma20 = s(row.get("MA20"))
        if price is not None and price > 0 and ma20 is not None and ma20 > 0:
            distance = (price / ma20 - 1.0) * 100.0
            scores["MA20"] = cls._interpolate(
                distance,
                [(-30, 3), (-10, 5), (-5, 7), (0, 10), (5, 13),
                 (7.5, 15), (15, 11), (30, 8)],
            )

        ma50 = s(row.get("MA50"))
        slope = s(row.get("MA50_Slope_Pct"))
        if (
            price is not None and price > 0
            and ma50 is not None and ma50 > 0
            and slope is not None
        ):
            distance = (price / ma50 - 1.0) * 100.0
            ma50_points = cls._interpolate(
                distance,
                [(-30, 2), (-15, 4), (-5, 7), (0, 10), (5, 13),
                 (8, 15), (15, 11), (35, 7)],
            )
            adjustment = cls._interpolate(
                slope,
                [(-10, -6), (-3, -6), (0, 0), (3, 2), (10, 2)],
            )
            ma50_points += adjustment
            scores["MA50"] = float(np.clip(ma50_points, 1.0, 15.0))

        macd = s(row.get("MACD"))
        signal = s(row.get("MACD_Signal"))
        if (
            price is not None and price > 0
            and macd is not None and signal is not None
        ):
            spread_pct = (macd - signal) / price * 100.0
            scores["MACD"] = cls._interpolate(
                spread_pct,
                [(-3, 3), (-1, 5), (0, 8), (0.5, 12), (2, 15), (5, 15)],
            )

        vol_ratio = s(row.get("Vol_Ratio"))
        cmf_21 = s(row.get("CMF_21"))
        return_20d = s(row.get("Price_Return_20D_Pct"))
        demand_cmf_signal = None
        demand_return_signal = None
        demand_signal = None
        demand_volume_weight = None
        demand_inputs_complete = bool(
            cmf_21 is not None
            and return_20d is not None
            and vol_ratio is not None
            and vol_ratio >= 0
        )
        if demand_inputs_complete:
            # CMF and price return supply direction; relative volume controls
            # confidence in that direction. tanh keeps the result bounded and
            # continuous, eliminating category jumps at exactly zero.
            demand_cmf_signal = float(np.tanh(cmf_21 / cls.DEMAND_CMF_SCALE))
            demand_return_signal = float(
                np.tanh(return_20d / cls.DEMAND_RETURN_SCALE_PCT)
            )
            demand_signal = (demand_cmf_signal + demand_return_signal) / 2.0
            demand_volume_weight = float(
                np.tanh(vol_ratio / cls.DEMAND_VOLUME_SCALE)
            )
            scores["VOL"] = float(np.clip(
                7.5 + 7.5 * demand_signal * demand_volume_weight,
                0.0,
                TECH_COMPONENT_MAX["VOL"],
            ))

        pct_1m = s(row.get("Pct_Change_1M"))
        if pct_1m is not None:
            scores["MOM"] = cls._interpolate(
                pct_1m,
                [(-30, 1), (-10, 2), (-5, 6), (0, 8), (5, 20),
                 (15, 20), (25, 14), (40, 8), (80, 4)],
            )

        bb_pos = s(row.get("BB_Position"))
        if bb_pos is not None:
            scores["BB"] = cls._interpolate(
                bb_pos,
                [(-0.5, 5), (0, 7), (0.15, 8), (0.3, 6), (0.7, 6),
                 (0.9, 5), (1.0, 3), (1.5, 2)],
            )

        adx = s(row.get("ADX_14"))
        plus_di = s(row.get("ADX_Plus_DI"))
        minus_di = s(row.get("ADX_Minus_DI"))
        direction = None
        if adx is not None and plus_di is not None and minus_di is not None:
            denominator = abs(plus_di) + abs(minus_di)
            direction = (plus_di - minus_di) / denominator if denominator else 0.0
            strength = float(np.clip((adx - 15.0) / 25.0, 0.0, 1.0))
            scores["ADX"] = float(np.clip(3.0 + 9.0 * strength * direction, 1.0, 12.0))

        stoch_rsi = s(row.get("StochRSI_14"))
        if stoch_rsi is not None:
            if stoch_rsi <= 0 or stoch_rsi >= 100:
                scores["STOCH"] = 6.0
            elif stoch_rsi < 20 and direction is not None and direction < 0:
                scores["STOCH"] = 6.0
            else:
                scores["STOCH"] = cls._interpolate(
                    stoch_rsi,
                    [(0, 10), (15, 12), (30, 8), (50, 8), (70, 8),
                     (80, 6), (100, 3)],
                )

        atr = s(row.get("ATR_14"))
        if price is not None and price > 0 and atr is not None and atr >= 0:
            atr_pct = atr / price * 100.0
            scores["ATR"] = cls._interpolate(
                atr_pct,
                [(0, 8), (0.5, 8), (1, 7), (2, 5), (4, 2), (6, 1), (10, 0)],
            )

        observed = [name for name, value in scores.items() if value is not None]
        missing = [name for name, value in scores.items() if value is None]
        observed_max = sum(TECH_COMPONENT_MAX[name] for name in observed)
        raw = sum(float(scores[name]) for name in observed)
        coverage = observed_max / cls.MAX_TECH_SCORE if cls.MAX_TECH_SCORE else 0.0
        observed_score = raw / observed_max * 100.0 if observed_max else 50.0
        adjusted_score = 50.0 + coverage * (observed_score - 50.0)
        adjusted_score = float(np.clip(adjusted_score, 0.0, 100.0))
        return {
            "components": scores,
            "raw": raw,
            "observed_max": observed_max,
            "coverage": coverage,
            "observed_score": observed_score,
            "adjusted_score": adjusted_score,
            "adjusted_raw": adjusted_score / 100.0 * cls.MAX_TECH_SCORE,
            "missing_components": missing,
            "demand_proxy_input_complete": demand_inputs_complete,
            "demand_proxy_cmf_signal": demand_cmf_signal,
            "demand_proxy_return_signal": demand_return_signal,
            "demand_proxy_signal": demand_signal,
            "demand_proxy_volume_weight": demand_volume_weight,
        }

    @classmethod
    def score_technical(cls, row):
        """Backward-compatible raw score on the declared MAX_TECH_SCORE scale."""
        return cls.technical_score_details(row)["adjusted_raw"]

def fundamental_model_for_row(row):
    sector = str(row.get("Sector") or "").strip().upper()
    if sector == "FINANCIAL SERVICES":
        industry = str(row.get("Industry") or "").strip().upper()
        if "BANK" in industry:
            return "Bank Equity Quality Model"
        if any(term in industry for term in ("CREDIT SERVICES", "MORTGAGE", "CONSUMER FINANCE")):
            return "NBFC Equity Quality Model"
        if any(term in industry for term in ("CAPITAL MARKET", "ASSET MANAGEMENT", "BROKER", "EXCHANGE")):
            return "Capital Markets Earnings Quality Model"
        if "INSURANCE" in industry:
            return "Insurance Equity Quality Model"
        return "Financial Services Data-Limited Model"
    if sector == "REAL ESTATE":
        return "Real Estate Asset Model"
    return "Generic Fundamental Model"


def fundamental_anomalies(row):
    """Return severe point-in-time data patterns that need manual validation."""
    s = StockScorer.safe_float
    checks = (
        ("PE_Ratio", lambda value: 0 < value < 1, "PE below 1"),
        ("ROE", lambda value: abs(value) > 1, "absolute ROE above 100%"),
        ("ROA", lambda value: abs(value) > 0.5, "absolute ROA above 50%"),
        ("Profit_Margin", lambda value: abs(value) > 1, "absolute margin above 100%"),
        ("Revenue_Growth", lambda value: value > 2 or value <= -1, "extreme revenue growth"),
        ("Earnings_Growth", lambda value: value > 2 or value <= -1, "extreme earnings growth"),
    )
    anomalies = []
    for field, predicate, message in checks:
        value = s(row.get(field))
        if value is not None and predicate(value):
            anomalies.append(message)
    return anomalies


def specialized_quality_gate(row, fundamental_model):
    """High-conviction financial labels require sector-specific risk inputs."""
    s = StockScorer.safe_float
    required_by_model = {
        "Bank Equity Quality Model": (
            "Gross_NPA", "Net_NPA", "Capital_Adequacy",
        ),
        "NBFC Equity Quality Model": (
            "Gross_NPA", "Net_NPA", "Capital_Adequacy",
        ),
        "Insurance Equity Quality Model": ("Solvency_Ratio",),
        "Capital Markets Earnings Quality Model": (
            "ROE", "ROA", "Profit_Margin",
        ),
    }
    if fundamental_model == "Financial Services Data-Limited Model":
        return False, "financial sub-industry requires a dedicated model"
    required = required_by_model.get(fundamental_model)
    if not required:
        return True, "passed"
    missing = [field for field in required if s(row.get(field)) is None]
    if missing:
        return False, "missing specialized quality data: " + ", ".join(missing)

    if fundamental_model in {"Bank Equity Quality Model", "NBFC Equity Quality Model"}:
        gross_npa, net_npa, capital_adequacy = _financial_quality_percentages(row)
        failures = []
        if gross_npa > 8.0:
            failures.append(f"Gross NPA {gross_npa:.1f}% above 8%")
        if net_npa > 4.0:
            failures.append(f"Net NPA {net_npa:.1f}% above 4%")
        if capital_adequacy < 12.0:
            failures.append(f"capital adequacy {capital_adequacy:.1f}% below 12%")
        if failures:
            return False, "specialized quality threshold failed: " + ", ".join(failures)

    if fundamental_model == "Insurance Equity Quality Model":
        solvency = s(row.get("Solvency_Ratio"))
        if solvency is not None and solvency > 10:
            solvency /= 100.0
        if solvency is None or solvency < 1.5:
            return False, "specialized quality threshold failed: solvency below 1.5x"
    return True, "passed"


def _financial_quality_percentages(row):
    """Normalize NPA/CAR fields using capital adequacy to infer row units."""
    s = StockScorer.safe_float
    capital_adequacy = s(row.get("Capital_Adequacy"))
    values_are_ratios = capital_adequacy is not None and abs(capital_adequacy) <= 1.0

    def normalize(field):
        value = s(row.get(field))
        if value is None:
            return None
        return value * 100.0 if values_are_ratios else value

    return normalize("Gross_NPA"), normalize("Net_NPA"), normalize("Capital_Adequacy")


def _bank_risk_points(row, gross_max, net_max, capital_max, nbfc=False):
    gross_npa, net_npa, capital_adequacy = _financial_quality_percentages(row)
    gross_good = 3.0 if nbfc else 2.0
    net_good = 1.5 if nbfc else 1.0
    return {
        "GROSS_NPA": 0.0 if gross_npa is None else (
            float(gross_max) if gross_npa <= gross_good
            else round(gross_max * 0.70, 2) if gross_npa <= 4.0
            else round(gross_max * 0.35, 2) if gross_npa <= 8.0
            else 0.0
        ),
        "NET_NPA": 0.0 if net_npa is None else (
            float(net_max) if net_npa <= net_good
            else round(net_max * 0.70, 2) if net_npa <= 2.0
            else round(net_max * 0.35, 2) if net_npa <= 4.0
            else 0.0
        ),
        "CAPITAL_ADEQUACY": 0.0 if capital_adequacy is None else (
            float(capital_max) if capital_adequacy >= 18.0
            else round(capital_max * 0.80, 2) if capital_adequacy >= 15.0
            else round(capital_max * 0.50, 2) if capital_adequacy >= 12.0
            else 0.0
        ),
    }


def _pe_points(pe, max_points):
    if pe is None or pe <= 0:
        return 0.0
    if pe < 1:
        return round(max_points * 0.30, 2)
    if pe < 10:
        return float(max_points)
    if pe < 18:
        return round(max_points * 0.85, 2)
    if pe < 25:
        return round(max_points * 0.67, 2)
    if pe < 40:
        return round(max_points * 0.40, 2)
    return round(max_points * 0.20, 2)


def _pb_roe_points(pb, roe, max_points):
    """Reward cheap book value only when the equity earns an adequate return."""
    if pb is None or pb <= 0 or roe is None:
        return 0.0
    if roe < 0:
        base = 1
    elif roe >= 0.18:
        base = 20 if pb <= 2 else 16 if pb <= 3 else 10
    elif roe >= 0.15:
        base = 17 if pb <= 1.5 else 14 if pb <= 2.5 else 8
    elif roe >= 0.12:
        base = 14 if pb <= 1.25 else 11 if pb <= 2 else 6
    elif roe >= 0.10:
        base = 10 if pb <= 1 else 8 if pb <= 1.5 else 4
    else:
        base = 4 if pb < 1 else 2
    return round(base / 20 * max_points, 2)


def _roe_points(value, max_points):
    if value is None:
        return 0.0
    if abs(value) > 1:
        return round(max_points * 0.30, 2)
    if value >= 0.20:
        return float(max_points)
    if value >= 0.15:
        return round(max_points * 0.80, 2)
    if value >= 0.10:
        return round(max_points * 0.55, 2)
    if value >= 0:
        return round(max_points * 0.30, 2)
    return round(max_points * 0.10, 2)


def _roa_points(value, max_points):
    if value is None:
        return 0.0
    if abs(value) > 0.5:
        return round(max_points * 0.20, 2)
    if value >= 0.03:
        return float(max_points)
    if value >= 0.02:
        return round(max_points * 0.80, 2)
    if value >= 0.01:
        return round(max_points * 0.60, 2)
    if value >= 0:
        return round(max_points * 0.30, 2)
    return round(max_points * 0.10, 2)


def _profit_points(value, max_points):
    if value is None:
        return 0.0
    if abs(value) > 1:
        return round(max_points * 0.30, 2)
    if value >= 0.20:
        return float(max_points)
    if value >= 0.12:
        return round(max_points * 0.80, 2)
    if value >= 0.05:
        return round(max_points * 0.55, 2)
    if value >= 0:
        return round(max_points * 0.30, 2)
    return round(max_points * 0.10, 2)


def _growth_points(value, max_points, strong_threshold=0.20):
    if value is None:
        return 0.0
    if value > 2 or value <= -1:
        return round(max_points * 0.30, 2)
    if value >= strong_threshold:
        return float(max_points)
    if value >= 0.10:
        return round(max_points * 0.80, 2)
    if value >= 0.05:
        return round(max_points * 0.60, 2)
    if value >= 0:
        return round(max_points * 0.30, 2)
    return round(max_points * 0.10, 2)


def _dividend_points(value, max_points=5):
    if value is None or value <= 0:
        return 0.0
    if value >= 0.03:
        return float(max_points)
    if value >= 0.015:
        return round(max_points * 0.80, 2)
    return round(max_points * 0.60, 2)


def score_financial_services(row, fundamental_model=None, return_components=False):
    """Industry-specific equity models; never use debt as a bank quality input."""
    s = StockScorer.safe_float
    model = fundamental_model or fundamental_model_for_row(row)
    pe = s(row.get("PE_Ratio"))
    pb = s(row.get("PB_Ratio"))
    roe = s(row.get("ROE"))
    roa = s(row.get("ROA"))
    margin = s(row.get("Profit_Margin"))
    revenue_growth = s(row.get("Revenue_Growth"))
    earnings_growth = s(row.get("Earnings_Growth"))
    dividend_yield = s(
        row.get("Dividend_Yield_Ratio")
        if row.get("Dividend_Yield_Ratio") is not None
        else row.get("Dividend_Yield")
    )

    if model == "Bank Equity Quality Model":
        scores = {
            "PE": _pe_points(pe, 10),
            "PB_ROE": _pb_roe_points(pb, roe, 15),
            "ROE": _roe_points(roe, 15),
            "ROA": _roa_points(roa, 10),
            "PM": _profit_points(margin, 5),
            "RG": _growth_points(revenue_growth, 8, 0.15),
            "EG": _growth_points(earnings_growth, 7),
            "DY": _dividend_points(dividend_yield),
        }
        scores.update(_bank_risk_points(row, gross_max=8, net_max=7, capital_max=10))
    elif model == "NBFC Equity Quality Model":
        scores = {
            "PE": _pe_points(pe, 10),
            "PB_ROE": _pb_roe_points(pb, roe, 15),
            "ROE": _roe_points(roe, 15),
            "ROA": _roa_points(roa, 10),
            "PM": _profit_points(margin, 5),
            "RG": _growth_points(revenue_growth, 10, 0.15),
            "EG": _growth_points(earnings_growth, 10),
            "DY": _dividend_points(dividend_yield),
        }
        scores.update(
            _bank_risk_points(row, gross_max=6, net_max=5, capital_max=9, nbfc=True)
        )
    elif model == "Insurance Equity Quality Model":
        solvency = s(row.get("Solvency_Ratio"))
        scores = {
            "PE": _pe_points(pe, 15),
            "PB_ROE": _pb_roe_points(pb, roe, 15),
            "ROE": _roe_points(roe, 20),
            "ROA": _roa_points(roa, 10),
            "PM": _profit_points(margin, 10),
            "RG": _growth_points(revenue_growth, 10, 0.15),
            "EG": _growth_points(earnings_growth, 10),
            "DY": _dividend_points(dividend_yield),
            "SOLVENCY": 5.0 if solvency is not None and solvency >= 1.5 else 0.0,
        }
    else:
        # Capital-markets and unknown financial firms use earnings-quality
        # inputs. Unknown industries are separately capped by the model gate.
        scores = {
            "PE": _pe_points(pe, 15),
            "PB_ROE": _pb_roe_points(pb, roe, 15),
            "ROE": _roe_points(roe, 20),
            "ROA": _roa_points(roa, 10),
            "PM": _profit_points(margin, 15),
            "RG": _growth_points(revenue_growth, 10, 0.15),
            "EG": _growth_points(earnings_growth, 10),
            "DY": _dividend_points(dividend_yield),
        }
    return scores if return_components else sum(scores.values())


def score_real_estate(row, return_components=False):
    """Asset, leverage, profitability, and growth model for real-estate firms."""
    s = StockScorer.safe_float
    scores = {}

    pe = s(row.get("PE_Ratio"))
    scores["PE"] = _pe_points(pe, 15)

    pb = s(row.get("PB_Ratio"))
    roe = s(row.get("ROE"))
    scores["PB_ROE"] = _pb_roe_points(pb, roe, 15)

    debt_to_equity = s(row.get("Debt_to_Equity"))
    scores["DE"] = 0 if debt_to_equity is None or debt_to_equity < 0 else 15 if debt_to_equity < 30 else 12 if debt_to_equity < 70 else 7 if debt_to_equity < 120 else 3

    current_ratio = s(row.get("Current_Ratio"))
    scores["CR"] = 0 if current_ratio is None or current_ratio < 0 else 10 if current_ratio >= 1.5 else 7 if current_ratio >= 1.0 else 3

    margin = s(row.get("Profit_Margin"))
    scores["PM"] = _profit_points(margin, 15)

    revenue_growth = s(row.get("Revenue_Growth"))
    scores["RG"] = _growth_points(revenue_growth, 15)

    earnings_growth = s(row.get("Earnings_Growth"))
    scores["EG"] = _growth_points(earnings_growth, 15)
    return scores if return_components else sum(scores.values())


def score_fundamentals(
    row,
    sector_relative=None,
    sector_relative_weight=0.5,
    return_components=False,
):
    """Fundamental quality/valuation score, raw max = 100.

    ``sector_relative`` (optional) is a mapping of column -> percentile-based
    score (see ``sector_relative_fund_scores``) for the metrics that vary a lot
    by sector. When present and not NaN for a given metric, it is blended with
    the fixed absolute-threshold score below (weight = ``sector_relative_weight``),
    so e.g. a PE of 18 is judged partly against other same-sector names rather
    than a single universal bar that treats IT and Utilities identically.
    """
    s = StockScorer.safe_float
    scores = {}

    pe = s(row.get("PE_Ratio"))
    scores["PE"] = _pe_points(pe, 15)

    pb = s(row.get("PB_Ratio"))
    if pb is None or pb <= 0: scores["PB"] = 0
    elif pb < 2: scores["PB"] = 8
    elif pb < 4: scores["PB"] = 6
    elif pb < 8: scores["PB"] = 4
    else: scores["PB"] = 2

    roe = s(row.get("ROE"))
    scores["ROE"] = _roe_points(roe, 15)

    roa = s(row.get("ROA"))
    scores["ROA"] = _roa_points(roa, 5)

    de = s(row.get("Debt_to_Equity"))  # yfinance reports this as a percentage
    if de is None or de < 0: scores["DE"] = 0
    elif de < 30: scores["DE"] = 10
    elif de < 70: scores["DE"] = 8
    elif de < 150: scores["DE"] = 5
    else: scores["DE"] = 2

    cr = s(row.get("Current_Ratio"))
    if cr is None or cr < 0: scores["CR"] = 0
    elif cr >= 2: scores["CR"] = 7
    elif cr >= 1.2: scores["CR"] = 5
    elif cr >= 1: scores["CR"] = 4
    else: scores["CR"] = 2

    pm = s(row.get("Profit_Margin"))
    scores["PM"] = _profit_points(pm, 10)

    rg = s(row.get("Revenue_Growth"))
    scores["RG"] = _growth_points(rg, 10)

    eg = s(row.get("Earnings_Growth"))
    scores["EG"] = _growth_points(eg, 10)

    dy = s(
        row.get("Dividend_Yield_Ratio")
        if row.get("Dividend_Yield_Ratio") is not None
        else row.get("Dividend_Yield")
    )
    if dy is None or dy <= 0: scores["DY"] = 0
    elif dy >= 0.03: scores["DY"] = 5
    elif dy >= 0.015: scores["DY"] = 4
    else: scores["DY"] = 3

    ev = s(row.get("EV_EBITDA"))
    if ev is None or ev <= 0: scores["EV"] = 0
    elif ev < 10: scores["EV"] = 5
    elif ev < 18: scores["EV"] = 4
    elif ev < 30: scores["EV"] = 2
    else: scores["EV"] = 1

    if sector_relative is not None:
        weight = max(0.0, min(1.0, StockScorer.safe_float(sector_relative_weight, 0.5) or 0.0))
        if weight > 0:
            for key, column in SECTOR_RELATIVE_COLUMN_BY_KEY.items():
                sector_score = sector_relative.get(column) if hasattr(sector_relative, "get") else None
                if sector_score is None or (isinstance(sector_score, float) and pd.isna(sector_score)):
                    continue
                scores[key] = round(scores[key] * (1 - weight) + sector_score * weight, 2)

    # Invalid valuation/domain observations remain zero even if an older cache
    # or external caller supplies a peer score for them.
    if pe is not None and pe <= 0:
        scores["PE"] = 0.0
    if pb is not None and pb <= 0:
        scores["PB"] = 0.0
    if ev is not None and ev <= 0:
        scores["EV"] = 0.0
    if de is not None and de < 0:
        scores["DE"] = 0.0
    if cr is not None and cr < 0:
        scores["CR"] = 0.0

    # Hard guards are applied after peer-relative blending. A bad or suspect
    # absolute value must not become attractive merely because its peers are
    # similarly weak or because an extreme observation wins a percentile rank.
    if pe is not None and 0 < pe < 1:
        scores["PE"] = min(scores["PE"], 4.5)
    if pb is not None and 0 < pb < 2 and (roe is None or roe < 0.10):
        scores["PB"] = min(scores["PB"], 4.0)
    if roe is not None and abs(roe) > 1:
        scores["ROE"] = min(scores["ROE"], 4.5)
    if roa is not None and abs(roa) > 0.5:
        scores["ROA"] = min(scores["ROA"], 1.0)
    if pm is not None and abs(pm) > 1:
        scores["PM"] = min(scores["PM"], 3.0)
    if rg is not None and (rg > 2 or rg <= -1):
        scores["RG"] = min(scores["RG"], 3.0)
    if eg is not None and (eg > 2 or eg <= -1):
        scores["EG"] = min(scores["EG"], 3.0)

    # Value-trap guard: a low PE/PB only reflects genuine undervaluation if the
    # business isn't actively shrinking. When BOTH revenue and earnings are
    # contracting, cap the reward for a "cheap" multiple - it's priced that way
    # for a reason, not because the market is missing a bargain. Applied after
    # sector-relative blending so it's a hard final cap regardless of how the
    # stock compares to its (possibly also-struggling) sector peers.
    is_shrinking = (eg is not None and eg < 0) and (rg is not None and rg < 0)
    if is_shrinking:
        if pe is not None and 0 < pe < 15:
            scores["PE"] = min(scores["PE"], 8)
        if pb is not None and 0 < pb < 2:
            scores["PB"] = min(scores["PB"], 5)

    return scores if return_components else sum(scores.values())
