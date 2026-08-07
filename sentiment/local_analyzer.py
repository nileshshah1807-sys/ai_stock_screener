"""Hybrid local sentiment features for earnings-call excerpts.

TextBlob remains a transparent baseline, while FinBERT (when installed) and a
financial-language lexicon drive the production-oriented score.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from textblob import TextBlob

from .schemas import ChunkSentiment


POSITIVE_TERMS = {
    "accelerating", "beat", "beats", "bullish", "expansion", "growth",
    "improved", "improving", "momentum", "outperform", "profitable", "recovery",
    "resilient", "strong", "tailwind",
}
NEGATIVE_TERMS = {
    "challenge", "challenges", "contraction", "decline", "headwind", "impairment",
    "loss", "pressure", "slowdown", "softness", "volatility", "weak", "weakness",
}
UNCERTAINTY_TERMS = {
    "approximately", "cautious", "could", "may", "possibly", "risk", "risks",
    "uncertain", "uncertainty", "visibility", "volatile",
}
CONSTRAINT_TERMS = {
    "approval", "commodity", "constraint", "constraints", "currency", "disruption",
    "inflation", "litigation", "regulatory", "supply", "tariff",
}
STRONG_MODAL_TERMS = {"will", "confident", "committed", "expect", "expects", "plan", "plans"}
WEAK_MODAL_TERMS = {"aim", "believe", "could", "may", "might", "target", "try"}
FORWARD_LOOKING_TERMS = {
    "forecast", "guidance", "outlook", "quarter", "expect", "expects", "will", "plan",
    "plans", "target", "targets", "next", "future",
}
RAISED_GUIDANCE = re.compile(
    r"\b(?:raise[ds]?|increase[ds]?|upgrade[ds]?|revis(?:e[ds]?|ion)\s+upward)\s+(?:our\s+)?"
    r"(?:guidance|outlook|forecast|expectations?)\b",
    re.IGNORECASE,
)
LOWERED_GUIDANCE = re.compile(
    r"\b(?:lower(?:ed|ing)?|cut|withdraw(?:n)?|reduce[ds]?|revis(?:e[ds]?|ion)\s+downward)\s+(?:our\s+)?"
    r"(?:guidance|outlook|forecast|expectations?)\b",
    re.IGNORECASE,
)
MAINTAINED_GUIDANCE = re.compile(
    r"\b(?:maintain(?:ed|ing)?|reaffirm(?:ed|ing)?|stand(?:ing)?\s+by|unchanged|remain(?:s|ed)?\s+unchanged)"
    r"\s+(?:our\s+)?(?:guidance|outlook|forecast|expectations?)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-zA-Z']+")
_SECTION = re.compile(r"^\[(?P<section>[^]]+)\]", re.IGNORECASE)


class LocalSentimentAnalyzer:
    """Score excerpts with financial lexicons and an optional FinBERT signal."""

    def analyze_chunk(self, text: str) -> dict[str, object]:
        sentences = _sentences(text)
        tokens = _tokens(text)
        positive_hits = _hits(tokens, POSITIVE_TERMS)
        negative_hits = _hits(tokens, NEGATIVE_TERMS)
        uncertainty_hits = _hits(tokens, UNCERTAINTY_TERMS)
        constraint_hits = _hits(tokens, CONSTRAINT_TERMS)
        strong_modal_hits = _hits(tokens, STRONG_MODAL_TERMS)
        weak_modal_hits = _hits(tokens, WEAK_MODAL_TERMS)
        textblob_polarity = _weighted_polarity(sentences)
        lexical_balance = (positive_hits - negative_hits) / max(1, positive_hits + negative_hits)
        finbert_score = _finbert_score(sentences)
        sentiment_signal = _sentiment_signal(finbert_score, lexical_balance, textblob_polarity)
        optimism = _scale(sentiment_signal)
        uncertainty_density = _density(uncertainty_hits, tokens)
        constraint_density = _density(constraint_hits, tokens)
        section = _section(text)
        guidance_direction = _guidance_direction(text)
        guidance_strength = _guidance_strength(guidance_direction, text)
        risk_intensity = _bounded(
            45 + 7 * negative_hits + 6 * uncertainty_hits + 5 * constraint_hits - 4 * positive_hits
        )
        management_confidence = _bounded(
            optimism + 4 * strong_modal_hits - 5 * weak_modal_hits - 40 * uncertainty_density
            + (12 if guidance_direction == "raised" else 0)
        )
        analyst_pressure = _bounded(
            25 + 8 * len(re.findall(r"\?", text)) + 4 * uncertainty_hits + 3 * negative_hits
            + (10 if section == "analyst_question" else 0)
        )
        answer_quality = _bounded(
            45 + min(35, len(sentences) * 3) + (10 if section == "management_answer" else 0)
        )
        catalysts = _evidence(sentences, POSITIVE_TERMS)
        risks = _evidence(sentences, NEGATIVE_TERMS | UNCERTAINTY_TERMS | CONSTRAINT_TERMS)
        evidence = _evidence(sentences, POSITIVE_TERMS | NEGATIVE_TERMS | UNCERTAINTY_TERMS | CONSTRAINT_TERMS)
        output = ChunkSentiment(
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
        output.update({
            "section": section,
            "textblob_polarity": round(textblob_polarity, 4),
            "finbert_score": round(finbert_score, 4) if finbert_score is not None else None,
            "financial_lexicon_score": round(lexical_balance, 4),
            "uncertainty_density": round(uncertainty_density, 4),
            "constraint_density": round(constraint_density, 4),
            "forward_looking_density": round(_density(_hits(tokens, FORWARD_LOOKING_TERMS), tokens), 4),
            "model_disagreement": round(abs(textblob_polarity - finbert_score), 4) if finbert_score is not None else 0.0,
        })
        return output


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT.split(text) if sentence.strip()]


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _WORD.findall(text)]


def _hits(tokens: list[str], terms: set[str]) -> int:
    return sum(token in terms for token in tokens)


def _density(hits: int, tokens: list[str]) -> float:
    return hits / max(1, len(tokens))


def _weighted_polarity(sentences: list[str]) -> float:
    if not sentences:
        return 0.0
    weights = [max(1, len(_tokens(sentence))) for sentence in sentences]
    return sum(TextBlob(sentence).sentiment.polarity * weight for sentence, weight in zip(sentences, weights)) / sum(weights)


def _sentiment_signal(finbert_score: float | None, lexical_balance: float, textblob_polarity: float) -> float:
    if finbert_score is not None:
        return finbert_score * 0.70 + lexical_balance * 0.20 + textblob_polarity * 0.10
    return lexical_balance * 0.55 + textblob_polarity * 0.45


@lru_cache(maxsize=1)
def _finbert_pipeline():
    if os.getenv("TRANSCRIPT_ENABLE_FINBERT", "1").strip().lower() in {"0", "false", "no"}:
        return None
    try:
        from transformers import pipeline

        return pipeline("sentiment-analysis", model="ProsusAI/finbert", tokenizer="ProsusAI/finbert")
    except Exception as exc:
        if _finbert_required():
            raise RuntimeError("FinBERT is required but could not be loaded") from exc
        return None


def _finbert_score(sentences: list[str]) -> float | None:
    classifier = _finbert_pipeline()
    if classifier is None or not sentences:
        return None
    try:
        results = classifier(sentences, truncation=True, max_length=512, batch_size=16)
    except Exception as exc:
        if _finbert_required():
            raise RuntimeError("FinBERT inference failed") from exc
        return None
    label_scores = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
    values = [label_scores.get(str(result["label"]).lower(), 0.0) * float(result["score"]) for result in results]
    return sum(values) / len(values) if values else None


def _section(text: str) -> str:
    match = _SECTION.match(text.strip())
    return match.group("section").lower() if match else "unknown"


def _guidance_direction(text: str) -> str:
    if LOWERED_GUIDANCE.search(text):
        return "lowered"
    if RAISED_GUIDANCE.search(text):
        return "raised"
    if MAINTAINED_GUIDANCE.search(text):
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
    positive = sum(term in relevant for term in POSITIVE_TERMS)
    negative = sum(term in relevant for term in NEGATIVE_TERMS)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral" if relevant else ""


def _evidence(sentences: list[str], terms: set[str]) -> list[str]:
    return [sentence for sentence in sentences if any(token in terms for token in _tokens(sentence))][:3]


def _scale(value: float) -> float:
    return _bounded(50 + 50 * value)


def _bounded(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _finbert_required() -> bool:
    return os.getenv("TRANSCRIPT_REQUIRE_FINBERT", "0").strip().lower() in {
        "1", "true", "yes"
    }
