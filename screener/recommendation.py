"""Pure, versioned recommendation finalization.

Evidence producers may propose scores and weights, but only this module turns
them into a decision score, recommendation, and ranks.  Keeping that policy in
one place prevents a later enrichment stage from bypassing an earlier gate.
"""

from __future__ import annotations

import json
from typing import Iterable

import numpy as np
import pandas as pd

from .numeric import round_half_up, round_series_half_up


RATING_ORDER = {
    "STRONG BUY": 0,
    "BUY": 1,
    "HOLD": 2,
    "REDUCE": 3,
    "SELL": 4,
    "UNRATED": 5,
}


def _safe_float(value, default=None):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _as_bool(value, default=False):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
    return bool(value)


def _bool_series(frame, column, default=False):
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=bool)
    return frame[column].map(lambda value: _as_bool(value, default)).astype(bool)


def _numeric_series(frame, column, default=np.nan):
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _dedupe(items: Iterable[str]):
    seen = set()
    result = []
    for item in items:
        normalized = str(item).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _json_reasons(reasons):
    return json.dumps(reasons, separators=(",", ":"), ensure_ascii=True)


def rating_from_score(score):
    score = _safe_float(score)
    if score is None:
        return "UNRATED"
    if score >= 70:
        return "STRONG BUY"
    if score >= 60:
        return "BUY"
    if score >= 50:
        return "HOLD"
    if score >= 40:
        return "REDUCE"
    return "SELL"


def _rating_ceiling(score):
    """Highest score that stays inside the score's current rating class."""

    score = _safe_float(score)
    if score is None:
        return np.nan
    if score >= 70:
        return 100.0
    if score >= 60:
        return 69.99
    if score >= 50:
        return 59.99
    if score >= 40:
        return 49.99
    return 39.99


# Short, stable slugs for the single most decision-relevant gate on a row.
# Ordered most severe first: the first match becomes ``Primary_Gate``.
PRIMARY_GATE_PATTERNS = (
    ("core score unavailable", "NO_SCORE"),
    ("price bar behind expected session", "STALE_PRICE_BAR"),
    ("stale fundamental fallback", "STALE_FUNDAMENTALS"),
    ("insufficient fundamental data", "LOW_DATA_QUALITY"),
    ("factor coverage insufficient", "LOW_FACTOR_COVERAGE"),
    ("coverage insufficient", "LOW_COVERAGE"),
    ("specialized", "SPECIALIST_MODEL_REQUIRED"),
    ("multiple fundamental data anomalies", "DATA_ANOMALY"),
    ("confirmed trend breakdown", "TREND_BREAKDOWN"),
    ("below MA200", "BELOW_MA200"),
    ("MA200", "MA200_TREND"),
    ("relative strength", "WEAK_RELATIVE_STRENGTH"),
    ("quality percentile", "LOW_QUALITY"),
    ("liquidity", "ILLIQUID"),
    ("regime", "MARKET_REGIME"),
)


def primary_gate(failures):
    """Reduce a failure list to one stable, sortable reason code.

    Patterns are scanned in severity order, not in the order the failures
    happen to appear: a row that is both low-quality and unscorable should
    report the unscorable reason regardless of which gate ran first.
    """
    lowered = [str(reason).lower() for reason in failures]
    for needle, slug in PRIMARY_GATE_PATTERNS:
        needle = needle.lower()
        if any(needle in reason for reason in lowered):
            return slug
    return "NONE" if not failures else "OTHER"


