"""Speech to text for a call recording, with an open-source model on CPU.

`faster-whisper` is outside the production locks: only the transcription jobs
of the call-recordings workflow install it (`requirements-speech.txt`), and
nothing else imports this module's model.

Measured on a four-core hosted runner (12 Oct 2026): `large-v3-turbo` runs at
about 2.8x real time and `small` at about 8x. The larger model is the default
because the smaller one misheard names and figures in the same passages.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from transcripts.recordings import decode_audio

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "large-v3-turbo"


def transcribe(
    path: Path,
    start: float | None = None,
    end: float | None = None,
    *,
    model_name: str = DEFAULT_MODEL,
    threads: int | None = None,
) -> dict[str, Any]:
    """Transcribe a recording, or the piece of it between ``start`` and ``end``.

    Each passage the model emits becomes a line. A recording has no speaker
    labels, so the text carries none: the tone score reads it as one voice.
    """
    from faster_whisper import WhisperModel

    samples = decode_audio(path, start, end)
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads or os.cpu_count() or 4)
    started_at = time.monotonic()
    # No conditioning on earlier text: on a long recording one misheard passage
    # otherwise repeats itself through everything after it.
    segments, info = model.transcribe(samples, vad_filter=True, beam_size=1, condition_on_previous_text=False)
    lines = [segment.text.strip() for segment in segments]
    seconds = time.monotonic() - started_at
    return {
        "text": "\n".join(line for line in lines if line),
        "model": model_name,
        "language": info.language,
        "audio_seconds": round(float(info.duration), 1),
        "seconds": round(seconds, 1),
    }
