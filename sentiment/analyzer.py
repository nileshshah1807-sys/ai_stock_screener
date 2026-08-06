"""Deterministic aggregation for local transcript sentiment features."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from transcripts.chunker import TranscriptChunk, build_chunks
from transcripts.segmenter import segment_transcript

from .local_analyzer import LocalSentimentAnalyzer
from .schemas import ChunkSentiment


ANALYSIS_VERSION = "v3-local-textblob-finance-lexicon"


def analyze_transcript(cleaned_text: str) -> dict[str, Any]:
    segments = segment_transcript(cleaned_text)
    chunks = build_chunks(segments)
    if not chunks:
        raise ValueError("transcript contains no analyzable text")
    analyzer = LocalSentimentAnalyzer()
    analyses = [ChunkSentiment.from_payload(analyzer.analyze_chunk(chunk.text)) for chunk in chunks]
    return aggregate_sentiments(analyses, chunks)


def aggregate_sentiments(analyses: list[ChunkSentiment], chunks: list[TranscriptChunk]) -> dict[str, Any]:
    if not analyses or len(analyses) != len(chunks):
        raise ValueError("analyses and chunks must be non-empty and aligned")
    total_weight = sum(max(1, chunk.estimated_tokens) for chunk in chunks)
    score_keys = (
        "optimism", "guidance_strength", "management_confidence", "risk_intensity",
        "analyst_pressure", "answer_quality",
    )
    output = {
        key: round(
            sum(getattr(analysis, key) * max(1, chunk.estimated_tokens) for analysis, chunk in zip(analyses, chunks))
            / total_weight,
            2,
        )
        for key in score_keys
    }
    direction_votes: defaultdict[str, int] = defaultdict(int)
    for analysis, chunk in zip(analyses, chunks):
        if analysis.guidance_direction != "unclear":
            direction_votes[analysis.guidance_direction] += max(1, chunk.estimated_tokens)
    output["guidance_direction"] = max(direction_votes, key=direction_votes.get) if direction_votes else "unclear"
    for key in ("revenue_outlook", "margin_outlook", "demand_outlook"):
        output[key] = next((getattr(analysis, key) for analysis in analyses if getattr(analysis, key)), "")
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