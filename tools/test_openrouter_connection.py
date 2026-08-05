"""Run one minimal OpenRouter schema-validation probe using an environment key."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentiment.openrouter_client import OpenRouterClient
from sentiment.schemas import ChunkSentiment


def main() -> None:
    client = OpenRouterClient(
        os.getenv("OPENROUTER_API_KEY", ""),
        os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
        max_retries=1,
        timeout_seconds=90,
    )
    prompt = """Return exactly one JSON object with these fields:
optimism, guidance_strength, management_confidence, risk_intensity,
analyst_pressure, answer_quality as integer scores from 0 to 100;
guidance_direction as unclear; revenue_outlook, margin_outlook,
demand_outlook as strings; catalysts, risks, evidence as arrays of strings.
Use this source text only: Revenue grew 18 percent, management maintained
guidance, and input costs remain a risk."""
    payload = client.analyze_chunk(prompt)
    print(json.dumps(ChunkSentiment.from_payload(payload).to_dict(), indent=2))


if __name__ == "__main__":
    main()