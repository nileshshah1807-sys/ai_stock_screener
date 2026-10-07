"""Structured outlook extraction from an earnings-call transcript.

The word-list score in `local_analyzer` measures how a call *sounds*. This
module asks a language model what the call *said*: the guidance given and
whether it moved, the order book, capacity coming on line, demand and margins.

Two rules keep a cheap model honest:

* **Every extracted item carries the sentence it came from.** `verify_quotes`
  checks that the quote appears in the transcript and clears any item whose
  quote does not, so an invented figure never reaches the score. It cannot
  catch a real sentence that was misread -- a segment's order book reported as
  the company's -- only one that was made up.
* **Nothing is scored that was not stated.** A field the call did not address
  is null and contributes nothing; `outlook_score` starts at 50 and moves only
  on verified items.

The point weights in `outlook_score` are a judgment, not a fitted model: there
is no history of extractions to fit against yet. They are deliberately lopsided
toward things that are hard to say without meaning them -- a guidance change, a
quantified order book -- and light on expansion plans, which management
announces freely and which predict lower returns on their own (Jha, Qian, Weber
and Yang, NBER w32161).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

OUTLOOK_VERSION = "outlook-v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Calls longer than this are cut from the end. The median call is ~45,000
# characters; the cap only bounds the cost of a pathological document.
MAX_TRANSCRIPT_CHARACTERS = 160_000

GUIDANCE_DIRECTIONS = ("raised", "maintained", "lowered", "none")
TRENDS = ("up", "flat", "down", "unknown")
DEMAND_TONES = ("strong", "stable", "weak", "unknown")
CAPACITY_STATES = ("operational", "ramping", "under_construction", "planned", "none")

_QUOTE = {"type": ["string", "null"]}
_NUMBER = {"type": ["number", "null"]}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "guidance", "order_book", "capacity", "demand", "margin", "tailwinds", "headwinds",
    ],
    "properties": {
        "guidance": {
            "type": "object",
            "additionalProperties": False,
            "required": ["direction", "metric", "growth_pct", "quote"],
            "properties": {
                "direction": {"enum": list(GUIDANCE_DIRECTIONS)},
                "metric": {"type": ["string", "null"]},
                "growth_pct": _NUMBER,
                "quote": _QUOTE,
            },
        },
        "order_book": {
            "type": "object",
            "additionalProperties": False,
            "required": ["value_inr_crore", "revenue_cover_years", "trend", "quote"],
            "properties": {
                "value_inr_crore": _NUMBER,
                "revenue_cover_years": _NUMBER,
                "trend": {"enum": list(TRENDS)},
                "quote": _QUOTE,
            },
        },
        "capacity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["state", "commissioning", "quote"],
            "properties": {
                "state": {"enum": list(CAPACITY_STATES)},
                "commissioning": {"type": ["string", "null"]},
                "quote": _QUOTE,
            },
        },
        "demand": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tone", "quote"],
            "properties": {"tone": {"enum": list(DEMAND_TONES)}, "quote": _QUOTE},
        },
        "margin": {
            "type": "object",
            "additionalProperties": False,
            "required": ["trend", "quote"],
            "properties": {"trend": {"enum": list(TRENDS)}, "quote": _QUOTE},
        },
        "tailwinds": {"type": "array", "maxItems": 3, "items": {"$ref": "#/$defs/item"}},
        "headwinds": {"type": "array", "maxItems": 3, "items": {"$ref": "#/$defs/item"}},
    },
    "$defs": {
        "item": {
            "type": "object",
            "additionalProperties": False,
            "required": ["what", "quote"],
            "properties": {"what": {"type": "string"}, "quote": {"type": "string"}},
        }
    },
}

SYSTEM_PROMPT = """You extract forward-looking facts from an Indian company's \
earnings-call transcript. Report only what management said about the company \
as a whole, in this call. Do not infer, estimate or use outside knowledge.

