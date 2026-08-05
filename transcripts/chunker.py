"""Chunk transcript segments into bounded LLM analysis requests."""

from dataclasses import dataclass

from .segmenter import TranscriptSegment


@dataclass(frozen=True)
class TranscriptChunk:
    index: int
    text: str
    estimated_tokens: int


def estimate_tokens(text: str) -> int:
    """Use a conservative approximation when a model tokenizer is unavailable."""
    return max(1, (len(text) + 3) // 4) if text else 0


def build_chunks(
    segments: list[TranscriptSegment],
    target_tokens: int = 4000,
    overlap_tokens: int = 150,
) -> list[TranscriptChunk]:
    """Build chunks that never exceed the requested estimated-token budget."""
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens cannot be negative")

    chunks: list[TranscriptChunk] = []
    current_units: list[str] = []
    current_tokens = 0

    def emit() -> None:
        nonlocal current_units, current_tokens
        if not current_units:
            return
        text = "\n\n".join(current_units)
        chunks.append(TranscriptChunk(len(chunks), text, estimate_tokens(text)))
        current_units = []
        current_tokens = 0

    for segment in segments:
        units = _bounded_segment_units(segment, target_tokens)
        for unit in units:
            unit_tokens = estimate_tokens(unit)
            separator_tokens = 1 if current_units else 0
            if current_units and current_tokens + separator_tokens + unit_tokens > target_tokens:
                previous_unit = current_units[-1]
                emit()
                previous_tokens = estimate_tokens(previous_unit)
                if previous_tokens <= overlap_tokens:
                    current_units.append(previous_unit)
                    current_tokens = previous_tokens
            separator_tokens = 1 if current_units else 0
            if current_units and current_tokens + separator_tokens + unit_tokens > target_tokens:
                emit()
            current_units.append(unit)
            current_tokens += separator_tokens + unit_tokens
    emit()
    return chunks


def _bounded_segment_units(segment: TranscriptSegment, target_tokens: int) -> list[str]:
    prefix = f"[{segment.section}] {segment.speaker}:\n"
    available_text_tokens = max(1, target_tokens - estimate_tokens(prefix))
    text_parts = _split_text(segment.text, available_text_tokens)
    return [f"{prefix}{text_part}" for text_part in text_parts]


def _split_text(text: str, max_tokens: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    parts: list[str] = []
    current_words: list[str] = []
    for word in words:
        candidate_words = current_words + [word]
        candidate = " ".join(candidate_words)
        if current_words and estimate_tokens(candidate) > max_tokens:
            parts.append(" ".join(current_words))
            current_words = [word]
        else:
            current_words = candidate_words
    if current_words:
        parts.append(" ".join(current_words))
    return parts