"""Conservative speaker and section detection for cleaned call transcripts."""

from dataclasses import dataclass
import re


_SPEAKER_LINE = re.compile(r"^(?P<speaker>[A-Za-z][A-Za-z .,'()&/-]{1,80})(?::|\s+-\s+)$")
_MANAGEMENT_TERMS = (
    "ceo", "cfo", "coo", "chief executive officer", "chief financial officer",
    "chief operating officer", "managing director", "director", "management", "promoter",
)
_ANALYST_TERMS = ("analyst", "research", "securities", "capital", "investments")
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
        match = _SPEAKER_LINE.fullmatch(line.strip())
        if match:
            emit()
            current_speaker = match.group("speaker").strip()
            current_role = _speaker_role(current_speaker)
        else:
            current_lines.append(line)
    emit()
    return segments