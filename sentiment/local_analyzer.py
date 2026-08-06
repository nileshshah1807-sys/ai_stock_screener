"""Deterministic local sentiment features for earnings-call excerpts."""

from __future__ import annotations

import re

from textblob import TextBlob

from .schemas import ChunkSentiment


POSITIVE_TERMS = {
    "accelerating", "beat", "beats", "bullish", "demand", "expansion", "growth",
    "improved", "improving", "momentum", "outperform", "profitable", "recovery",
    "resilient", "strong", "tailwind", "visibility",
}
NEGATIVE_TERMS = {
    "challenge", "challenges", "contraction", "decline", "headwind", "loss",
    "pressure", "slowdown", "softness", "volatility", "weak", "weakness",
}
UNCERTAINTY_TERMS = {
    "cautious", "could", "may", "risk", "risks", "uncertain", "uncertainty",
    "visibility", "volatile",
}
RAISED_GUIDANCE = ("raise guidance", "raised guidance", "increase guidance", "upward revision")
LOWERED_GUIDANCE = ("lower guidance", "lowered guidance", "cut guidance", "withdraw guidance")
MAINTAINED_GUIDANCE = ("maintain guidance", "maintained guidance", "reaffirm guidance", "reaffirmed guidance")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-zA-Z']+")


class LocalSentimentAnalyzer:
    """Score an excerpt with TextBlob polarity plus finance-domain term counts."""

    def analyze_chunk(self, text: str) -> dict[str, object]:
        sentences = _sentences(text)
        tokens = _tokens(text)
        positive_hits = sum(token in POSITIVE_TERMS for token in tokens)
        negative_hits = sum(token in NEGATIVE_TERMS for token in tokens)
        uncertainty_hits = sum(token in UNCERTAINTY_TERMS for token in tokens)
        polarity = _weighted_polarity(sentences)
        lexical_balance = (positive_hits - negative_hits) / max(1, positive_hits + negative_hits)
        optimism = _scale((polarity * 0.6) + (lexical_balance * 0.4))
        guidance_direction = _guidance_direction(text)
        guidance_strength = _guidance_strength(guidance_direction, text)
        risk_intensity = _bounded(50 + 8 * negative_hits + 5 * uncertainty_hits - 5 * positive_hits)
        management_confidence = _bounded(optimism - 4 * uncertainty_hits + 12 if guidance_direction == "raised" else optimism - 4 * uncertainty_hits)
        analyst_pressure = _bounded(30 + 8 * len(re.findall(r"\?", text)) + 6 * uncertainty_hits)
        answer_quality = _bounded(45 + min(35, len(sentences) * 3) + (10 if "q&a" in text.lower() else 0))
        catalysts = _evidence(sentences, POSITIVE_TERMS)
        risks = _evidence(sentences, NEGATIVE_TERMS | UNCERTAINTY_TERMS)
        evidence = _evidence(sentences, POSITIVE_TERMS | NEGATIVE_TERMS | UNCERTAINTY_TERMS)
        return ChunkSentiment(
            optimism=optimism,
            guidance_strength=guidance_strength,
            management_confidence=management_confidence,
            risk_intensity=risk_intensity,
            analyst_pressure=analyst_pressure,
            answer_quality=answer_quality,
            guidance_direction=guidance_direction,
            revenue_outlook=_outlook(text, ("revenue", "sales", "growth")),
            margin_outlook=_outlook(text, ("margin", "profit", "cost")),
            demand_outlook=_outlook(text, ("demand", "volume", "order")),
            catalysts=catalysts,
            risks=risks,
            evidence=evidence,
        ).to_dict()


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT.split(text) if sentence.strip()]


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _WORD.findall(text)]


def _weighted_polarity(sentences: list[str]) -> float:
    if not sentences:
        return 0.0
    weights = [max(1, len(_tokens(sentence))) for sentence in sentences]
    return sum(TextBlob(sentence).sentiment.polarity * weight for sentence, weight in zip(sentences, weights)) / sum(weights)


def _guidance_direction(text: str) -> str:
    normalized = text.lower()
    if any(phrase in normalized for phrase in LOWERED_GUIDANCE):
        return "lowered"
    if any(phrase in normalized for phrase in RAISED_GUIDANCE):
        return "raised"
    if any(phrase in normalized for phrase in MAINTAINED_GUIDANCE):
        return "maintained"
    return "unclear"


def _guidance_strength(direction: str, text: str) -> float:
    if direction == "raised":
        return 85.0
    if direction == "maintained":
        return 65.0
    if direction == "lowered":
        return 20.0
    return 50.0 if "guidance" in text.lower() else 35.0


def _outlook(text: str, terms: tuple[str, ...]) -> str:
    relevant = " ".join(sentence.lower() for sentence in _sentences(text) if any(term in sentence.lower() for term in terms))
    if not relevant:
        return ""
    balance = sum(token in POSITIVE_TERMS for token in _tokens(relevant)) - sum(token in NEGATIVE_TERMS for token in _tokens(relevant))
    return "positive" if balance > 0 else "negative" if balance < 0 else "neutral"


def _evidence(sentences: list[str], terms: set[str]) -> list[str]:
    selected: list[str] = []
    for sentence in sentences:
        sentence_terms = set(_tokens(sentence))
        if not sentence_terms & terms:
            continue
        selected.append(sentence[:100])
        if len(selected) == 2:
            break
    return selected


def _scale(value: float) -> float:
    return round(_bounded(50 + 50 * value), 2)


def _bounded(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)