"""Validation types for model-produced transcript sentiment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


_DIRECTIONS = {"raised", "maintained", "lowered", "unclear"}


def _score(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number between 0 and 100")
    value = float(value)
    if not 0 <= value <= 100:
        raise ValueError(f"{key} must be between 0 and 100")
    return value


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


@dataclass(frozen=True)
class ChunkSentiment:
    optimism: float
    guidance_strength: float
    management_confidence: float
    risk_intensity: float
    analyst_pressure: float
    answer_quality: float
    guidance_direction: str
    revenue_outlook: str
    margin_outlook: str
    demand_outlook: str
    catalysts: list[str]
    risks: list[str]
    evidence: list[str]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ChunkSentiment":
        if not isinstance(payload, dict):
            raise ValueError("model response must be a JSON object")
        direction = str(payload.get("guidance_direction", "unclear")).strip().lower()
        if direction not in _DIRECTIONS:
            direction = "unclear"
        return cls(
            optimism=_score(payload, "optimism"),
            guidance_strength=_score(payload, "guidance_strength"),
            management_confidence=_score(payload, "management_confidence"),
            risk_intensity=_score(payload, "risk_intensity"),
            analyst_pressure=_score(payload, "analyst_pressure"),
            answer_quality=_score(payload, "answer_quality"),
            guidance_direction=direction,
            revenue_outlook=str(payload.get("revenue_outlook", "")).strip(),
            margin_outlook=str(payload.get("margin_outlook", "")).strip(),
            demand_outlook=str(payload.get("demand_outlook", "")).strip(),
            catalysts=_string_list(payload, "catalysts"),
            risks=_string_list(payload, "risks"),
            evidence=_string_list(payload, "evidence"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)