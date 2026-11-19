"""US earnings-call transcripts from Alpha Vantage (``EARNINGS_CALL_TRANSCRIPT``).

One request returns one call, by symbol and fiscal quarter (``2026Q3``), as a list
of speaker turns. Each turn becomes a "Name (Title):" heading line, which the
segmenter already reads as a speaker change (its role read from both), so the
tone and outlook scores need no US branch. Alpha Vantage's own per-turn
sentiment is dropped: our models score the call.

Alpha Vantage free key: personal, non-commercial use only (ToS s.2a), 25 requests a
day across every caller of the key.
"""

from __future__ import annotations

from typing import Any

URL = "https://www.alphavantage.co/query"
KEY_ENV = "ALPHAVANTAGE_API_KEY"
TIMEOUT_SECONDS = 60


class Refused(RuntimeError):
    """The API answered with a note instead of data: the day's allowance is spent, or the key is bad."""


def fetch_transcript(symbol: str, quarter: str, key: str) -> dict[str, Any]:
    import requests

    response = requests.get(
        URL,
        params={"function": "EARNINGS_CALL_TRANSCRIPT", "symbol": symbol, "quarter": quarter, "apikey": key},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def transcript_text(payload: dict[str, Any]) -> str:
    """The call as text, one turn per paragraph; "" when Alpha Vantage has no transcript yet.

    A refusal arrives as HTTP 200 with an ``Information``, ``Note`` or
    ``Error Message`` field and no transcript; it raises rather than reading as an
    empty call, so the caller stops instead of marking calls as missing.
    """
    turns = payload.get("transcript")
    if not turns:
        note = next((payload[k] for k in ("Information", "Note", "Error Message") if payload.get(k)), None)
        if note:
            raise Refused(str(note)[:300])
        return ""
    paragraphs = []
    for turn in turns:
        content = " ".join(str(turn.get("content") or "").split())
        if not content:
            continue
        speaker = " ".join(str(turn.get("speaker") or "").split()) or "Unknown"
        title = " ".join(str(turn.get("title") or "").split())
        heading = f"{speaker} ({title}):" if title and title.lower() != speaker.lower() else f"{speaker}:"
        paragraphs.append(f"{heading}\n{content}")
    return "\n\n".join(paragraphs)
