"""Deterministic candidate-policy replay over a frozen screener export.

This intentionally reuses the export's raw market/fundamental observations. It
can validate score, evidence, gate, and rank changes without any network call;
it cannot repair an unfinished source bar or restore symbols excluded before
the historical export was written.
"""

from __future__ import annotations

from datetime import date
import json

import numpy as np
import pandas as pd

from scoring.transcript_enricher import recency_weight, rank_actionable_recommendations
from screener.data_collection import align_valuation_to_completed_price_bar
from screener.liquidity import LiquidityQualityEnricher
from screener.numeric import round_series_half_up
from screener.recommendation import finalize_recommendations
from screener.scoring import StockScorer
from screener.valuation import ReverseDCFModel
from validation.reproducibility import canonical_config_hash
from transcripts.periods import (
    CURRENT_CYCLE,
    PRIOR_CYCLE,
    classify_transcript_evidence,
    cycle_transition_confidence,
)


DECISION_COLUMNS = {
    "Core_Score",
    "Evidence_Score",
    "Evidence_Rating",
    "Decision_Score",
    "Decision_Rating",
    "Decision_Score_Ceiling",
    "Final_Score",
    "Rating",
    "Rating_Capped",
    "Rating_Cap_Reason",
    "Buy_Eligible",
    "Buy_Gate_Reason",
    "Buy_Gate_Failures",
    "Strong_Buy_Eligible",
    "Strong_Buy_Gate_Reason",
    "Strong_Buy_Gate_Failures",
    "Trend_Confirmed",
    "Gate_Failures",
    "Rank",
    "Score_Rank",
    "Recommendation_Rank",
    "Investment_Rank",
    "Actionable_Rank",
}

STORED_TRANSCRIPT_INPUT_COLUMNS = {
    "Transcript_Call_Date",
    "Transcript_Score",
    "Transcript_Risk",
    "Transcript_Guidance",
    "Transcript_Management_Confidence",
    "Transcript_Optimism_QoQ_Delta",
    "Transcript_Uncertainty_QoQ_Delta",
    "Transcript_Previous_Guidance",
}

MODEL_PROVENANCE_COLUMNS = (
    "Model_Version",
    "Recommendation_Policy_Version",
    "Output_Schema_Version",
    "Model_Config_SHA256",
)

REPLAY_LIMITATIONS = (
    "Market, fundamental, liquidity, and transcript observations are reused "
    "from the frozen source export; they are not refetched.",
    "An incomplete or provisional market bar already present in the source "
    "cannot be repaired by replay.",
    "Symbols filtered out before the source export cannot be restored, so "
    "sector peer ranks are limited to the frozen source universe.",
    "Replay validates deterministic scoring, evidence, gates, ratings, and "
    "ranks only; it is not point-in-time or out-of-sample validation.",
    "Exports written before the adjusted-signal-price split carry no "
    "Technical_Price. Replay substitutes the raw Current_Price so the "
    "price-relative technical components stay observable; for symbols with a "
    "corporate action inside the indicator lookback this reintroduces the "
    "raw-versus-adjusted scale mismatch that production collection avoids. "
    "Technical_Price_Source records which rows were proxied.",
)


def replay_source_provenance(source: pd.DataFrame) -> dict:
    """Summarize inherited provenance without copying stale run identities.

    Only version-like values are retained in the manifest. ``Run_*`` values
    may contain workflow identifiers or other environment-specific data, so
    the manifest records their column names while the candidate frame removes
    their values completely.
    """

    model_metadata = {}
    for column in MODEL_PROVENANCE_COLUMNS:
        if column not in source:
            continue
        values = (
            source[column]
            .dropna()
            .astype(str)
            .str.strip()
        )
        values = sorted(value for value in values.unique().tolist() if value)
        model_metadata[column] = {
            "distinct_count": len(values),
            "values": values[:20],
            "values_truncated": len(values) > 20,
        }
    return {
        "source_model_metadata": model_metadata,
        "cleared_source_run_columns": sorted(
            column for column in source.columns if column.startswith("Run_")
        ),
    }


