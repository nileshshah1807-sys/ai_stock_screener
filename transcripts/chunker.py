"""Chunk transcript segments at speaker boundaries for LLM analysis."""

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
    """Build chunks without splitting an individual speaker block."""
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens cannot be negative")

    chunks: list[TranscriptChunk] = []
    current_segments: list[TranscriptSegment] = []
    current_tokens = 0

    def emit() -> None:
        nonlocal current_segments, current_tokens
        if not current_segments:
            return
        text = "\n\n".join(
            f"[{segment.section}] {segment.speaker}:\n{segment.text}"
            for segment in current_segments
        )
        chunks.append(TranscriptChunk(len(chunks), text, estimate_tokens(text)))
        current_segments = []
        current_tokens = 0

    for segment in segments:
        segment_tokens = estimate_tokens(segment.text)
        if current_segments and current_tokens + segment_tokens > target_tokens:
            previous_segment = current_segments[-1]
            emit()
            if estimate_tokens(previous_segment.text) <= overlap_tokens:
                current_segments.append(previous_segment)
                current_tokens = estimate_tokens(previous_segment.text)
        current_segments.append(segment)
        current_tokens += segment_tokens
    emit()
    return chunks