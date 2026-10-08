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
# The same model is sold by some thirty providers at prices a factor of ten
# apart, and OpenRouter's default routing does not pick the cheapest. Requests
# go to the cheapest provider first and never to one above these prices, USD
# per million tokens (prompt, completion).
MAX_PRICE_PER_MILLION = (0.10, 1.20)
MAX_OUTPUT_TOKENS = 3000

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

Answer with one JSON object and nothing else -- no explanation, no code fence. \
It has exactly these keys; where a set of values is listed, use one of them:
{
  "guidance": {"direction": "raised|maintained|lowered|none", "metric": string or null, \
"growth_pct": number or null, "quote": string or null},
  "order_book": {"value_inr_crore": number or null, "revenue_cover_years": number or null, \
"trend": "up|flat|down|unknown", "quote": string or null},
  "capacity": {"state": "operational|ramping|under_construction|planned|none", \
"commissioning": "YYYY-MM" or null, "quote": string or null},
  "demand": {"tone": "strong|stable|weak|unknown", "quote": string or null},
  "margin": {"trend": "up|flat|down|unknown", "quote": string or null},
  "tailwinds": [{"what": string, "quote": string}],
  "headwinds": [{"what": string, "quote": string}]
}"""


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


_DEMAND_ORDER = {"weak": -1, "stable": 0, "strong": 1}
_TREND_ORDER = {"down": -1, "flat": 0, "up": 1}
_CAPACITY_ORDER = {"planned": 1, "under_construction": 2, "ramping": 3, "operational": 4}
# Guided growth within a point of the last call's is the same guidance, and an
# order book within 5% the same book: both are restated loosely from memory.
GUIDANCE_TOLERANCE_PCT = 1.0
ORDER_BOOK_TOLERANCE = 0.05


def _percent(value: float) -> str:
    return f"{value:g}%"


def _ranked_change(item, label, order, previous, current):
    """A change in a field whose values have a natural order, or None."""
    before, after = order.get(previous), order.get(current)
    if before is None or after is None:
        return None
    if after == before:
        return {"item": item, "change": "kept", "text": f"{label} still {current}"}
    change = "better" if after > before else "worse"
    return {"item": item, "change": change, "text": f"{label} {previous} -> {current}"}


def compare_outlooks(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    """What a call changed from the company's previous one.

    Each entry is ``{"item", "change", "text"}`` with ``change`` one of
    ``better``, ``worse``, ``kept`` or ``not_restated``. An item is compared
    only where both calls stated it: silence in one of them is not a change.
    The one exception is guidance that was given and is not repeated, reported
    as ``not_restated`` -- worth a look, and not counted against the company,
    because it is as often the extraction missing a sentence as management
    dropping a number.

    Two limits. Guided growth is compared as stated, so across a financial
    year-end the two figures are for different years. And both sides are one
    reading of one call: a "change" can be the model picking a different
    project or segment the second time.
    """
    changes: list[dict[str, str]] = []

    before, after = previous.get("guidance") or {}, current.get("guidance") or {}
    was, now = before.get("direction") or "none", after.get("direction") or "none"
    old_growth, new_growth = _number(before.get("growth_pct")), _number(after.get("growth_pct"))
    if was != "none" and now == "none":
        changes.append({"item": "guidance", "change": "not_restated", "text": "guidance not restated"})
    elif was != "none" and old_growth is not None and new_growth is not None:
        move = new_growth - old_growth
        span = f"{_percent(old_growth)} -> {_percent(new_growth)}"
        if abs(move) < GUIDANCE_TOLERANCE_PCT:
            changes.append({
                "item": "guidance", "change": "kept",
                "text": f"guided growth held at {_percent(new_growth)}",
            })
        else:
            changes.append({
                "item": "guidance", "change": "better" if move > 0 else "worse",
                "text": f"guided growth {'raised' if move > 0 else 'cut'} {span}",
            })
    elif was != "none" and now == "raised":
        changes.append({"item": "guidance", "change": "better", "text": "guidance raised"})
    elif was != "none" and now == "lowered":
        changes.append({"item": "guidance", "change": "worse", "text": "guidance lowered"})
    elif was != "none" and now == "maintained":
        changes.append({"item": "guidance", "change": "kept", "text": "guidance maintained"})

    before, after = previous.get("order_book") or {}, current.get("order_book") or {}
    old_book, new_book = _number(before.get("value_inr_crore")), _number(after.get("value_inr_crore"))
    if old_book and new_book and old_book > 0:
        move = new_book / old_book - 1.0
        span = f"{old_book:,.0f} -> {new_book:,.0f} crore"
        if abs(move) < ORDER_BOOK_TOLERANCE:
            changes.append({"item": "order_book", "change": "kept", "text": f"order book steady, {span}"})
        else:
            changes.append({
                "item": "order_book", "change": "better" if move > 0 else "worse",
                "text": f"order book {'up' if move > 0 else 'down'} {abs(move) * 100:.0f}%, {span}",
            })

    before, after = previous.get("capacity") or {}, current.get("capacity") or {}
    old_stage = _CAPACITY_ORDER.get(before.get("state"))
    new_stage = _CAPACITY_ORDER.get(after.get("state"))
    old_date, new_date = str(before.get("commissioning") or ""), str(after.get("commissioning") or "")
    dated = bool(re.fullmatch(r"\d{4}-\d{2}", old_date) and re.fullmatch(r"\d{4}-\d{2}", new_date))
    if dated and new_date != old_date:
        # YYYY-MM sorts as text.
        changes.append({
            "item": "capacity", "change": "worse" if new_date > old_date else "better",
            "text": f"commissioning {'slipped' if new_date > old_date else 'pulled forward'} "
                    f"{old_date} -> {new_date}",
        })
    elif old_stage and new_stage and new_stage > old_stage:
        changes.append({
            "item": "capacity", "change": "better",
            "text": f"capacity progressed {before['state']} -> {after['state']}".replace("_", " "),
        })
    elif dated:
        changes.append({"item": "capacity", "change": "kept", "text": f"commissioning date held at {new_date}"})
    # A later call at an earlier stage is a different project, not a retreat.

    demand = _ranked_change(
        "demand", "demand outlook", _DEMAND_ORDER,
        (previous.get("demand") or {}).get("tone"), (current.get("demand") or {}).get("tone"),
    )
    margin = _ranked_change(
        "margin", "margin outlook", _TREND_ORDER,
        (previous.get("margin") or {}).get("trend"), (current.get("margin") or {}).get("trend"),
    )
    changes.extend(change for change in (demand, margin) if change)
    return changes


def summarise_changes(changes: list[dict[str, str]]) -> str:
    """The changes that moved, worst first; what was kept is counted, not listed."""
    order = {"worse": 0, "better": 1, "not_restated": 2}
    moved = sorted(
        (change for change in changes if change["change"] in order),
        key=lambda change: order[change["change"]],
    )
    kept = sum(1 for change in changes if change["change"] == "kept")
    parts = [change["text"] for change in moved]
    if kept:
        parts.append(f"{kept} item{'s' if kept != 1 else ''} unchanged")
    return "; ".join(parts)


class ExtractionError(ValueError):
    """A reply that could not be used. It was still paid for: ``cost_usd``."""

    def __init__(self, message: str, cost_usd: float = 0.0):
        super().__init__(message)
        self.cost_usd = float(cost_usd or 0.0)


def parse_response(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(extraction, usage)`` from an OpenRouter chat-completion response."""
    usage = payload.get("usage") or {}
    cost = float(usage.get("cost") or 0.0)
    choices = payload.get("choices") or []
    if not choices:
        raise ExtractionError(f"no choices in response: {str(payload)[:300]}", cost)
    content = (choices[0].get("message") or {}).get("content") or ""
    if choices[0].get("finish_reason") == "length":
        # Cut off mid-object, or the tokens went on reasoning before any answer.
        raise ExtractionError("reply hit the output limit before the JSON was complete", cost)
    # A model that ignores response_format wraps the object in a code fence.
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ExtractionError("response carried no JSON object", cost)
    try:
        extraction = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"response JSON did not parse: {exc}", cost) from exc
    if not isinstance(extraction, dict):
        raise ExtractionError("response JSON is not an object", cost)
    return extraction, usage


def request_extraction(session, api_key: str, messages, *, model: str = DEFAULT_MODEL, timeout: int = 180):
    """One extraction call. Returns ``(extraction, usage)``; raises on failure."""
    response = session.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "usage": {"include": True},
            # Extraction, not problem solving: left on, the model spends the
            # whole reply thinking and never reaches the object.
            "reasoning": {"enabled": False},
            "provider": {
                "sort": "price",
                "max_price": {
                    "prompt": MAX_PRICE_PER_MILLION[0],
                    "completion": MAX_PRICE_PER_MILLION[1],
                },
            },
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