class RecommendationPolicy:
    """Finalize evidence into internally consistent decisions and ranks."""

    def __init__(self, config):
        self.config = config

    # ------------------------------------------------------------------
    # Model 5.0 gates
    # ------------------------------------------------------------------
    def _factor_gate_failures(self, row):
        """Trend, factor-percentile, liquidity and regime gates for Model 5.0.

        Returns ``(buy_failures, strong_failures)`` covering only the gates that
        differ from the 4.x policy; the shared data-integrity gates are applied
        by the caller so both models fail closed on the same evidence problems.
        """
        buy_failures = []
        strong_failures = []
        config = self.config

        price = _safe_float(row.get("Technical_Price"))
        ma200 = _safe_float(row.get("MA200"))
        ma200_slope = _safe_float(row.get("MA200_Slope_Pct"))
        ma50 = _safe_float(row.get("MA50"))

        # --- long-term trend, with a tolerance band ---------------------
        # An exact boundary makes a stock oscillating around its average flip
        # its rating daily. The band costs a little precision and buys rating
        # stability, which is what makes the label usable.
        if _as_bool(getattr(config, "REQUIRE_MA200_TREND_FOR_BUY", True), True):
            tolerance = float(getattr(config, "BUY_MA200_TOLERANCE", 0.98))
            if price is None or price <= 0 or ma200 is None or ma200 <= 0:
                buy_failures.append("price/MA200 unavailable")
            elif price < tolerance * ma200:
                buy_failures.append(
                    f"price below MA200 tolerance band ({tolerance:.0%})"
                )
            slope_floor = float(getattr(config, "BUY_MIN_MA200_SLOPE_PCT", 0.0))
            if ma200_slope is None:
                buy_failures.append("MA200 slope unavailable")
            elif ma200_slope < slope_floor:
                buy_failures.append("MA200 slope falling")

            # Confirmed breakdown is the stricter exit condition. Requiring
            # persistence, a falling average AND weak relative strength keeps a
            # single dip through the line from revoking a rating that a rebound
            # would restore the next session.
            streak = _safe_float(row.get("Below_MA200_Streak"))
            rs_6m = _safe_float(row.get("RS_Market_6M_Pct"))
            confirm = float(getattr(config, "BREAKDOWN_CONFIRM_SESSIONS", 10))
            if (
                streak is not None
                and streak >= confirm
                and ma200_slope is not None
                and ma200_slope < 0
                and rs_6m is not None
                and rs_6m < 0
            ):
                buy_failures.append("confirmed trend breakdown below MA200")

        # --- relative strength ------------------------------------------
        rs_floor_6m = float(getattr(config, "BUY_MIN_RS_6M", 0.0))
        rs_market_6m = _safe_float(row.get("RS_Market_6M_Pct"))
        rs_sector_6m = _safe_float(row.get("RS_Sector_6M_Pct"))
        if rs_market_6m is None:
            buy_failures.append("market relative strength unavailable")
        elif rs_market_6m <= rs_floor_6m:
            buy_failures.append("6M market relative strength not positive")
        # Sector relative strength is unavailable for thin sectors by design.
        # Only fail on an observed negative reading, never on absence.
        if rs_sector_6m is not None and rs_sector_6m <= rs_floor_6m:
            buy_failures.append("6M sector relative strength not positive")

        # --- factor percentile floors ------------------------------------
        quality_pct = _safe_float(row.get("Quality_Percentile"))
        buy_quality_floor = float(getattr(config, "BUY_MIN_QUALITY_PCT", 40.0))
        if quality_pct is None:
            buy_failures.append("quality percentile unavailable")
        elif quality_pct < buy_quality_floor:
            buy_failures.append("quality percentile below BUY floor")

        for block in ("Quality", "Growth", "Value", "Momentum", "Risk"):
            column = f"{block}_Coverage_Sufficient"
            if column in row.index and not _as_bool(row.get(column), True):
                buy_failures.append(f"{block.lower()} factor coverage insufficient")

        # Model 5.0 raises the BUY evidence floors. These are checked
        # numerically rather than through the 4.x eligibility booleans, which
        # were computed against the looser thresholds.
        fund_coverage = _safe_float(row.get("Fundamental_Coverage"))
        fund_floor = float(
            getattr(config, "FACTOR_FUNDAMENTAL_MIN_COVERAGE_FOR_BUY", 0.70)
        )
        if fund_coverage is None:
            buy_failures.append("fundamental coverage unavailable")
        elif fund_coverage < fund_floor:
            buy_failures.append("fundamental coverage insufficient for BUY")
        tech_coverage = _safe_float(row.get("Technical_Coverage"))
        tech_floor = float(
            getattr(config, "FACTOR_TECHNICAL_MIN_COVERAGE_FOR_BUY", 0.90)
        )
        if tech_coverage is None:
            buy_failures.append("technical coverage unavailable")
        elif tech_coverage < tech_floor:
            buy_failures.append("technical coverage insufficient for BUY")

        # --- execution liquidity as a BUY requirement ---------------------
        # An illiquid name can be excellent research and still be unsuitable as
        # a published BUY. Research_Rating stays uncapped so the research view
        # is not lost.
        if _as_bool(getattr(config, "REQUIRE_LIQUIDITY_FOR_BUY", True), True):
            if "Portfolio_Actionable" in row.index and not _as_bool(
                row.get("Portfolio_Actionable"), False
            ):
                buy_failures.append("insufficient execution liquidity for target size")

        # --- STRONG BUY ---------------------------------------------------
        strong_quality_floor = float(
            getattr(config, "STRONG_BUY_MIN_QUALITY_PCT", 70.0)
        )
        if quality_pct is not None and quality_pct < strong_quality_floor:
            strong_failures.append("quality percentile below STRONG BUY floor")
        growth_pct = _safe_float(row.get("Growth_Percentile"))
        if growth_pct is None:
            strong_failures.append("growth percentile unavailable")
        elif growth_pct < float(getattr(config, "STRONG_BUY_MIN_GROWTH_PCT", 60.0)):
            strong_failures.append("growth percentile below STRONG BUY floor")
        momentum_pct = _safe_float(row.get("Momentum_Percentile"))
        if momentum_pct is None:
            strong_failures.append("momentum percentile unavailable")
        elif momentum_pct < float(
            getattr(config, "STRONG_BUY_MIN_MOMENTUM_PCT", 70.0)
        ):
            strong_failures.append("momentum percentile below STRONG BUY floor")

        if _as_bool(
            getattr(config, "STRONG_BUY_REQUIRE_MA50_ABOVE_MA200", True), True
        ):
            if ma50 is None or ma200 is None or price is None:
                strong_failures.append("MA50/MA200 stack unavailable")
            elif not (price > ma50 > ma200):
                strong_failures.append("price/MA50/MA200 not stacked bullishly")
        if ma200_slope is not None and ma200_slope <= 0:
            strong_failures.append("MA200 not rising")

        rs_market_12m = _safe_float(row.get("RS_Market_12M_Pct"))
        if rs_market_12m is None:
            strong_failures.append("12M relative strength unavailable")
        elif rs_market_12m <= float(getattr(config, "STRONG_BUY_MIN_RS_12M", 0.0)):
            strong_failures.append("12M relative strength not positive")

        # --- market regime overlay ----------------------------------------
        # Deployment conviction only. The factor scores and the research rank
        # are untouched, so the underlying ranking stays fully visible.
        regime = _safe_text(row.get("Market_Regime")).upper()
        if regime == "RISK_OFF":
            if _as_bool(
                getattr(config, "REGIME_RISK_OFF_DISABLES_STRONG_BUY", True), True
            ):
                strong_failures.append("market regime risk-off: STRONG BUY disabled")
            floor = float(getattr(config, "REGIME_RISK_OFF_MIN_MOMENTUM_PCT", 90.0))
            if momentum_pct is None or momentum_pct < floor:
                buy_failures.append(
                    "market regime risk-off: BUY requires top-decile momentum"
                )
        elif regime == "NEUTRAL":
            floor = float(
                getattr(
                    config,
                    "REGIME_NEUTRAL_MIN_MOMENTUM_PCT_FOR_STRONG_BUY",
                    85.0,
                )
            )
            if momentum_pct is None or momentum_pct < floor:
                strong_failures.append(
                    "market regime neutral: STRONG BUY requires exceptional momentum"
                )

        return buy_failures, strong_failures

    def _blend_evidence(self, frame):
        base = _numeric_series(frame, "Combined_Score")
        frame["Core_Score"] = round_series_half_up(base, 2)

        dcf_score_column = (
            "DCF_Evidence_Score"
            if "DCF_Evidence_Score" in frame
            else "DCF_Valuation_Score"
        )
        dcf_score = _numeric_series(frame, dcf_score_column).clip(0, 100)
        dcf_eligible = _bool_series(frame, "DCF_Blend_Eligible")
        default_dcf_weight = max(
            0.0,
            min(
                1.0,
                float(getattr(self.config, "REVERSE_DCF_RANKING_WEIGHT", 0.10)),
            ),
        )
        dcf_weight = _numeric_series(
            frame, "DCF_Blend_Weight", default_dcf_weight
        ).fillna(default_dcf_weight).clip(0, 1)
        dcf_applied = dcf_eligible & base.notna() & dcf_score.notna() & dcf_weight.gt(0)
        after_dcf = base.copy()
        # DCF score 50 is explicitly neutral. Apply centered evidence so a
        # neutral valuation is a true no-op, favorable evidence always adds,
        # and adverse evidence always subtracts by the same magnitude. A
        # convex average with the core would make even a 50.01 "favorable"
        # signal reduce every core score above 50.
        after_dcf.loc[dcf_applied] = (
            base.loc[dcf_applied]
            + dcf_weight.loc[dcf_applied]
            * (dcf_score.loc[dcf_applied] - 50.0)
        ).clip(0.0, 100.0)
        # Quantize each declared stage once, then use that exported value as
        # the next stage's input so CSV arithmetic is exactly reproducible.
        after_dcf = round_series_half_up(after_dcf, 4)
        frame["DCF_Blend_Applied"] = dcf_applied
        frame["DCF_Blend_Weight_Applied"] = dcf_weight.where(dcf_applied, 0.0)
        frame["DCF_Evidence_Contribution"] = round_series_half_up(
            after_dcf - base, 4
        )
        frame["Score_After_DCF"] = round_series_half_up(after_dcf, 4)

        transcript_score = _numeric_series(
            frame, "Transcript_Effective_Score"
        ).clip(0, 100)
        transcript_eligible = _bool_series(frame, "Transcript_Blend_Eligible")
        default_transcript_weight = max(
            0.0,
            min(
                1.0,
                float(getattr(self.config, "TRANSCRIPT_SENTIMENT_WEIGHT", 0.15)),
            ),
        )
        transcript_weight = _numeric_series(
            frame, "Transcript_Blend_Weight", default_transcript_weight
        ).fillna(default_transcript_weight).clip(0, 1)
        transcript_applied = (
            transcript_eligible
            & after_dcf.notna()
            & transcript_score.notna()
            & transcript_weight.gt(0)
        )
        score_used = transcript_score.copy()
        # Like DCF, transcript score 50 is neutral. Default policy applies only
        # the negative half of that centered signal; a positive 60 must not
        # reduce an 80 core simply because a convex average regresses to 50.
        centered_delta = transcript_weight * (score_used - 50.0)
        transcript_delta = np.minimum(centered_delta, 0.0)
        no_promotion = transcript_applied & centered_delta.gt(0)

        evidence = after_dcf.copy()
        evidence.loc[transcript_applied] = (
            after_dcf.loc[transcript_applied]
            + transcript_delta.loc[transcript_applied]
        ).clip(0.0, 100.0)
        evidence = round_series_half_up(evidence, 4)
        frame["Transcript_Blend_Applied"] = transcript_applied
        frame["Transcript_Blend_Weight_Applied"] = transcript_weight.where(
            transcript_applied, 0.0
        )
        frame["Transcript_Effective_Score_Used"] = score_used.where(
            transcript_applied, np.nan
        )
        frame["Transcript_Evidence_Contribution"] = round_series_half_up(
            evidence - after_dcf, 4
        )
        applied_direction = pd.Series("not_applied", index=frame.index, dtype=object)
        applied_direction.loc[transcript_applied] = "neutral"
        applied_direction.loc[
            transcript_applied & frame["Transcript_Evidence_Contribution"].lt(0)
        ] = "downside"
        applied_direction.loc[
            transcript_applied & frame["Transcript_Evidence_Contribution"].gt(0)
        ] = "upside"
        frame["Transcript_Applied_Direction"] = applied_direction
        frame["Transcript_No_Promotion"] = no_promotion
        frame["Transcript_Pre_Blend_Rating_Ceiling"] = after_dcf.map(
            _rating_ceiling
        )
        frame["Evidence_Score"] = round_series_half_up(evidence, 2)
        return frame

    @staticmethod
    def _coverage_failure(row, column, reason):
        if column not in row.index:
            return None
        value = row.get(column)
        try:
            if value is None or pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return None if _as_bool(value) else reason

    def _gate_failures(self, row):
        buy_failures = []
        strong_failures = []
        # Model 5.0 replaces the MA50/ADX trend gates with an MA200 trend gate,
        # relative strength and factor percentiles. The data-integrity gates
        # below are shared: both models must fail closed on the same evidence
        # problems.
        factor_model = _as_bool(row.get("Factor_Model_Applied"), False)

        if _safe_float(row.get("Combined_Score")) is None:
            buy_failures.append("core score unavailable")

        coverage_checks = (
            ("Coverage_Eligible", "overall required coverage insufficient"),
            (
                "Fundamental_Coverage_Eligible",
                "fundamental required coverage insufficient",
            ),
            (
                "Technical_Coverage_Eligible",
                "technical required coverage insufficient",
            ),
        )
        for column, reason in coverage_checks:
            failure = self._coverage_failure(row, column, reason)
            if failure:
                buy_failures.append(failure)

        if _safe_text(row.get("Data_Quality")).upper() == "LOW":
            buy_failures.append("insufficient fundamental data")

        if _as_bool(row.get("Specialized_Fundamental_Model_Required")):
            buy_failures.append("sector requires specialized fundamental model")
        if _as_bool(row.get("Fund_Data_Stale")):
            buy_failures.append("stale fundamental fallback")

        # A price bar behind the expected completed session makes this row's
        # trend, returns and peer percentiles incomparable with the rest of the
        # cross-section, so it must not carry BUY conviction that day. The row
        # is still scored and published -- excluding it outright would discard
        # most of the universe whenever the vendor has a session gap.
        if _as_bool(
            getattr(self.config, "REQUIRE_ALIGNED_PRICE_BAR_FOR_BUY", True), True
        ) and "Price_Bar_Aligned" in row.index:
            if not _as_bool(row.get("Price_Bar_Aligned"), True):
                sessions_behind = _safe_float(row.get("Price_Bar_Session_Lag"))
                detail = (
                    f" ({int(sessions_behind)} session(s) behind)"
                    if sessions_behind
                    else ""
                )
                buy_failures.append(f"price bar behind expected session{detail}")

        anomaly_reason = _safe_text(row.get("Fundamental_Anomaly_Reason"))
        anomaly_parts = [part.strip() for part in anomaly_reason.split(",") if part.strip()]
        anomaly_count = _safe_float(row.get("Fundamental_Anomaly_Count"))
        if anomaly_count is None:
            anomaly_count = len(anomaly_parts)
            if not anomaly_count and _as_bool(row.get("Fundamental_Anomaly")):
                anomaly_count = 1
        if anomaly_count >= 2:
            buy_failures.append("multiple fundamental data anomalies")

        specialized_quality_present = "Specialized_Quality_Eligible" in row.index
        specialized_quality_eligible = _as_bool(
            row.get("Specialized_Quality_Eligible"), True
        )
        dedicated_model = _safe_text(row.get("Fundamental_Model")) in {
            "Bank Equity Quality Model",
            "NBFC Equity Quality Model",
            "Capital Markets Earnings Quality Model",
            "Insurance Equity Quality Model",
            "Financial Services Data-Limited Model",
        }
        if specialized_quality_present and dedicated_model and not specialized_quality_eligible:
            # NPA/CAR/solvency are required here but never collected, so this
            # gate currently bars every financial from BUY. Model 5.0 can
            # instead accept its statement-based financial quality template --
            # which is fully covered -- and keep the regulatory requirement for
            # STRONG BUY only. Opt-in, so the default stays fail-closed.
            statement_quality_ok = (
                factor_model
                and _as_bool(
                    getattr(
                        self.config,
                        "FACTOR_FINANCIAL_STATEMENT_QUALITY_SUFFICIENT",
                        False,
                    )
                )
                and _as_bool(row.get("Quality_Coverage_Sufficient"), False)
            )
            if statement_quality_ok:
                strong_failures.append(
                    "specialized regulatory coverage insufficient"
                )
            else:
                buy_failures.append("specialized regulatory coverage insufficient")

        # MA50 is calculated from adjusted closes, so its gate must compare
        # against the adjusted technical close rather than raw quote scale.
        price = _safe_float(row.get("Technical_Price"))
        ma50 = _safe_float(row.get("MA50"))
        ma50_slope = _safe_float(row.get("MA50_Slope_Pct"))
        return_3m = _safe_float(row.get("Pct_Change_3M"))
        require_uptrend = _as_bool(
            getattr(self.config, "REQUIRE_UPTREND_FOR_BUY", True), True
        ) and not factor_model
        if require_uptrend:
            if price is None or price <= 0 or ma50 is None:
                buy_failures.append("price/MA50 unavailable")
            elif price <= ma50:
                buy_failures.append("price not above MA50")
            slope_floor = float(getattr(self.config, "BUY_MIN_MA50_SLOPE", 0.0))
            if ma50_slope is None:
                buy_failures.append("MA50 slope unavailable")
            elif ma50_slope < slope_floor:
                buy_failures.append("MA50 falling")
            return_floor = float(getattr(self.config, "BUY_MIN_3M_RETURN", 0.0))
            if return_3m is None:
                buy_failures.append("3M return unavailable")
            elif return_3m <= return_floor:
                buy_failures.append("3M return not positive")

        if factor_model:
            factor_buy, factor_strong = self._factor_gate_failures(row)
            buy_failures.extend(factor_buy)
            strong_failures.extend(factor_strong)

        buy_failures = _dedupe(buy_failures)
        strong_failures.extend(buy_failures)

        if not factor_model:
            # 4.x high-conviction evidence. Model 5.0 expresses the same intent
            # through growth/momentum percentiles and the MA200 stack, so
            # applying both would double-count the trend requirement.
            revenue_growth = _safe_float(row.get("Revenue_Growth"))
            earnings_growth = _safe_float(row.get("Earnings_Growth"))
            growth_floor = float(
                getattr(self.config, "STRONG_BUY_MIN_GROWTH", 0.05)
            )
            if revenue_growth is None and earnings_growth is None:
                strong_failures.append("growth unavailable")
            elif not (
                (revenue_growth is not None and revenue_growth >= growth_floor)
                or (
                    earnings_growth is not None
                    and earnings_growth >= growth_floor
                )
            ):
                strong_failures.append("growth below threshold")

            adx = _safe_float(row.get("ADX_14"))
            plus_di = _safe_float(row.get("ADX_Plus_DI"))
            minus_di = _safe_float(row.get("ADX_Minus_DI"))
            adx_floor = float(getattr(self.config, "STRONG_BUY_MIN_ADX", 20.0))
            if adx is None:
                strong_failures.append("ADX unavailable")
            elif adx < adx_floor:
                strong_failures.append("ADX below threshold")
            if plus_di is None or minus_di is None:
                strong_failures.append("directional indicators unavailable")
            elif plus_di <= minus_di:
                strong_failures.append("positive DI not above negative DI")

            technical_score = _safe_float(row.get("Technical_Score"))
            technical_floor = float(
                getattr(self.config, "STRONG_BUY_MIN_TECH_SCORE", 55.0)
            )
            if technical_score is None:
                strong_failures.append("technical score unavailable")
            elif technical_score < technical_floor:
                strong_failures.append("technical score below threshold")

        fundamental_coverage = _safe_float(row.get("Fundamental_Coverage"))
        strong_fund_coverage = float(
            getattr(
                self.config,
                "FUNDAMENTAL_MIN_COVERAGE_FOR_STRONG_BUY",
                0.75,
            )
        )
        if (
            fundamental_coverage is not None
            and fundamental_coverage < strong_fund_coverage
        ):
            strong_failures.append("fundamental coverage below STRONG BUY threshold")
        technical_coverage = _safe_float(row.get("Technical_Coverage"))
        strong_technical_coverage = float(
            getattr(
                self.config,
                "TECHNICAL_MIN_COVERAGE_FOR_STRONG_BUY",
                0.90,
            )
        )
        if (
            technical_coverage is not None
            and technical_coverage < strong_technical_coverage
        ):
            strong_failures.append("technical coverage below STRONG BUY threshold")

        if specialized_quality_present and not specialized_quality_eligible:
            detail = _safe_text(row.get("Specialized_Quality_Gate_Reason"))
            strong_failures.append(
                "specialized quality ineligible" + (f": {detail}" if detail else "")
            )
        if anomaly_count:
            strong_failures.append(
                "fundamental anomaly" + (f": {anomaly_reason}" if anomaly_reason else "")
            )

        if (
            _as_bool(
                getattr(
                    self.config,
                    "CAP_STRONG_BUY_ON_REPORTED_NEGATIVE_FCF",
                    True,
                ),
                True,
            )
            and _safe_text(row.get("DCF_Status")) == "negative_fcf"
        ):
            strong_failures.append(
                "reported non-positive FCF requires normalization review"
            )

        if _as_bool(
            getattr(self.config, "REQUIRE_TRANSCRIPT_FOR_STRONG_BUY", False)
        ):
            if "Transcript_Quality_Eligible" in row.index:
                transcript_quality = _as_bool(row.get("Transcript_Quality_Eligible"))
            else:
                transcript_quality = (
                    _safe_text(row.get("Transcript_Quality_Gate")).lower()
                    == "passed"
                )
            if not transcript_quality:
                strong_failures.append("fresh quality transcript required")

        return buy_failures, _dedupe(strong_failures)

    def _apply_decision_policy(self, frame):
        decision_scores = []
        ratings = []
        evidence_ratings = []
        ceilings = []
        buy_eligible_values = []
        strong_eligible_values = []
        trend_confirmed_values = []
        buy_reason_json = []
        strong_reason_json = []
        all_reason_json = []
        buy_reason_text = []
        strong_reason_text = []
        cap_reason_text = []
        cap_applied_values = []
        transcript_cap_values = []

        for _, row in frame.iterrows():
            evidence_score = _safe_float(row.get("Evidence_Score"))
            buy_failures, strong_failures = self._gate_failures(row)
            policy_failures = list(strong_failures)
            ceiling = 100.0

            if buy_failures:
                ceiling = min(ceiling, 59.99)
            elif strong_failures:
                ceiling = min(ceiling, 69.99)

            buy_failures = _dedupe(buy_failures)
            strong_failures = _dedupe(strong_failures)
            policy_failures = _dedupe(policy_failures)
            if evidence_score is None:
                decision_score = np.nan
                cap_applied = False
            else:
                decision_score = round_half_up(min(evidence_score, ceiling), 2)
                cap_applied = decision_score < round_half_up(evidence_score, 2)

            decision_scores.append(decision_score)
            ratings.append(rating_from_score(decision_score))
            evidence_ratings.append(rating_from_score(evidence_score))
            ceilings.append(ceiling)
            buy_eligible_values.append(not buy_failures)
            strong_eligible_values.append(not strong_failures)
            # Trend confirmation is specifically the medium-term/ADX subset;
            # other coverage/fundamental gates do not change this diagnostic.
            trend_confirmed_values.append(
                not any(
                    reason
                    in {
                        "price/MA50 unavailable",
                        "price not above MA50",
                        "MA50 slope unavailable",
                        "MA50 falling",
                        "3M return unavailable",
                        "3M return not positive",
                        "ADX unavailable",
                        "ADX below threshold",
                        "directional indicators unavailable",
                        "positive DI not above negative DI",
                    }
                    for reason in strong_failures
                )
            )
            buy_reason_json.append(_json_reasons(buy_failures))
            strong_reason_json.append(_json_reasons(strong_failures))
            all_reason_json.append(_json_reasons(policy_failures))
            buy_reason_text.append("; ".join(buy_failures))
            strong_reason_text.append("; ".join(strong_failures))
            cap_reason_text.append("; ".join(policy_failures) if cap_applied else "")
            cap_applied_values.append(cap_applied)
            transcript_cap_values.append(
                bool(
                    cap_applied
                    and "fresh quality transcript required" in strong_failures
                    and evidence_score is not None
                    and evidence_score >= 70.0
                )
            )

        # --- separated views of one decision ------------------------------
        # Collapsing every gate failure onto an identical 59.99 creates a large
        # artificial cluster and destroys the ordering *within* it. Publishing
        # the research view, the policy-eligible view and the execution view as
        # separate fields keeps the decision auditable and lets capped rows keep
        # a meaningful relative order.
        frame["Research_Rating"] = evidence_ratings
        frame["Policy_Eligible_Rating"] = ratings
        frame["Primary_Gate"] = [
            primary_gate(json.loads(value)) for value in all_reason_json
        ]
        frame["Gate_Severity"] = [
            len(json.loads(value)) for value in all_reason_json
        ]
        # 0 = clears every gate, 1 = BUY-eligible only, 2 = policy-capped,
        # 3 = unscorable. Sorting on this keeps eligible names ahead of capped
        # ones without pretending their scores are comparable.
        frame["Eligibility_Class"] = [
            3
            if decision is None or (isinstance(decision, float) and np.isnan(decision))
            else 0
            if strong_ok
            else 1
            if buy_ok
            else 2
            for decision, buy_ok, strong_ok in zip(
                decision_scores, buy_eligible_values, strong_eligible_values
            )
        ]
        if "Portfolio_Actionable" in frame:
            frame["Execution_Status"] = np.where(
                _bool_series(frame, "Portfolio_Actionable"),
                "ACTIONABLE",
                "NOT_ACTIONABLE",
            )
        else:
            frame["Execution_Status"] = "UNKNOWN"

        frame["Evidence_Rating"] = evidence_ratings
        frame["Decision_Score_Ceiling"] = ceilings
        frame["Decision_Score"] = decision_scores
        frame["Decision_Rating"] = ratings
        frame["Final_Score"] = frame["Decision_Score"]
        frame["Rating"] = frame["Decision_Rating"]
        # Compatibility alias.  Liquidity now runs before this policy so Model
        # 5.0 can use execution suitability as a gate; at that earlier stage no
        # final Rating exists yet.  The policy is the sole rating writer and
        # must therefore refresh the alias after every finalization/replay.
        frame["Investment_Rating"] = frame["Decision_Rating"]
        frame["Buy_Eligible"] = buy_eligible_values
        frame["Strong_Buy_Eligible"] = strong_eligible_values
        frame["Trend_Confirmed"] = trend_confirmed_values
        frame["Buy_Gate_Failures"] = buy_reason_json
        frame["Strong_Buy_Gate_Failures"] = strong_reason_json
        frame["Gate_Failures"] = all_reason_json
        frame["Buy_Gate_Failure_Count"] = [
            len(json.loads(value)) for value in buy_reason_json
        ]
        frame["Strong_Buy_Gate_Failure_Count"] = [
            len(json.loads(value)) for value in strong_reason_json
        ]
        frame["Gate_Failure_Count"] = [
            len(json.loads(value)) for value in all_reason_json
        ]
        # Backward-compatible scalar audit columns now contain every failure.
        frame["Buy_Gate_Reason"] = buy_reason_text
        frame["Strong_Buy_Gate_Reason"] = strong_reason_text
        frame["Rating_Capped"] = cap_applied_values
        frame["Rating_Cap_Reason"] = cap_reason_text
        frame["Decision_Cap_Applied"] = cap_applied_values
        frame["Decision_Cap_Reason"] = cap_reason_text
        # Backward-compatible audit column is authored by the same finalizer
        # that actually applies the policy; the evidence enricher cannot know
        # whether the final score needed a STRONG BUY ceiling.
        frame["Transcript_Strong_Buy_Capped"] = transcript_cap_values
        return frame

    def _add_stability_diagnostics(self, frame):
        """Export continuous distances to every categorical decision gate."""

        price = _numeric_series(frame, "Technical_Price")
        ma50 = _numeric_series(frame, "MA50")
        slope = _numeric_series(frame, "MA50_Slope_Pct")
        return_3m = _numeric_series(frame, "Pct_Change_3M")
        revenue_growth = _numeric_series(frame, "Revenue_Growth")
        earnings_growth = _numeric_series(frame, "Earnings_Growth")
        growth = pd.concat([revenue_growth, earnings_growth], axis=1).max(
            axis=1, skipna=True
        )
        growth.loc[revenue_growth.isna() & earnings_growth.isna()] = np.nan
        adx = _numeric_series(frame, "ADX_14")
        plus_di = _numeric_series(frame, "ADX_Plus_DI")
        minus_di = _numeric_series(frame, "ADX_Minus_DI")
        technical = _numeric_series(frame, "Technical_Score")
        fund_coverage = _numeric_series(frame, "Fundamental_Coverage")
        tech_coverage = _numeric_series(frame, "Technical_Coverage")
        evidence = _numeric_series(frame, "Evidence_Score")

        valid_price = price.gt(0) & ma50.gt(0)
        frame["Buy_Price_MA50_Margin_Pct"] = round_series_half_up(
            ((price / ma50) - 1.0).mul(100.0).where(valid_price), 4
        )
        frame["Buy_MA50_Slope_Margin_Pct"] = round_series_half_up(
            slope - float(getattr(self.config, "BUY_MIN_MA50_SLOPE", 0.0)), 4
        )
        frame["Buy_3M_Return_Margin_Pct"] = round_series_half_up(
            return_3m - float(getattr(self.config, "BUY_MIN_3M_RETURN", 0.0)), 4
        )
        frame["Strong_Buy_Growth_Margin_Ratio"] = round_series_half_up(
            growth - float(getattr(self.config, "STRONG_BUY_MIN_GROWTH", 0.05)),
            6,
        )
        frame["Strong_Buy_ADX_Margin"] = round_series_half_up(
            adx - float(getattr(self.config, "STRONG_BUY_MIN_ADX", 20.0)), 4
        )
        frame["Strong_Buy_DI_Margin"] = round_series_half_up(
            plus_di - minus_di, 4
        )
        frame["Strong_Buy_Technical_Score_Margin"] = round_series_half_up(
            technical
            - float(getattr(self.config, "STRONG_BUY_MIN_TECH_SCORE", 55.0)),
            4,
        )
        frame["Buy_Fundamental_Coverage_Margin"] = round_series_half_up(
            fund_coverage
            - float(
                getattr(self.config, "FUNDAMENTAL_MIN_COVERAGE_FOR_BUY", 0.55)
            ),
            6,
        )
        frame["Strong_Buy_Fundamental_Coverage_Margin"] = round_series_half_up(
            fund_coverage
            - float(
                getattr(
                    self.config,
                    "FUNDAMENTAL_MIN_COVERAGE_FOR_STRONG_BUY",
                    0.75,
                )
            ),
            6,
        )
        frame["Buy_Technical_Coverage_Margin"] = round_series_half_up(
            tech_coverage
            - float(
                getattr(self.config, "TECHNICAL_MIN_COVERAGE_FOR_BUY", 0.75)
            ),
            6,
        )
        frame["Strong_Buy_Technical_Coverage_Margin"] = round_series_half_up(
            tech_coverage
            - float(
                getattr(
                    self.config,
                    "TECHNICAL_MIN_COVERAGE_FOR_STRONG_BUY",
                    0.90,
                )
            ),
            6,
        )
        frame["Buy_Score_Margin"] = round_series_half_up(evidence - 60.0, 4)
        frame["Strong_Buy_Score_Margin"] = round_series_half_up(
            evidence - 70.0, 4
        )
        frame["Evidence_Distance_To_Nearest_Rating_Threshold"] = round_series_half_up(
            evidence.map(
                lambda value: (
                    min(abs(value - threshold) for threshold in (40, 50, 60, 70))
                    if value is not None and not pd.isna(value)
                    else np.nan
                )
            ),
            4,
        )
        decision = _numeric_series(frame, "Decision_Score")
        frame["Decision_Distance_To_Nearest_Rating_Threshold"] = (
            round_series_half_up(
                decision.map(
                    lambda value: (
                        min(
                            abs(value - threshold)
                            for threshold in (40, 50, 60, 70)
                        )
                        if value is not None and not pd.isna(value)
                        else np.nan
                    )
                ),
                4,
            )
        )
        frame["Distance_To_Nearest_Rating_Threshold"] = frame[
            "Decision_Distance_To_Nearest_Rating_Threshold"
        ]
        decision_capped = _bool_series(frame, "Decision_Cap_Applied")
        frame["Stability_Rating_Threshold_Distance"] = frame[
            "Decision_Distance_To_Nearest_Rating_Threshold"
        ].where(
            ~decision_capped,
            frame["Evidence_Distance_To_Nearest_Rating_Threshold"],
        )

        diagnostic_bands = (
            (
                "rating score",
                "Stability_Rating_Threshold_Distance",
                float(getattr(self.config, "BORDERLINE_SCORE_BAND", 1.0)),
                "rating",
            ),
            (
                "price vs MA50",
                "Buy_Price_MA50_Margin_Pct",
                float(
                    getattr(
                        self.config, "BORDERLINE_PRICE_MA50_PCT_BAND", 1.0
                    )
                ),
                "buy",
            ),
            (
                "MA50 slope",
                "Buy_MA50_Slope_Margin_Pct",
                float(
                    getattr(
                        self.config, "BORDERLINE_MA50_SLOPE_PCT_BAND", 0.25
                    )
                ),
                "buy",
            ),
            (
                "3M return",
                "Buy_3M_Return_Margin_Pct",
                float(
                    getattr(self.config, "BORDERLINE_3M_RETURN_PCT_BAND", 1.0)
                ),
                "buy",
            ),
            (
                "growth",
                "Strong_Buy_Growth_Margin_Ratio",
                float(
                    getattr(self.config, "BORDERLINE_GROWTH_RATIO_BAND", 0.01)
                ),
                "strong",
            ),
            (
                "ADX",
                "Strong_Buy_ADX_Margin",
                float(getattr(self.config, "BORDERLINE_ADX_BAND", 1.0)),
                "strong",
            ),
            (
                "+DI/-DI",
                "Strong_Buy_DI_Margin",
                float(getattr(self.config, "BORDERLINE_DI_BAND", 1.0)),
                "strong",
            ),
            (
                "technical score",
                "Strong_Buy_Technical_Score_Margin",
                float(
                    getattr(self.config, "BORDERLINE_TECH_SCORE_BAND", 2.0)
                ),
                "strong",
            ),
            (
                "fundamental BUY coverage",
                "Buy_Fundamental_Coverage_Margin",
                float(getattr(self.config, "BORDERLINE_COVERAGE_BAND", 0.05)),
                "buy",
            ),
            (
                "fundamental STRONG BUY coverage",
                "Strong_Buy_Fundamental_Coverage_Margin",
                float(getattr(self.config, "BORDERLINE_COVERAGE_BAND", 0.05)),
                "strong",
            ),
            (
                "technical BUY coverage",
                "Buy_Technical_Coverage_Margin",
                float(getattr(self.config, "BORDERLINE_COVERAGE_BAND", 0.05)),
                "buy",
            ),
            (
                "technical STRONG BUY coverage",
                "Strong_Buy_Technical_Coverage_Margin",
                float(getattr(self.config, "BORDERLINE_COVERAGE_BAND", 0.05)),
                "strong",
            ),
        )
        reasons = []
        for index in frame.index:
            row_reasons = []
            row_evidence = _safe_float(frame.at[index, "Evidence_Score"])
            buy_relevant = row_evidence is not None and row_evidence >= 55.0
            strong_relevant = (
                row_evidence is not None
                and row_evidence >= 65.0
                and _as_bool(frame.at[index, "Buy_Eligible"])
            )
            for label, column, band, scope in diagnostic_bands:
                if scope == "buy" and not buy_relevant:
                    continue
                if scope == "strong" and not strong_relevant:
                    continue
                value = _safe_float(frame.at[index, column])
                if value is not None and abs(value) <= max(0.0, band):
                    row_reasons.append(label)
            reasons.append(_dedupe(row_reasons))
        frame["Gate_Borderline"] = [bool(items) for items in reasons]
        frame["Gate_Borderline_Count"] = [len(items) for items in reasons]
        frame["Gate_Borderline_Reasons"] = [
            _json_reasons(items) for items in reasons
        ]
        data_limited = (
            ~_bool_series(frame, "Fundamental_Coverage_Eligible", True)
            | ~_bool_series(frame, "Technical_Coverage_Eligible", True)
            | _numeric_series(frame, "Evidence_Score").isna()
        )
        frame["Decision_Stability_Status"] = [
            "DATA_LIMITED"
            if bool(data_limited.loc[index])
            else "BORDERLINE"
            if reasons[position]
            else "POLICY_CAPPED"
            if bool(decision_capped.loc[index])
            else "CLEAR"
            for position, index in enumerate(frame.index)
        ]
        return frame

    def _assign_ranks(self, frame):
        ranked = frame.copy().reset_index(drop=True)
        if "Symbol" not in ranked:
            ranked["Symbol"] = ranked.index.astype(str)
        ranked["_Symbol_Sort"] = ranked["Symbol"].fillna("").astype(str)
        ranked["_Rating_Order"] = ranked["Rating"].map(RATING_ORDER).fillna(
            len(RATING_ORDER)
        )

        def assign(column, by, ascending):
            order = ranked.sort_values(
                by,
                ascending=ascending,
                na_position="last",
                kind="mergesort",
            ).index
            values = pd.Series(index=ranked.index, dtype="int64")
            values.loc[order] = range(1, len(ranked) + 1)
            ranked[column] = values.astype(int)

        assign(
            "Score_Rank",
            ["Evidence_Score", "_Symbol_Sort"],
            [False, True],
        )
        assign(
            "Recommendation_Rank",
            [
                "_Rating_Order",
                "Decision_Score",
                "Evidence_Score",
                "_Symbol_Sort",
            ],
            [True, False, False, True],
        )
        # Primary investment rank is decision-score first.  Recommendation_Rank
        # remains available for consumers that explicitly want rating classes.
        factor_model_run = (
            _as_bool(getattr(self.config, "FACTOR_MODEL_ENABLED", False))
            and "Factor_Model_Applied" in ranked
            and bool(_bool_series(ranked, "Factor_Model_Applied", False).all())
        )
        if (
            factor_model_run
            and _as_bool(
                getattr(self.config, "RANK_BY_ELIGIBILITY_CLASS", False)
            )
            and "Eligibility_Class" in ranked
        ):
            # Eligibility first, then the uncapped research score. Every capped
            # candidate shares one ceiling, so ordering them by Decision_Score
            # sorts a column that is constant by construction and falls through
            # to the symbol tie-break -- i.e. alphabetical order presented as
            # investment merit. Research_Score restores a real ordering inside
            # each class while eligibility still dominates across classes.
            research = (
                "Research_Score" if "Research_Score" in ranked else "Evidence_Score"
            )
            assign(
                "Investment_Rank",
                [
                    "Eligibility_Class",
                    research,
                    "Gate_Severity",
                    "_Symbol_Sort",
                ],
                [True, False, True, True],
            )
        else:
            assign(
                "Investment_Rank",
                ["Decision_Score", "Evidence_Score", "_Symbol_Sort"],
                [False, False, True],
            )
        ranked["Rank"] = ranked["Investment_Rank"]
        ranked = ranked.sort_values("Investment_Rank", kind="mergesort").reset_index(
            drop=True
        )
        return ranked.drop(columns=["_Symbol_Sort", "_Rating_Order"])

    def finalize(self, scored_df):
        """Return a new frame; never mutate the caller's evidence frame."""

        if scored_df is None:
            return None
        frame = scored_df.copy(deep=True).reset_index(drop=True)
        if "Combined_Score" not in frame:
            raise ValueError("Combined_Score is required to finalize recommendations")
        frame = self._blend_evidence(frame)
        frame = self._apply_decision_policy(frame)
        frame = self._add_stability_diagnostics(frame)
        return self._assign_ranks(frame)


def finalize_recommendations(scored_df, config):
    """Convenience entry point for the single recommendation policy."""

    return RecommendationPolicy(config).finalize(scored_df)
