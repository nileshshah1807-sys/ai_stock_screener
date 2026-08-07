"""Deterministic aggregation for local transcript sentiment features."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from transcripts.chunker import TranscriptChunk, build_chunks
from transcripts.segmenter import segment_transcript

from .local_analyzer import LocalSentimentAnalyzer
from .schemas import ChunkSentiment


ANALYSIS_VERSION = "v5-management-weighted-finance-structure"


def analyze_transcript(cleaned_text: str) -> dict[str, Any]:
    segments = segment_transcript(cleaned_text)
    chunks = build_chunks(segments)
    if not chunks:
        raise ValueError("transcript contains no analyzable text")
    analyzer = LocalSentimentAnalyzer()
    payloads = [analyzer.analyze_chunk(chunk.text) for chunk in chunks]
    analyses = [ChunkSentiment.from_payload(payload) for payload in payloads]
    return aggregate_sentiments(analyses, chunks, payloads)


def aggregate_sentiments(
    analyses: list[ChunkSentiment],
    chunks: list[TranscriptChunk],
    feature_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not analyses or len(analyses) != len(chunks):
        raise ValueError("analyses and chunks must be non-empty and aligned")
    sections = [_chunk_section(chunk) for chunk in chunks]
    management_indexes = [
        index for index, section in enumerate(sections)
        if section in {"prepared_remarks", "management_answer"}
    ]
    core_indexes = management_indexes or list(range(len(chunks)))
    analyst_indexes = [index for index, section in enumerate(sections) if section == "analyst_question"]
    answer_indexes = [index for index, section in enumerate(sections) if section == "management_answer"]
    score_keys = (
        "optimism", "guidance_strength", "management_confidence", "risk_intensity",
        "analyst_pressure", "answer_quality",
    )
    output = {}
    for key in score_keys:
        indexes = core_indexes
        if key == "analyst_pressure" and analyst_indexes:
            indexes = analyst_indexes
        elif key == "answer_quality" and answer_indexes:
            indexes = answer_indexes
        output[key] = _weighted_metric(analyses, chunks, indexes, key)

    # Explicit guidance is categorical evidence; it should not be decided by
    # whichever containing chunk happens to be longest. A detected reduction is
    # conservatively dominant, followed by raised and then maintained guidance.
    directions = {analyses[index].guidance_direction for index in core_indexes}
    output["guidance_direction"] = next(
        (direction for direction in ("lowered", "raised", "maintained") if direction in directions),
        "unclear",
    )
    for key in ("revenue_outlook", "margin_outlook", "demand_outlook"):
        output[key] = _weighted_outlook(analyses, chunks, core_indexes, key)
    for key in ("catalysts", "risks", "evidence"):
        output[key] = _unique_items(item for analysis in analyses for item in getattr(analysis, key))[:20]
    output["overall_score"] = round(
        output["optimism"] * 0.25
        + output["management_confidence"] * 0.20
        + output["guidance_strength"] * 0.20
        + (100 - output["risk_intensity"]) * 0.20
        + output["answer_quality"] * 0.15,
        2,
    )
    output["confidence_score"] = output["management_confidence"]
    if feature_payloads is not None:
        if len(feature_payloads) != len(chunks):
            raise ValueError("feature_payloads and chunks must be aligned")
        _add_hybrid_features(output, analyses, chunks, feature_payloads)
    return output


def _unique_items(items: Any) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            unique.append(normalized)
    return unique


def _chunk_section(chunk: TranscriptChunk) -> str:
    text = chunk.text.lstrip()
    if not text.startswith("[") or "]" not in text:
        return "unknown"
    return text[1:text.index("]")].strip().lower()


def _weighted_metric(
    analyses: list[ChunkSentiment],
    chunks: list[TranscriptChunk],
    indexes: list[int],
    key: str,
) -> float:
    total_weight = sum(max(1, chunks[index].estimated_tokens) for index in indexes)
    return round(
        sum(
            getattr(analyses[index], key) * max(1, chunks[index].estimated_tokens)
            for index in indexes
        ) / total_weight,
        2,
    )


def _weighted_outlook(
    analyses: list[ChunkSentiment],
    chunks: list[TranscriptChunk],
    indexes: list[int],
    key: str,
) -> str:
    votes: defaultdict[str, int] = defaultdict(int)
    fallback = ""
    for index in indexes:
        value = str(getattr(analyses[index], key) or "").strip()
        if not value:
            continue
        fallback = fallback or value
        if value.lower() in {"positive", "negative", "neutral"}:
            votes[value.lower()] += max(1, chunks[index].estimated_tokens)
    if votes:
        # Prefer the more conservative interpretation when weighted votes tie.
        return max(votes, key=lambda value: (votes[value], {"negative": 2, "neutral": 1, "positive": 0}[value]))
    return fallback


def _add_hybrid_features(
    output: dict[str, Any],
    analyses: list[ChunkSentiment],
    chunks: list[TranscriptChunk],
    payloads: list[dict[str, Any]],
) -> None:
    """Preserve diagnostic metrics and compare prepared remarks with Q&A."""
    for key in (
        "textblob_polarity",
        "finbert_score",
        "financial_lexicon_score",
        "uncertainty_density",
        "constraint_density",
        "forward_looking_density",
        "model_disagreement",
    ):
        value = _weighted_payload_value(payloads, chunks, key)
        output[key] = round(value, 4) if value is not None else None

    prepared = _section_analyses("prepared_remarks", analyses, chunks)
    management_qa = _section_analyses("management_answer", analyses, chunks)
    prepared_optimism = _weighted_analysis_value(prepared, "optimism")
    management_qa_optimism = _weighted_analysis_value(management_qa, "optimism")
    prepared_confidence = _weighted_analysis_value(prepared, "management_confidence")
    management_qa_confidence = _weighted_analysis_value(management_qa, "management_confidence")
    output.update({
        "prepared_optimism": prepared_optimism,
        "management_qa_optimism": management_qa_optimism,
        "prepared_confidence": prepared_confidence,
        "management_qa_confidence": management_qa_confidence,
        "prepared_vs_qa_tone_gap": _difference(prepared_optimism, management_qa_optimism),
        "qa_confidence_drop": _difference(prepared_confidence, management_qa_confidence),
    })
    output["review_flag"] = bool(
        (output["model_disagreement"] or 0) >= 0.50
        or (output["qa_confidence_drop"] or 0) >= 20
    )


def _weighted_payload_value(
    payloads: list[dict[str, Any]], chunks: list[TranscriptChunk], key: str
) -> float | None:
    values = [
        (float(payload[key]), max(1, chunk.estimated_tokens))
        for payload, chunk in zip(payloads, chunks)
        if isinstance(payload.get(key), (int, float)) and not isinstance(payload.get(key), bool)
    ]
    if not values:
        return None
    total_weight = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / total_weight


def _section_analyses(
    section: str, analyses: list[ChunkSentiment], chunks: list[TranscriptChunk]
) -> list[tuple[ChunkSentiment, TranscriptChunk]]:
    prefix = f"[{section}]"
    return [
        (analysis, chunk)
        for analysis, chunk in zip(analyses, chunks)
        if chunk.text.lstrip().lower().startswith(prefix)
    ]


def _weighted_analysis_value(
    items: list[tuple[ChunkSentiment, TranscriptChunk]], key: str
) -> float | None:
    if not items:
        return None
    total_weight = sum(max(1, chunk.estimated_tokens) for _, chunk in items)
    return round(
        sum(getattr(analysis, key) * max(1, chunk.estimated_tokens) for analysis, chunk in items) / total_weight,
        2,
    )


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 2)
