"""Transcript sentiment enrichment and ranking for daily screening."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from storage.supabase_repository import SupabaseRepository


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
        enriched["Transcript_Technical_Gate"] = "No transcript"
        enriched["Final_Score"] = base_scores

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
            weight = recency_weight(record.get("call_date"))
            score = _number(record.get("overall_score"))
            enriched.at[index, "Transcript_Status"] = "Available" if weight else "Expired"
            enriched.at[index, "Transcript_Score"] = score
            enriched.at[index, "Transcript_Weighted_Score"] = round(score * weight, 2) if score is not None else np.nan
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
            )

        priority_weight = _weight(getattr(self.config, "TRANSCRIPT_SENTIMENT_WEIGHT", 0.05))
        minimum_technical_score = _score_threshold(
            getattr(self.config, "TRANSCRIPT_MIN_TECHNICAL_SCORE", 45.0),
            45.0,
        )
        full_weight_technical_score = max(
            minimum_technical_score,
            _score_threshold(getattr(self.config, "TRANSCRIPT_FULL_WEIGHT_TECHNICAL_SCORE", 60.0), 60.0),
        )
        eligible = (enriched["Transcript_Status"] == "Available") & enriched["Transcript_Weighted_Score"].notna()
        technical_scores = pd.to_numeric(
            enriched.get("Technical_Score", pd.Series(np.nan, index=enriched.index)),
            errors="coerce",
        )
        trend_confirmed = enriched.get("Trend_Confirmed", pd.Series(False, index=enriched.index)).eq(True)
        full_weight = eligible & (technical_scores >= full_weight_technical_score) & trend_confirmed
        limited_weight = (
            eligible
            & (technical_scores >= minimum_technical_score)
            & trend_confirmed
            & ~full_weight
        )
        weak_technical = eligible & ~full_weight & ~limited_weight
        enriched.loc[full_weight, "Transcript_Technical_Gate"] = "Full weight"
        enriched.loc[limited_weight, "Transcript_Technical_Gate"] = "Limited weight; HOLD cap"
        enriched.loc[
            eligible & ~trend_confirmed,
            "Transcript_Technical_Gate",
        ] = "Trend not confirmed; REDUCE cap"
        enriched.loc[
            weak_technical & trend_confirmed,
            "Transcript_Technical_Gate",
        ] = "Weak technicals; REDUCE cap"
        enriched["Transcript_Priority_Applied"] = full_weight
        enriched.loc[full_weight, "Final_Score"] = (
            base_scores.loc[full_weight] * (1 - priority_weight)
            + enriched.loc[full_weight, "Transcript_Weighted_Score"] * priority_weight
        ).round(2)
        limited_weight_value = priority_weight / 2
        enriched.loc[limited_weight, "Final_Score"] = (
            base_scores.loc[limited_weight] * (1 - limited_weight_value)
            + enriched.loc[limited_weight, "Transcript_Weighted_Score"] * limited_weight_value
        ).round(2)
        if "Rating" in enriched:
            enriched.loc[eligible, "Rating"] = enriched.loc[eligible, "Final_Score"].map(_rating_from_score)
            enriched.loc[limited_weight & enriched["Rating"].isin(["STRONG BUY", "BUY"]), "Rating"] = "HOLD"
            if "Rating_Capped" in enriched:
                enriched.loc[eligible & (enriched["Rating_Capped"] == True), "Rating"] = "HOLD"
            if "Strong_Buy_Eligible" in enriched:
                enriched.loc[
                    eligible
                    & (enriched["Rating"] == "STRONG BUY")
                    & (enriched["Strong_Buy_Eligible"] != True),
                    "Rating",
                ] = "BUY"
            else:
                # Optional transcript evidence must never manufacture high
                # conviction when the base scorer did not provide its explicit
                # STRONG BUY eligibility gate.
                enriched.loc[eligible & (enriched["Rating"] == "STRONG BUY"), "Rating"] = "BUY"
            enriched.loc[weak_technical, "Rating"] = "REDUCE"
        return enriched


def rank_by_transcript_priority(scored_df):
    """Rank by final score; use validated fresh transcript coverage only as a tie-breaker."""
    ranked = scored_df.sort_values(
        ["Final_Score", "Transcript_Priority_Applied"],
        ascending=[False, False],
    ).reset_index(drop=True)
    ranked["Rank"] = range(1, len(ranked) + 1)
    return ranked


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _weight(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.05


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
):
    if score is None or not recency_weight_value:
        return "Expired"
    direction = str(guidance or "unclear").strip().lower()
    if direction != "unclear":
        return f"{score:.1f} | {direction.replace('_', ' ').title()} | {str(call_date)[:10]}"

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
    return f"{score:.1f} | {'; '.join(commentary)} | {str(call_date)[:10]}"