Rules:
- Every item needs `quote`: one sentence copied exactly from the transcript \
that states it. If you cannot quote it, the value is null (or "none" / \
"unknown"), and the quote is null.
- guidance.direction: "raised" or "lowered" only if management says the \
guidance changed from what it gave before; "maintained" if it restates or \
reaffirms earlier guidance; "none" if no guidance is given. A first-time \
number with no reference to earlier guidance is "maintained".
- guidance.growth_pct: the guided revenue growth for the current or next \
financial year, in percent, as one number (the midpoint of a range). Null if \
the guidance is not a revenue growth rate.
- order_book.value_inr_crore: the company's total order book or backlog in \
rupees crore. Convert lakh, million and billion. Ignore a single segment's or \
subsidiary's figure. revenue_cover_years only if management states it.
- capacity.state: "operational" or "ramping" for capacity already producing; \
"under_construction" for work in progress with spending committed; "planned" \
for intentions. commissioning is the stated start as YYYY-MM, else null.
- demand.tone and margin.trend describe management's stated outlook, not the \
quarter just reported.
- tailwinds and headwinds: at most three each, specific to this company \
(a new approval, a customer win, a tariff, a raw-material cost), not general \
optimism.
Return JSON matching the schema and nothing else."""


def build_messages(company: str, symbol: str, call_date: str, text: str) -> list[dict[str, str]]:
    body = text[:MAX_TRANSCRIPT_CHARACTERS]
    header = f"Company: {company or symbol} ({symbol})\nCall date: {call_date or 'unknown'}\n\nTranscript:\n"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": header + body},
    ]


def _normalise(text: str) -> str:
    """Lower-case, with punctuation and spacing differences removed."""
    return re.sub(r"[^a-z0-9%.]+", " ", str(text).lower()).strip()


def quote_found(quote: str | None, normalised_transcript: str) -> bool:
    """Whether ``quote`` occurs in the transcript, ignoring spacing and case.

    A model trims or rejoins a sentence at a line break, so the test is on the
    normalised text; a quote shorter than four words proves nothing and fails.
    """
    needle = _normalise(quote or "")
    if len(needle.split()) < 4:
        return False
    return needle in normalised_transcript


_EMPTY = {
    "guidance": {"direction": "none", "metric": None, "growth_pct": None, "quote": None},
    "order_book": {"value_inr_crore": None, "revenue_cover_years": None, "trend": "unknown", "quote": None},
    "capacity": {"state": "none", "commissioning": None, "quote": None},
    "demand": {"tone": "unknown", "quote": None},
    "margin": {"trend": "unknown", "quote": None},
}


def _stated(section: str, value: dict[str, Any]) -> bool:
    """Whether a section claims anything beyond its empty default."""
    empty = _EMPTY[section]
    return any(value.get(key) != empty[key] for key in empty if key != "quote")


def verify_quotes(extraction: dict[str, Any], transcript: str) -> tuple[dict[str, Any], int, int]:
    """Clear every item whose quote is not in the transcript.

    Returns ``(verified_extraction, verified_count, unverified_count)``. The
    counts cover items that claimed something; an empty section is neither.
    """
    haystack = _normalise(transcript)
    verified: dict[str, Any] = {}
    kept = dropped = 0
    for section, empty in _EMPTY.items():
        value = dict(empty) | {
            key: item for key, item in (extraction.get(section) or {}).items() if key in empty
        }
        if not _stated(section, value):
            verified[section] = dict(empty)
        elif quote_found(value.get("quote"), haystack):
            verified[section] = value
            kept += 1
        else:
            verified[section] = dict(empty)
            dropped += 1
    for section in ("tailwinds", "headwinds"):
        items = []
        for item in (extraction.get(section) or [])[:3]:
            if isinstance(item, dict) and item.get("what") and quote_found(item.get("quote"), haystack):
                items.append({"what": str(item["what"]), "quote": str(item["quote"])})
                kept += 1
            else:
                dropped += 1
        verified[section] = items
    return verified, kept, dropped


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def outlook_points(verified: dict[str, Any]) -> list[tuple[str, float]]:
    """The scored items of a verified extraction, as ``(reason, points)``."""
    points: list[tuple[str, float]] = []

    guidance = verified["guidance"]
    direction = guidance.get("direction")
    if direction == "raised":
        points.append(("guidance raised", 15.0))
    elif direction == "lowered":
        points.append(("guidance lowered", -20.0))
    elif direction == "maintained":
        points.append(("guidance maintained", 3.0))
    growth = _number(guidance.get("growth_pct"))
    if growth is not None and direction != "none":
        if growth >= 25:
            points.append(("guided revenue growth 25% or more", 10.0))
        elif growth >= 15:
            points.append(("guided revenue growth 15-25%", 6.0))
        elif growth >= 5:
            points.append(("guided revenue growth 5-15%", 2.0))
        elif growth < 0:
            points.append(("guided revenue decline", -10.0))

    order_book = verified["order_book"]
    if order_book.get("trend") == "up":
        points.append(("order book rising", 8.0))
    elif order_book.get("trend") == "down":
        points.append(("order book falling", -8.0))
    cover = _number(order_book.get("revenue_cover_years"))
    if cover is not None:
        if cover >= 2:
            points.append(("order book covers two years or more of revenue", 6.0))
        elif cover >= 1:
            points.append(("order book covers a year or more of revenue", 3.0))

    state = verified["capacity"].get("state")
    if state in ("operational", "ramping"):
        points.append(("new capacity producing", 6.0))
    elif state == "under_construction":
        points.append(("capacity under construction", 3.0))
    elif state == "planned":
        points.append(("capacity planned", 1.0))

    tone = verified["demand"].get("tone")
    if tone == "strong":
        points.append(("demand outlook strong", 8.0))
    elif tone == "weak":
        points.append(("demand outlook weak", -10.0))

    margin = verified["margin"].get("trend")
    if margin == "up":
        points.append(("margin outlook improving", 6.0))
    elif margin == "down":
        points.append(("margin outlook worsening", -8.0))

    for item in verified["tailwinds"]:
        points.append((f"tailwind: {item['what']}", 2.0))
    for item in verified["headwinds"]:
        points.append((f"headwind: {item['what']}", -3.0))
    return points


def outlook_score(verified: dict[str, Any]) -> float:
    """0-100, neutral at 50, from verified items only."""
    total = 50.0 + sum(value for _, value in outlook_points(verified))
    return round(min(100.0, max(0.0, total)), 2)


def parse_response(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(extraction, usage)`` from an OpenRouter chat-completion response."""
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError(f"no choices in response: {str(payload)[:300]}")
    content = (choices[0].get("message") or {}).get("content") or ""
    # A model that ignores response_format wraps the object in a code fence.
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("response carried no JSON object")
    extraction = json.loads(match.group(0))
    if not isinstance(extraction, dict):
        raise ValueError("response JSON is not an object")
    return extraction, payload.get("usage") or {}