def attach_replay_provenance(
    frame: pd.DataFrame,
    config,
    *,
    analysis_date: date,
) -> pd.DataFrame:
    """Attach candidate-owned metadata after all inherited decisions are gone."""

    enriched = frame.copy()
    for column in [column for column in enriched if column.startswith("Run_")]:
        enriched = enriched.drop(columns=column)
    enriched["Model_Version"] = str(
        getattr(config, "MODEL_VERSION", "unknown")
    )
    enriched["Recommendation_Policy_Version"] = str(
        getattr(config, "RECOMMENDATION_POLICY_VERSION", "unknown")
    )
    enriched["Output_Schema_Version"] = str(
        getattr(config, "OUTPUT_SCHEMA_VERSION", "unknown")
    )
    enriched["Model_Config_SHA256"] = canonical_config_hash(config)
    enriched["Run_Kind"] = "frozen_export_replay"
    enriched["Run_Analysis_Date"] = analysis_date.isoformat()
    enriched["Run_Source_Kind"] = "frozen_screener_export"
    return enriched


def apply_replay_technical_price_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    """Restore an observable technical price denominator for legacy exports.

    Production collection always writes ``Technical_Price`` on the adjusted
    scale every indicator is computed from.  Exports predating that split have
    only the raw ``Current_Price``, and without a substitute the MA20, MA50,
    MACD and ATR components become unobservable: technical coverage collapses
    below the BUY floor and every row is capped at HOLD, which would leave the
    replay unable to validate ranking at all.

    The substitution is deliberately confined to replay.  ``Technical_Price_
    Source`` marks each row so a proxied comparison is never mistaken for a
    collected one.
    """

    enriched = frame.copy()
    if "Technical_Price" in enriched:
        existing = pd.to_numeric(enriched["Technical_Price"], errors="coerce")
    else:
        existing = pd.Series(np.nan, index=enriched.index, dtype=float)
    if "Current_Price" in enriched:
        fallback = pd.to_numeric(enriched["Current_Price"], errors="coerce")
    else:
        fallback = pd.Series(np.nan, index=enriched.index, dtype=float)

    proxied = existing.isna() & fallback.gt(0)
    resolved = existing.where(existing.notna(), fallback.where(fallback.gt(0)))
    enriched["Technical_Price"] = resolved

    source = pd.Series("source_export", index=enriched.index, dtype=object)
    source.loc[proxied] = "replay_proxy_raw_close"
    source.loc[resolved.isna()] = "unavailable"
    enriched["Technical_Price_Source"] = source
    return enriched


def technical_price_source_counts(frame: pd.DataFrame) -> dict:
    """Machine-readable summary of how the technical price was resolved."""

    if "Technical_Price_Source" not in frame:
        return {}
    counts = frame["Technical_Price_Source"].value_counts(dropna=False)
    return {str(key): int(value) for key, value in counts.items()}


def _as_bool(series: pd.Series) -> pd.Series:
    return series.map(
        lambda value: value is True
        or (isinstance(value, (int, float)) and value == 1)
        or str(value).strip().lower() in {"true", "1", "yes"}
    )


