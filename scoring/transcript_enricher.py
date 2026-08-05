"""Read-only transcript sentiment enrichment for shadow-mode screening."""

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
        enriched["Transcript_Status"] = "No transcript"
        enriched["Transcript_Score"] = np.nan
        enriched["Transcript_Weighted_Score"] = np.nan
        enriched["Transcript_Recency_Weight"] = 0.0
        enriched["Transcript_Guidance"] = ""
        enriched["Transcript_Risk"] = np.nan
        enriched["Transcript_Management_Confidence"] = np.nan
        enriched["Transcript_Optimism_QoQ_Delta"] = np.nan
        enriched["Transcript_Call_Date"] = ""

        repository = self.repository
        if repository is None:
            if not getattr(self.config, "SUPABASE_URL", "") or not getattr(self.config, "SUPABASE_SERVICE_ROLE_KEY", ""):
                enriched["Transcript_Status"] = "Not configured"
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
        return enriched


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None