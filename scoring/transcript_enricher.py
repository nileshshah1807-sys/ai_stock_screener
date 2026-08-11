"""Transcript sentiment enrichment and ranking for daily screening."""

from __future__ import annotations

from datetime import date
import json
import math

import numpy as np
import pandas as pd

from screener.numeric import round_half_up, round_series_half_up
from screener.scoring import RATING_ORDER
from storage.supabase_repository import SupabaseRepository
from transcripts.periods import (
    CURRENT_CYCLE,
    PRIOR_CYCLE,
    classify_transcript_evidence,
    cycle_transition_confidence,
)


def recency_weight(
    call_date: str | None,
    today: date | None = None,
    half_life_days: float = 90.0,
    max_age_days: int = 180,
) -> float:
    """Return a continuous confidence weight for current transcript evidence.

    The old 30/60/90/180-day staircase produced deterministic rank jumps on
    calendar boundaries. Exponential decay is continuous, monotone and easy to
    audit. Evidence outside the configured horizon remains informational only.
    """
    if not call_date:
        return 0.0
    try:
        age_days = max(0, ((today or date.today()) - date.fromisoformat(str(call_date)[:10])).days)
    except ValueError:
        return 0.0
    if age_days > max(0, int(max_age_days)):
        return 0.0
    half_life = max(1.0, float(half_life_days))
    return round_half_up(
        math.exp(-math.log(2.0) * age_days / half_life), 6
    )