def _attach_stored_transcript_evidence(
    frame: pd.DataFrame,
    config,
    *,
    analysis_date: date,
) -> pd.DataFrame:
    """Translate stored transcript observations into the v4 evidence contract."""

    enriched = frame.copy()
    calls = enriched.get(
        "Transcript_Call_Date", pd.Series("", index=enriched.index)
    ).fillna("").astype(str)
    scores = pd.to_numeric(
        enriched.get("Transcript_Score", pd.Series(np.nan, index=enriched.index)),
        errors="coerce",
    )
    max_age = int(getattr(config, "TRANSCRIPT_MAX_EVIDENCE_AGE_DAYS", 180))
    half_life = float(getattr(config, "TRANSCRIPT_RECENCY_HALF_LIFE_DAYS", 90.0))
    evidence = calls.map(
        lambda call: classify_transcript_evidence(
            call,
            as_of=analysis_date,
            max_age_days=max_age,
            market_holidays=getattr(config, "NSE_MARKET_HOLIDAYS", ()),
        )
    )
    age_weights = calls.map(
        lambda call: recency_weight(
            call,
            today=analysis_date,
            half_life_days=half_life,
            max_age_days=max_age,
        )
    )
    cycle_details = evidence.map(
        lambda item: cycle_transition_confidence(
            item.period_end,
            analysis_date,
            getattr(config, "TRANSCRIPT_CYCLE_TAPER_DAYS", 20),
            getattr(config, "NSE_MARKET_HOLIDAYS", ()),
        )
    )
    cycle_weights = cycle_details.map(lambda item: item[0])
    weights = age_weights * cycle_weights
    current_cycle = evidence.map(lambda item: item.status == CURRENT_CYCLE)
    eligible = current_cycle & scores.notna() & weights.gt(0)
    if not getattr(config, "TRANSCRIPT_SENTIMENT_ENABLED", True):
        eligible[:] = False

    effective = 50.0 + (scores - 50.0) * weights
    transcript_weight = float(getattr(config, "TRANSCRIPT_SENTIMENT_WEIGHT", 0.15))
    transcript_weight = min(1.0, max(0.0, transcript_weight))
    risk = pd.to_numeric(
        enriched.get("Transcript_Risk", pd.Series(np.nan, index=enriched.index)),
        errors="coerce",
    )
    guidance = enriched.get(
        "Transcript_Guidance", pd.Series("", index=enriched.index)
    ).fillna("").astype(str).str.lower()
    minimum_score = float(getattr(config, "TRANSCRIPT_MIN_PRIORITY_SCORE", 55.0))
    maximum_risk = float(getattr(config, "TRANSCRIPT_MAX_PRIORITY_RISK", 60.0))
    quality = (
        eligible
        & scores.ge(minimum_score)
        & (risk.isna() | risk.le(maximum_risk))
        & ~guidance.eq("lowered")
    )

    has_transcript = calls.str.strip().ne("") & scores.notna()
    status = pd.Series("No transcript", index=enriched.index, dtype=object)
    status.loc[has_transcript] = "Expired"
    status.loc[evidence.map(lambda item: item.status == PRIOR_CYCLE)] = (
        "Prior-cycle"
    )
    status.loc[eligible] = "Available"
    enriched["Transcript_Status"] = status
    enriched["Transcript_Fallback_Used"] = status.eq("Prior-cycle")
    enriched["Management_Evidence_Path"] = "No transcript; base model retained"
    enriched.loc[status.eq("Expired"), "Management_Evidence_Path"] = (
        "Expired transcript; base model retained"
    )
    enriched.loc[status.eq("Prior-cycle"), "Management_Evidence_Path"] = (
        "Prior-cycle transcript; informational only"
    )
    enriched.loc[status.eq("Available"), "Management_Evidence_Path"] = (
        "Current-cycle transcript"
    )

    enriched["Transcript_Evidence_Status"] = evidence.map(lambda item: item.status)
    enriched["Transcript_Age_Days"] = evidence.map(lambda item: item.age_days)
    enriched["Transcript_Evidence_Period"] = evidence.map(
        lambda item: item.period_end.isoformat() if item.period_end else ""
    )
    enriched["Transcript_Expected_Period"] = evidence.map(
        lambda item: (
            item.expected_period_end.isoformat()
            if item.expected_period_end else ""
        )
    )
    enriched["Transcript_Recency_Weight"] = weights
    enriched["Transcript_Cycle_Weight"] = cycle_weights
    enriched["Transcript_Cycle_Transition_Date"] = cycle_details.map(
        lambda item: item[1].isoformat() if item[1] else ""
    )
    enriched["Transcript_Days_To_Cycle_Transition"] = cycle_details.map(
        lambda item: item[2]
    )
    enriched["Transcript_Weighted_Score"] = round_series_half_up(
        effective.where(weights.gt(0)), 2
    )
    enriched["Transcript_Scoring_Eligible"] = eligible
    enriched["Transcript_Blend_Eligible"] = eligible
    enriched["Transcript_Downside_Applied"] = eligible & scores.lt(50.0)
    enriched["Transcript_Priority_Applied"] = False
    enriched["Transcript_Quality_Eligible"] = quality
    quality_failures = []
    for index in enriched.index:
        failures = []
        if eligible.loc[index]:
            if scores.loc[index] < minimum_score:
                failures.append("Sentiment below priority threshold")
            if risk.loc[index] > maximum_risk:
                failures.append("Risk above priority threshold")
            if guidance.loc[index] == "lowered":
                failures.append("Guidance lowered")
        quality_failures.append(failures)
    enriched["Transcript_Quality_Gate"] = [
        "; ".join(items)
        if items
        else "Passed"
        if bool(eligible.loc[index])
        else "No eligible transcript"
        for index, items in zip(enriched.index, quality_failures)
    ]
    enriched["Transcript_Quality_Gate_Failures"] = [
        json.dumps(items, separators=(",", ":")) for items in quality_failures
    ]
    enriched["Transcript_Quality_Gate_Failure_Count"] = [
        len(items) for items in quality_failures
    ]
    tone = pd.Series("unknown", index=enriched.index, dtype=object)
    tone.loc[eligible & scores.lt(45)] = "negative"
    tone.loc[eligible & scores.between(45, 55, inclusive="left")] = "cautious"
    tone.loc[eligible & scores.ge(55)] = "positive"
    enriched["Transcript_Tone_Direction"] = tone
    enriched["Transcript_Technical_Gate"] = "No eligible transcript"
    enriched.loc[eligible, "Transcript_Technical_Gate"] = (
        "Downside-only evidence; finalized centrally"
    )
    applied_weight = transcript_weight * weights
    enriched["Transcript_Blend_Weight"] = np.where(eligible, applied_weight, 0.0)
    enriched["Transcript_Effective_Score"] = round_series_half_up(
        scores.where(eligible), 2
    )
    enriched["Transcript_Proposed_Delta_Core"] = (
        applied_weight * np.minimum(scores - 50.0, 0.0)
    ).where(eligible, 0.0)
    enriched["Transcript_Proposed_Delta_Core"] = round_series_half_up(
        enriched["Transcript_Proposed_Delta_Core"], 2
    )
    enriched["Transcript_Signal_Direction"] = "unknown"
    enriched.loc[eligible, "Transcript_Signal_Direction"] = "neutral"
    enriched.loc[
        eligible & enriched["Transcript_Proposed_Delta_Core"].lt(0),
        "Transcript_Signal_Direction",
    ] = "downside"
    enriched["Transcript_Summary"] = status
    if eligible.any():
        enriched.loc[eligible, "Transcript_Summary"] = (
            scores.loc[eligible]
            .map(lambda value: f"Replayed score {value:.1f}")
            .astype(str)
            + " | "
            + guidance.loc[eligible].replace("", "unclear").str.title()
            + " | "
            + calls.loc[eligible].str[:10]
        )
    prior = status.eq("Prior-cycle")
    if prior.any():
        enriched.loc[prior, "Transcript_Summary"] = (
            "Prior-cycle evidence | "
            + scores.loc[prior].map(lambda value: f"{value:.1f}").astype(str)
            + " | "
            + calls.loc[prior].str[:10]
        )
    return enriched


