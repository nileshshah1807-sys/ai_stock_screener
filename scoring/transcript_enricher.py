"""Transcript sentiment enrichment and ranking for daily screening."""

from __future__ import annotations

from datetime import date

import numpy as np

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
        enriched["Transcript_Call_Date"] = ""
        enriched["Transcript_Summary"] = "No transcript"
        enriched["Transcript_Priority_Applied"] = False
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
            enriched.at[index, "Transcript_Call_Date"] = record.get("call_date") or ""
            enriched.at[index, "Transcript_Summary"] = _summary(score, record.get("guidance_direction"), record.get("call_date"), weight)

        priority_weight = _weight(getattr(self.config, "TRANSCRIPT_SENTIMENT_WEIGHT", 0.80))
        eligible = (enriched["Transcript_Status"] == "Available") & enriched["Transcript_Weighted_Score"].notna()
        enriched["Transcript_Priority_Applied"] = eligible
        enriched.loc[eligible, "Final_Score"] = (
            base_scores.loc[eligible] * (1 - priority_weight)
            + enriched.loc[eligible, "Transcript_Weighted_Score"] * priority_weight
        ).round(2)
        return enriched


def rank_by_transcript_priority(scored_df):
    """Rank fresh transcript coverage first, then the sentiment-weighted final score."""
    ranked = scored_df.sort_values(
        ["Transcript_Priority_Applied", "Final_Score"],
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
        return 0.80


def _summary(score, guidance, call_date, recency_weight_value):
    if score is None or not recency_weight_value:
        return "Expired"
    direction = str(guidance or "unclear").replace("_", " ").title()
    return f"{score:.1f} | {direction} | {str(call_date)[:10]}"