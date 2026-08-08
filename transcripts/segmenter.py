"""Conservative speaker and section detection for cleaned call transcripts."""

from dataclasses import dataclass
import re


_SPEAKER_LINE = re.compile(r"^(?P<speaker>[A-Za-z][A-Za-z .,'()&/-]{1,120})(?::|\s+-\s+)$")
_SPEAKER_WITH_TITLE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z .,'()&/]{1,80})\s+-\s+"
    r"(?P<title>[A-Za-z][A-Za-z .,'()&/-]{2,140})$"
)
_MANAGEMENT_TERMS = (
    "ceo", "cfo", "coo", "chief executive officer", "chief financial officer",
    "chief operating officer", "managing director", "director", "management", "promoter",
    "investor relations", "whole time", "president", "vice president",
)
_ANALYST_TERMS = (
    "analyst", "research", "securities", "capital", "investments", "investor",
)
_OPERATOR_TERMS = ("operator", "moderator", "coordinator", "host")


@dataclass(frozen=True)
class TranscriptSegment:
    speaker: str
    role: str
    section: str
    text: str


def _speaker_role(speaker: str) -> str:
    value = speaker.lower()
    if any(term in value for term in _OPERATOR_TERMS):
        return "operator"
    if any(term in value for term in _MANAGEMENT_TERMS):
        return "management"
    if any(term in value for term in _ANALYST_TERMS):
        return "analyst"
    return "unknown"


def _speaker_from_line(line: str) -> tuple[str, str] | None:
    value = line.strip()
    if value.lower() in _OPERATOR_TERMS:
        return value, "operator"

    match = _SPEAKER_LINE.fullmatch(value)
    if match:
        speaker = match.group("speaker").strip()
        return speaker, _speaker_role(speaker)

    # AlphaStreet/StockScans transcripts use "Name - Job Title" headings.
    # Only accept the pattern when the title identifies a participant role so
    # ordinary prose containing a dash is not mistaken for a speaker change.
    match = _SPEAKER_WITH_TITLE.fullmatch(value)
    if match:
        title = match.group("title").strip()
        role = _speaker_role(title)
        if role != "unknown":
            return value, role
    return None


def is_speaker_line(line: str) -> bool:
    return _speaker_from_line(line) is not None


def segment_transcript(text: str) -> list[TranscriptSegment]:
    """Group lines under explicit speaker labels without guessing unnamed speakers."""
    segments: list[TranscriptSegment] = []
    current_speaker = "Unknown"
    current_role = "unknown"
    current_lines: list[str] = []
    seen_analyst = False

    def emit() -> None:
        nonlocal current_lines, seen_analyst
        body = "\n".join(current_lines).strip()
        if not body:
            return
        if current_role == "analyst":
            section = "analyst_question"
            seen_analyst = True
        elif current_role == "management":
            section = "management_answer" if seen_analyst else "prepared_remarks"
        elif current_role == "operator" and seen_analyst:
            section = "closing"
        else:
            section = "prepared_remarks"
        segments.append(TranscriptSegment(current_speaker, current_role, section, body))
        current_lines = []

    for line in text.splitlines():
        speaker = _speaker_from_line(line)
        if speaker:
            emit()
            current_speaker, current_role = speaker
        else:
            current_lines.append(line)
    emit()
    return segments