class TranscriptSentimentEnricher:
    def __init__(self, config, repository=None, analysis_date=None):
        self.config = config
        self.repository = repository
        self.analysis_date = analysis_date or date.today()

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
        enriched["Transcript_Cycle_Weight"] = 0.0
        enriched["Transcript_Cycle_Transition_Date"] = ""
        enriched["Transcript_Days_To_Cycle_Transition"] = np.nan
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
        enriched["Transcript_Quality_Gate_Failures"] = "[]"
        enriched["Transcript_Quality_Gate_Failure_Count"] = 0
        enriched["Transcript_Blend_Eligible"] = False
        enriched["Transcript_Blend_Weight"] = 0.0
        enriched["Transcript_Signal_Direction"] = "unknown"
        enriched["Transcript_Proposed_Delta_Core"] = 0.0

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
                as_of=self.analysis_date,
                max_age_days=getattr(self.config, "TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS", 180),
                market_holidays=getattr(
                    self.config, "NSE_MARKET_HOLIDAYS", ()
                ),
            )
            weight = recency_weight(
                record.get("call_date"),
                today=self.analysis_date,
                half_life_days=getattr(
                    self.config, "TRANSCRIPT_RECENCY_HALF_LIFE_DAYS", 90.0
                ),
                max_age_days=getattr(
                    self.config, "TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS", 180
                ),
            )
            cycle_weight, transition_date, transition_days = (
                cycle_transition_confidence(
                    evidence.period_end,
                    self.analysis_date,
                    getattr(self.config, "TRANSCRIPT_CYCLE_TAPER_DAYS", 20),
                    getattr(self.config, "NSE_MARKET_HOLIDAYS", ()),
                )
            )
            weight *= cycle_weight
            score = _number(record.get("overall_score"))
            scoring_eligible = evidence.scoring_eligible and bool(weight)
            if scoring_eligible:
                transcript_status = "Available"
                evidence_path = "Current-cycle transcript"
            elif evidence.status == PRIOR_CYCLE:
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
                round_half_up(50.0 + (score - 50.0) * weight, 2)
                if score is not None and weight else np.nan
            )
            enriched.at[index, "Transcript_Recency_Weight"] = weight
            enriched.at[index, "Transcript_Cycle_Weight"] = cycle_weight
            enriched.at[index, "Transcript_Cycle_Transition_Date"] = (
                transition_date.isoformat() if transition_date else ""
            )
            enriched.at[index, "Transcript_Days_To_Cycle_Transition"] = (
                transition_days
            )
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

        priority_weight = _weight(
            getattr(self.config, "TRANSCRIPT_SENTIMENT_WEIGHT", 0.15)
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
        enriched["Transcript_Quality_Eligible"] = quality_eligible
        for index in enriched.index[eligible]:
            failures = []
            if transcript_scores.loc[index] < minimum_priority_score:
                failures.append("Sentiment below priority threshold")
            if transcript_risk.loc[index] > maximum_priority_risk:
                failures.append("Risk above priority threshold")
            if lowered_guidance.loc[index]:
                failures.append("Guidance lowered")
            enriched.at[index, "Transcript_Quality_Gate"] = (
                "; ".join(failures) if failures else "Passed"
            )
            enriched.at[index, "Transcript_Quality_Gate_Failures"] = json.dumps(
                failures, separators=(",", ":")
            )
            enriched.at[index, "Transcript_Quality_Gate_Failure_Count"] = len(
                failures
            )
        # The enricher is evidence-only. It never mutates Final_Score, Rating or
        # ranks; the versioned recommendation policy is their sole writer.
        # Risk already contributes to the stored overall score, so using
        # ``100-risk`` here would count it twice. Guidance/risk remain explicit
        # audit fields and quality classifications, not a second numerical cap.
        # Recency reduces the amount of evidence applied, not its score toward
        # an absolute 50 anchor. Decaying a positive 80 score toward 50 while
        # retaining the full 15% blend would perversely make an older positive
        # call penalize a high-quality core more than a fresh call.
        effective = transcript_scores
        recency = pd.to_numeric(
            enriched["Transcript_Recency_Weight"], errors="coerce"
        ).fillna(0.0).clip(0.0, 1.0)
        applied_weight = priority_weight * recency
        high_risk = eligible & transcript_risk.gt(maximum_priority_risk)
        tone_direction = pd.Series("unknown", index=enriched.index, dtype=object)
        tone_direction.loc[eligible & effective.lt(45.0)] = "negative"
        tone_direction.loc[
            eligible & effective.between(45.0, 55.0, inclusive="left")
        ] = "cautious"
        tone_direction.loc[eligible & effective.ge(55.0)] = "positive"

        enriched.loc[eligible, "Transcript_Effective_Score"] = (
            round_series_half_up(effective.loc[eligible], 2)
        )
        enriched.loc[eligible, "Transcript_Blend_Eligible"] = True
        enriched.loc[eligible, "Transcript_Blend_Weight"] = applied_weight.loc[
            eligible
        ]
        enriched.loc[eligible, "Transcript_Tone_Direction"] = tone_direction.loc[
            eligible
        ]
        enriched.loc[eligible, "Transcript_Technical_Gate"] = (
            "Downside-only evidence; finalized centrally"
        )
        # This is an attribution estimate against the core score. The central
        # policy recomputes the exact delta after any eligible DCF evidence.
        proposed_delta = applied_weight * np.minimum(effective - 50.0, 0.0)
        enriched.loc[eligible, "Transcript_Proposed_Delta_Core"] = proposed_delta.loc[
            eligible
        ].map(lambda value: round_half_up(value, 2))
        enriched.loc[eligible & proposed_delta.lt(0), "Transcript_Downside_Applied"] = True
        enriched.loc[eligible, "Transcript_Signal_Direction"] = "neutral"
        enriched.loc[eligible & proposed_delta.lt(0), "Transcript_Signal_Direction"] = (
            "downside"
        )
        enriched["Transcript_Priority_Applied"] = False
        return enriched


def rank_actionable_recommendations(scored_df):
    """Add an execution rank without rewriting investment conviction.

    V4 makes the primary top list score-first. ``Investment_Rank`` is produced
    by the recommendation policy from ``Decision_Score`` and is independent of
    transcript availability and liquidity. This function only adds the
    execution overlay; rows remain ordered by investment conviction for CSV and
    report compatibility.
    """
    ranking_source = scored_df.copy().reset_index(drop=True)
    score_column = "Decision_Score" if "Decision_Score" in ranking_source else "Final_Score"
    scores = pd.to_numeric(ranking_source[score_column], errors="coerce").fillna(-np.inf)
    if "Investment_Rank" not in ranking_source:
        investment_order = ranking_source.assign(_Score=scores).sort_values(
            ["_Score", "Symbol"],
            ascending=[False, True],
            kind="mergesort",
        ).index
        ranking_source["Investment_Rank"] = pd.Series(
            range(1, len(ranking_source) + 1), index=investment_order
        )

    actionable = ranking_source.get(
        "Portfolio_Actionable",
        ranking_source.get(
            "Liquidity_Conviction_Eligible",
            pd.Series(True, index=ranking_source.index),
        ),
    ).fillna(False).astype(bool)
    # Within each actionability bucket preserve the exact primary investment
    # order (Decision Score, Evidence Score, Symbol). This avoids a different
    # symbol-only tie break when several gated rows share a 69.99/59.99 ceiling.
    action_order = ranking_source.assign(
        _Actionable=actionable,
    ).sort_values(
        ["_Actionable", "Investment_Rank"],
        ascending=[False, True],
        kind="mergesort",
    ).index
    ranking_source["Actionable_Rank"] = pd.Series(
        range(1, len(ranking_source) + 1), index=action_order
    )
    ranking_source["Rank"] = ranking_source["Investment_Rank"]
    return ranking_source.sort_values(
        ["Investment_Rank", "Symbol"], kind="mergesort"
    ).reset_index(drop=True)


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
    if score is None:
        return "Unavailable"
    if evidence_status != PRIOR_CYCLE and not recency_weight_value:
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
