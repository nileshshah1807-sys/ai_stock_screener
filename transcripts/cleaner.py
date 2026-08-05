"""Deterministic cleanup for text extracted from earnings-call PDFs."""

import re
from collections import Counter


_PAGE_NUMBER = re.compile(r"^(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?$", re.IGNORECASE)
_SAFE_HARBOR = re.compile(
    r"(?:safe harbor|forward-looking statements?|actual results? may differ)",
    re.IGNORECASE,
)


def clean_transcript_text(text: str) -> str:
    """Normalize extracted PDF text while retaining speaker and financial details."""
    if not text:
        return ""

    normalized_lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    candidate_lines = [
        line for line in normalized_lines
        if line and not _PAGE_NUMBER.fullmatch(line) and not _SAFE_HARBOR.search(line)
    ]

    repeated_short_lines = {
        line for line, count in Counter(candidate_lines).items()
        if count >= 3 and len(line) <= 120
    }
    cleaned_lines = [line for line in candidate_lines if line not in repeated_short_lines]
    return "\n".join(cleaned_lines).strip()