def replay_export_frame(
    source: pd.DataFrame,
    config,
    *,
    analysis_date: date,
) -> pd.DataFrame:
    """Replay v4 over raw observations retained in a historical export."""

    if source is None or source.empty:
        raise ValueError("source export is empty")
    if "Symbol" not in source:
        raise ValueError("source export has no Symbol column")
    if source["Symbol"].astype(str).duplicated().any():
        raise ValueError("source export contains duplicate symbols")

    drop_columns = [
        column
        for column in source.columns
        if column in DECISION_COLUMNS
        or column in MODEL_PROVENANCE_COLUMNS
        or column.startswith("Run_")
        or column.startswith("DCF_")
        or column.startswith("Pre_DCF_")
        or column.startswith("Decision_")
        or (
            column.startswith("Transcript_")
            and column not in STORED_TRANSCRIPT_INPUT_COLUMNS
        )
    ]
    working = source.drop(columns=drop_columns, errors="ignore").copy()
    working = align_valuation_to_completed_price_bar(working)
    working = apply_replay_technical_price_proxy(working)
    scored = StockScorer(config).score_all_stocks(working)
    if getattr(config, "REVERSE_DCF_ENABLED", True):
        scored = ReverseDCFModel(config).enrich(scored)
    scored = _attach_stored_transcript_evidence(
        scored, config, analysis_date=analysis_date
    )
    finalized = finalize_recommendations(scored, config)
    finalized = LiquidityQualityEnricher(config).enrich(finalized)
    ranked = rank_actionable_recommendations(finalized)
    return attach_replay_provenance(
        ranked,
        config,
        analysis_date=analysis_date,
    )
