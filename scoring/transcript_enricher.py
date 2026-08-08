"""Transcript sentiment enrichment and ranking for daily screening."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from screener.scoring import RATING_ORDER
from storage.supabase_repository import SupabaseRepository
from transcripts.periods import (
    CURRENT_CYCLE,
    PRIOR_CYCLE,
    classify_transcript_evidence,
)


def recency_weight(call_date: str | None, today: date | None = None) -> float:
    if not call_date:
        return 0.0
    try:
        age_days = max(0, ((today or date.today()) - date.fromisoformat(str(call_date)[:10])).days)
    except ValueError:
        return 0.0
    if age_days <= 30:
        return 1.0
    if age_days <= 60:
        return 0.75
    if age_days <= 90:
        return 0.50
    if age_days <= 180:
        return 0.25
    return 0.0


class TranscriptSentimentEnricher:
    def __init__(self, config, repository=None):
        self.config = config
        self.repository = repository

    def enrich(self, scored_df):
        enriched = scored_df.copy()
        base_score_column = "Final_Score" if "Final_Score" in enriched else "Combined_Score"
        base_scores = enriched[base_score_column].copy()
        enriched["Transcript_Status"] = "No transcript"
        enriched["Transcript_Evidence_Status"] = "No transcript"
        enriched["Transcript_Evidence_Period"] = ""
        enriched["Transcript_Expected_Period"] = ""
        enriched["Transcript_Age_Days"] = np.nan
        enriched["Transcript_Scoring_Eligible"] = False
        enriched["Transcript_Fallback_Used"] = False
        enriched["Management_Evidence_Path"] = "No transcript; base model retained"
        enriched["Transcript_Score"] = np.nan
        enriched["Transcript_Weighted_Score"] = np.nan
        enriched["Transcript_Recency_Weight"] = 0.0
        enriched["Transcript_Guidance"] = ""
        enriched["Transcript_Risk"] = np.nan
        enriched["Transcript_Management_Confidence"] = np.nan
        enriched["Transcript_Optimism_QoQ_Delta"] = np.nan
        enriched["Transcript_Uncertainty_QoQ_Delta"] = np.nan
        enriched["Transcript_Previous_Guidance"] = ""
        enriched["Transcript_Call_Date"] = ""
        enriched["Transcript_Summary"] = "No transcript"
        enriched["Transcript_Priority_Applied"] = False
        enriched["Transcript_Downside_Applied"] = False
        enriched["Transcript_Effective_Score"] = np.nan
        enriched["Transcript_Strong_Buy_Capped"] = False
        enriched["Transcript_Technical_Gate"] = "No transcript"
        enriched["Transcript_Quality_Gate"] = "No transcript"
        enriched["Final_Score"] = base_scores
        base_ratings = enriched["Rating"].copy() if "Rating" in enriched else None

        repository = self.repository
        if repository is None:
            if not getattr(self.config, "SUPABASE_URL", "") or not getattr(self.config, "SUPABASE_SERVICE_ROLE_KEY", ""):
                enriched["Transcript_Status"] = "Not configured"
                enriched["Transcript_Summary"] = "Not configured"
                return enriched
            repository = SupabaseRepository(
                self.config.SUPABASE_URL,
                self.config.SUPABASE_SERVICE_ROLE_KEY,
                getattr(self.config, "SUPABASE_TIMEOUT_SECONDS", 30),
            )
        records = repository.latest_sentiments(enriched["Symbol"].astype(str).str.upper().tolist())
        by_symbol = {str(record["symbol"]).upper(): record for record in records}
        for index, symbol in enriched["Symbol"].items():
            record = by_symbol.get(str(symbol).upper())
            if record is None:
                continue
            evidence = classify_transcript_evidence(
                record.get("call_date"),
                max_age_days=getattr(self.config, "TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS", 180),
            )
            weight = recency_weight(record.get("call_date"))
            score = _number(record.get("overall_score"))
            scoring_eligible = evidence.scoring_eligible and bool(weight)
            if scoring_eligible:
                transcript_status = "Available"
                evidence_path = "Current-cycle transcript"
            elif evidence.status == PRIOR_CYCLE and weight:
                transcript_status = "Prior-cycle"
                evidence_path = "Prior-cycle transcript; informational only"
            else:
                transcript_status = "Expired"
                evidence_path = "Expired transcript; base model retained"
            enriched.at[index, "Transcript_Status"] = transcript_status
            enriched.at[index, "Transcript_Evidence_Status"] = evidence.status
            enriched.at[index, "Transcript_Evidence_Period"] = (
                evidence.period_end.isoformat() if evidence.period_end else ""
            )
            enriched.at[index, "Transcript_Expected_Period"] = (
                evidence.expected_period_end.isoformat() if evidence.expected_period_end else ""
            )
            enriched.at[index, "Transcript_Age_Days"] = evidence.age_days
            enriched.at[index, "Transcript_Scoring_Eligible"] = scoring_eligible
            enriched.at[index, "Transcript_Fallback_Used"] = transcript_status == "Prior-cycle"
            enriched.at[index, "Management_Evidence_Path"] = evidence_path
            enriched.at[index, "Transcript_Score"] = score
            # Age reduces confidence in the signal, not the score's absolute
            # level. Decay toward neutral (50), otherwise an old positive call
            # is incorrectly transformed into a strongly negative score.
            enriched.at[index, "Transcript_Weighted_Score"] = (
                round(50.0 + (score - 50.0) * weight, 2)
                if score is not None and weight else np.nan
            )
            enriched.at[index, "Transcript_Recency_Weight"] = weight
            enriched.at[index, "Transcript_Guidance"] = record.get("guidance_direction", "")
            enriched.at[index, "Transcript_Risk"] = _number(record.get("risk_score"))
            enriched.at[index, "Transcript_Management_Confidence"] = _number(record.get("management_confidence"))
            enriched.at[index, "Transcript_Optimism_QoQ_Delta"] = _number(record.get("optimism_qoq_delta"))
            enriched.at[index, "Transcript_Uncertainty_QoQ_Delta"] = _number(record.get("uncertainty_qoq_delta"))
            enriched.at[index, "Transcript_Previous_Guidance"] = record.get("previous_guidance_direction", "")
            enriched.at[index, "Transcript_Call_Date"] = record.get("call_date") or ""
            enriched.at[index, "Transcript_Summary"] = _summary(
                score,
                record.get("guidance_direction"),
                record.get("call_date"),
                weight,
                record.get("structured_output"),
                _number(record.get("risk_score")),
                _number(record.get("management_confidence")),
                evidence.status,
            )

        priority_weight = _weight(getattr(self.config, "TRANSCRIPT_SENTIMENT_WEIGHT", 0.15))
        minimum_technical_score = _score_threshold(
            getattr(self.config, "TRANSCRIPT_MIN_TECHNICAL_SCORE", 45.0),
            45.0,
        )
        full_weight_technical_score = max(
            minimum_technical_score,
            _score_threshold(getattr(self.config, "TRANSCRIPT_FULL_WEIGHT_TECHNICAL_SCORE", 60.0), 60.0),
        )
        eligible = enriched["Transcript_Scoring_Eligible"].eq(True) & enriched["Transcript_Weighted_Score"].notna()
        minimum_priority_score = _score_threshold(
            getattr(self.config, "TRANSCRIPT_MIN_PRIORITY_SCORE", 55.0),
            55.0,
        )
        maximum_priority_risk = _score_threshold(
            getattr(self.config, "TRANSCRIPT_MAX_PRIORITY_RISK", 60.0),
            60.0,
        )
        transcript_scores = pd.to_numeric(enriched["Transcript_Score"], errors="coerce")
        transcript_risk = pd.to_numeric(enriched["Transcript_Risk"], errors="coerce")
        lowered_guidance = enriched["Transcript_Guidance"].astype(str).str.lower().eq("lowered")
        quality_eligible = (
            eligible
            & (transcript_scores >= minimum_priority_score)
            & (transcript_risk.isna() | (transcript_risk <= maximum_priority_risk))
            & ~lowered_guidance
        )
        enriched.loc[eligible, "Transcript_Quality_Gate"] = "Passed"
        enriched.loc[eligible & (transcript_scores < minimum_priority_score), "Transcript_Quality_Gate"] = (
            "Sentiment below priority threshold"
        )
        enriched.loc[eligible & (transcript_risk > maximum_priority_risk), "Transcript_Quality_Gate"] = (
            "Risk above priority threshold"
        )
        enriched.loc[eligible & lowered_guidance, "Transcript_Quality_Gate"] = "Guidance lowered"
        downside_weight = eligible & ~quality_eligible
        technical_scores = pd.to_numeric(
            enriched.get("Technical_Score", pd.Series(np.nan, index=enriched.index)),
            errors="coerce",
        )
        trend_confirmed = enriched.get("Trend_Confirmed", pd.Series(False, index=enriched.index)).eq(True)
        full_weight = quality_eligible & (technical_scores >= full_weight_technical_score) & trend_confirmed
        limited_weight = (
            quality_eligible
            & (technical_scores >= minimum_technical_score)
            & trend_confirmed
            & ~full_weight
        )
        weak_technical = quality_eligible & ~full_weight & ~limited_weight
        enriched.loc[full_weight, "Transcript_Technical_Gate"] = "Full weight"
        enriched.loc[limited_weight, "Transcript_Technical_Gate"] = "Limited weight; no rating promotion"
        enriched.loc[
            quality_eligible & ~trend_confirmed,
            "Transcript_Technical_Gate",
        ] = "Trend not confirmed; no transcript weight"
        enriched.loc[
            weak_technical & trend_confirmed,
            "Transcript_Technical_Gate",
        ] = "Weak technicals; no transcript weight"
        enriched["Transcript_Priority_Applied"] = full_weight
        enriched.loc[full_weight | limited_weight, "Transcript_Effective_Score"] = enriched.loc[
            full_weight | limited_weight,
            "Transcript_Weighted_Score",
        ]
        enriched.loc[full_weight, "Final_Score"] = (
            base_scores.loc[full_weight] * (1 - priority_weight)
            + enriched.loc[full_weight, "Transcript_Weighted_Score"] * priority_weight
        ).round(2)
        limited_weight_value = priority_weight / 2
        enriched.loc[limited_weight, "Final_Score"] = (
            base_scores.loc[limited_weight] * (1 - limited_weight_value)
            + enriched.loc[limited_weight, "Transcript_Weighted_Score"] * limited_weight_value
        ).round(2)

        # Adverse calls are evidence even when they fail the positive-priority
        # gate. Apply their downside regardless of chart strength; otherwise a
        # lowered outlook or high-risk call is paradoxically ignored. A failed
        # gate can only reduce the core score, never promote it.
        downside_score = pd.to_numeric(
            enriched["Transcript_Weighted_Score"], errors="coerce"
        ).copy()
        high_risk = downside_weight & transcript_risk.gt(maximum_priority_risk)
        downside_score.loc[high_risk] = np.minimum(
            downside_score.loc[high_risk],
            100.0 - transcript_risk.loc[high_risk],
        )
        downside_score.loc[downside_weight & lowered_guidance] = np.minimum(
            downside_score.loc[downside_weight & lowered_guidance],
            45.0,
        )
        downside_score.loc[downside_weight] = np.minimum(
            downside_score.loc[downside_weight],
            base_scores.loc[downside_weight],
        )
        enriched.loc[downside_weight, "Transcript_Effective_Score"] = downside_score.loc[
            downside_weight
        ].round(2)
        enriched.loc[downside_weight, "Final_Score"] = (
            base_scores.loc[downside_weight] * (1 - priority_weight)
            + downside_score.loc[downside_weight] * priority_weight
        ).round(2)
        enriched.loc[downside_weight, "Transcript_Downside_Applied"] = True
        enriched.loc[downside_weight, "Transcript_Technical_Gate"] = (
            "Downside applied; transcript quality gate failed"
        )
        if "Rating" in enriched:
            blended_rows = full_weight | limited_weight | downside_weight
            enriched.loc[blended_rows, "Rating"] = enriched.loc[blended_rows, "Final_Score"].map(_rating_from_score)
            # Limited transcript weight may lower conviction, but it cannot
            # promote a stock above the recommendation earned by the core model.
            if base_ratings is not None:
                promoted = limited_weight & (
                    enriched["Rating"].map(RATING_ORDER).fillna(len(RATING_ORDER))
                    < base_ratings.map(RATING_ORDER).fillna(len(RATING_ORDER))
                )
                enriched.loc[promoted, "Rating"] = base_ratings.loc[promoted]
            if "Rating_Capped" in enriched:
                capped_above_hold = (
                    eligible
                    & enriched["Rating_Capped"].eq(True)
                    & enriched["Rating"].map(RATING_ORDER).lt(RATING_ORDER["HOLD"])
                )
                enriched.loc[capped_above_hold, "Rating"] = "HOLD"
            strong_buy_eligible = enriched.get(
                "Strong_Buy_Eligible",
                pd.Series(False, index=enriched.index),
            ).eq(True)
            enriched.loc[
                eligible
                & (enriched["Rating"] == "STRONG BUY")
                & ~strong_buy_eligible,
                "Rating",
            ] = "BUY"
            require_transcript_for_strong_buy = bool(
                getattr(self.config, "REQUIRE_TRANSCRIPT_FOR_STRONG_BUY", False)
            )
            transcript_required_cap = (
                require_transcript_for_strong_buy
                & (enriched["Rating"] == "STRONG BUY")
                & ~quality_eligible
            )
            enriched.loc[transcript_required_cap, "Rating"] = "BUY"
            enriched.loc[transcript_required_cap, "Transcript_Strong_Buy_Capped"] = True
            enriched.loc[
                transcript_required_cap,
                "Transcript_Technical_Gate",
            ] = "Fresh, quality transcript required for STRONG BUY"
        return enriched


def rank_actionable_recommendations(scored_df):
    """Expose separate investment and execution-aware ranks.

    Transcript evidence is already blended into ``Final_Score`` at its
    configured weight.  Making availability a higher-order sort key gives it
    an unlimited hidden weight and lets a much lower-scoring company outrank a
    stronger no-call company.  Missing calls must remain neutral.

    Persistent liquidity is different: it is an execution constraint, so
    liquid names form the actionable report inside each recommendation class.
    ``Investment_Rank`` preserves the pure rating/score order; ``Rank`` and
    ``Actionable_Rank`` put executable names first. Thin names remain in the
    CSV for research.
    """
    transcript_priority = scored_df.get(
        "Transcript_Priority_Applied",
        pd.Series(False, index=scored_df.index),
    ).fillna(False)
    liquidity_eligible = scored_df.get(
        "Liquidity_Conviction_Eligible",
        pd.Series(True, index=scored_df.index),
    ).fillna(False)
    # StockScorer adds audit columns incrementally. Copy once here to
    # consolidate pandas blocks before the final sort and avoid fragmented
    # frame warnings on the full NSE universe.
    ranking_source = scored_df.copy().reset_index(drop=True)
    ranking_source = ranking_source.assign(
        _Rating_Order=ranking_source["Rating"].map(RATING_ORDER).fillna(len(RATING_ORDER)),
        _Liquidity_Actionable=liquidity_eligible.reset_index(drop=True),
        _Transcript_Tie_Break=transcript_priority.reset_index(drop=True),
    )
    investment_order = ranking_source.sort_values(
        ["_Rating_Order", "Final_Score", "_Transcript_Tie_Break", "Symbol"],
        ascending=[True, False, False, True],
        kind="mergesort",
    ).index
    ranking_source["Investment_Rank"] = pd.Series(
        range(1, len(ranking_source) + 1), index=investment_order
    )
    ranked = (
        ranking_source
        .sort_values(
            [
                "_Rating_Order",
                "_Liquidity_Actionable",
                "Final_Score",
                "_Transcript_Tie_Break",
                "Symbol",
            ],
            ascending=[True, False, False, False, True],
            kind="mergesort",
        )
        .drop(
            columns=[
                "_Rating_Order",
                "_Liquidity_Actionable",
                "_Transcript_Tie_Break",
            ]
        )
        .reset_index(drop=True)
    )
    ranked["Actionable_Rank"] = range(1, len(ranked) + 1)
    # Backwards-compatible report rank is explicitly the execution-aware rank.
    ranked["Rank"] = ranked["Actionable_Rank"]
    return ranked


def rank_by_transcript_priority(scored_df):
    """Backward-compatible name for the final actionability ranking."""
    return rank_actionable_recommendations(scored_df)


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _weight(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.15


def _score_threshold(value, default):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


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


def _summary(
    score,
    guidance,
    call_date,
    recency_weight_value,
    structured_output=None,
    risk_score=None,
    management_confidence=None,
    evidence_status=CURRENT_CYCLE,
):
    if score is None or not recency_weight_value:
        return "Expired"
    evidence_prefix = "Prior-cycle evidence | " if evidence_status == PRIOR_CYCLE else ""
    direction = str(guidance or "unclear").strip().lower()
    if direction != "unclear":
        return f"{evidence_prefix}{score:.1f} | {direction.replace('_', ' ').title()} | {str(call_date)[:10]}"

    details = structured_output if isinstance(structured_output, dict) else {}
    commentary = ["No explicit guidance"]
    demand_outlook = str(details.get("demand_outlook") or "").strip().lower()
    revenue_outlook = str(details.get("revenue_outlook") or "").strip().lower()
    margin_outlook = str(details.get("margin_outlook") or "").strip().lower()
    if demand_outlook in {"positive", "negative", "neutral"}:
        commentary.append(f"{demand_outlook} demand")
    if revenue_outlook in {"positive", "negative", "neutral"}:
        commentary.append(f"{revenue_outlook} revenue")
    if margin_outlook == "negative":
        commentary.append("margin pressure")
    elif margin_outlook in {"positive", "neutral"}:
        commentary.append(f"{margin_outlook} margins")
    if len(commentary) == 1:
        tone = "positive" if score >= 60 else "cautious" if score < 45 else "balanced"
        commentary.append(f"{tone} overall tone")
        if risk_score is not None:
            commentary.append("elevated risk" if risk_score >= 60 else "moderate risk" if risk_score >= 40 else "contained risk")
        if management_confidence is not None and management_confidence >= 65:
            commentary.append("confident management tone")
    return f"{evidence_prefix}{score:.1f} | {'; '.join(commentary)} | {str(call_date)[:10]}"