def request_extraction(session, api_key: str, messages, *, model: str = DEFAULT_MODEL, timeout: int = 180):
    """One extraction call. Returns ``(extraction, usage)``; raises on failure."""
    response = session.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 2000,
            "usage": {"include": True},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "call_outlook", "strict": True, "schema": SCHEMA},
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_response(response.json())


def analyse_transcript(session, api_key: str, transcript: dict[str, Any], text: str, *, model: str = DEFAULT_MODEL):
    """Extract, verify and score one call. Returns the row to store."""
    messages = build_messages(
        transcript.get("company_name") or "",
        transcript.get("symbol") or "",
        str(transcript.get("call_date") or "")[:10],
        text,
    )
    extraction, usage = request_extraction(session, api_key, messages, model=model)
    verified, kept, dropped = verify_quotes(extraction, text)
    return {
        "transcript_id": transcript["id"],
        "market": transcript.get("market") or "NSE",
        "symbol": transcript.get("symbol"),
        "call_date": str(transcript.get("call_date") or "")[:10] or None,
        "model_name": model,
        "analysis_version": OUTLOOK_VERSION,
        "outlook_score": outlook_score(verified),
        "verified_fields": kept,
        "unverified_fields": dropped,
        "extraction": {
            **verified,
            "points": [{"reason": reason, "points": value} for reason, value in outlook_points(verified)],
        },
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "cost_usd": float(usage.get("cost") or 0.0),
    }
