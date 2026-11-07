"""Listen to a call as it is held and append its text, a few seconds behind.

Prototype (branch ``test/live-concalls``). Given an audio source -- a webcast
or HLS address, or a file -- ``ffmpeg`` decodes it to 16 kHz mono, the stream
is cut every ``--chunk-seconds`` and each chunk is transcribed with
``faster-whisper`` (``requirements-speech.txt``). Every passage becomes a row
of ``live_call_lines`` and the call's row in ``live_calls`` is ``live`` until
the audio ends. Tables: ``storage/live_calls_schema.sql``, applied by hand to
a preview project, never to production.

``--replay`` plays a stored recording at real-time speed (``ffmpeg -re``), so a
demo needs no live call. A live webcast already arrives at call speed.

Runs on a laptop; nothing here is scheduled and nothing relays audio to a viewer.
The text is display evidence: no score reads it.

    python -m workers.live_calls --symbol BLUSPRING --source call.mp3 --replay --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any

from transcripts.recordings import SAMPLE_RATE, ffmpeg_executable
from transcripts.speech import DEFAULT_MODEL

logger = logging.getLogger(__name__)

CHUNK_SECONDS = 8.0
# A tail this short is dropped: Whisper mishears a clipped fragment.
MIN_CHUNK_SECONDS = 1.0
_BYTES_PER_SECOND = SAMPLE_RATE * 4  # float32 mono

Transcribe = Callable[[Any], list[tuple[float, str]]]


def call_id(market: str, symbol: str, day: date) -> str:
    return f"{market}:{symbol.upper()}:{day.isoformat()}"


def read_exactly(stream: Any, size: int) -> bytes:
    """``size`` bytes, or fewer only at the end of the stream (a pipe may return short reads)."""
    parts: list[bytes] = []
    got = 0
    while got < size:
        part = stream.read(size - got)
        if not part:
            break
        parts.append(part)
        got += len(part)
    return b"".join(parts)


def pcm_chunks(source: str, *, replay: bool = False, chunk_seconds: float = CHUNK_SECONDS) -> Iterator[tuple[float, Any]]:
    """``(start_seconds, samples)`` for each chunk of the source, as it arrives."""
    import numpy as np

    command = [ffmpeg_executable(), "-nostdin", "-loglevel", "error"]
    if replay:
        command += ["-re"]
    command += ["-i", source, "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    size = int(chunk_seconds * _BYTES_PER_SECOND)
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        start = 0.0
        while True:
            raw = read_exactly(process.stdout, size)
            if len(raw) < _BYTES_PER_SECOND * MIN_CHUNK_SECONDS:
                return
            samples = np.frombuffer(raw[: len(raw) - len(raw) % 4], dtype=np.float32)
            yield start, samples
            start += len(samples) / SAMPLE_RATE


def whisper_transcriber(model_name: str = DEFAULT_MODEL, threads: int | None = None) -> Transcribe:
    """One model, loaded once, that turns a chunk into ``(offset_seconds, text)`` passages."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads or os.cpu_count() or 4)

    def transcribe(samples: Any) -> list[tuple[float, str]]:
        segments, _ = model.transcribe(samples, vad_filter=True, beam_size=1, condition_on_previous_text=False)
        return [(float(s.start), s.text.strip()) for s in segments if s.text.strip()]

    return transcribe


def listen(
    repo: Any,
    *,
    call: str,
    symbol: str,
    source: str,
    chunks: Iterable[tuple[float, Any]],
    transcribe: Transcribe,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Mark the call live, append a line per passage, mark it ended. Returns the lines written."""
    repo.upsert_live_call(
        {"call_id": call, "symbol": symbol.upper(), "state": "live", "started_at": now().isoformat(), "source_url": source}
    )
    seq = 0
    try:
        for start, samples in chunks:
            rows = []
            for offset, text in transcribe(samples):
                seq += 1
                rows.append({"call_id": call, "seq": seq, "start_seconds": round(start + offset, 2), "text": text})
            if rows:
                repo.append_live_lines(rows)
                logger.info("%s: %s lines to %.0fs", call, len(rows), start)
    finally:
        # also on an error or ^C: a call left 'live' forever would read as still on
        repo.upsert_live_call({"call_id": call, "symbol": symbol.upper(), "state": "ended", "ended_at": now().isoformat()})
    return seq


class PrintRepo:
    """``--dry-run``: show what would be written."""

    def upsert_live_call(self, row: dict[str, Any]) -> None:
        print("call", {k: v for k, v in row.items() if k != "source_url"})

    def append_live_lines(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            print(f"[{row['start_seconds']:7.1f}s] {row['text']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", required=True, help="webcast / HLS address, or a file")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", default=os.getenv("MARKET", "NSE"))
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date())
    parser.add_argument("--replay", action="store_true", help="play a stored recording at real-time speed")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--chunk-seconds", type=float, default=CHUNK_SECONDS)
    parser.add_argument("--dry-run", action="store_true", help="print the lines instead of writing them")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.dry_run:
        repo: Any = PrintRepo()
    else:
        from storage.dashboard_repository import DashboardRepository

        repo = DashboardRepository.from_environment(args.market)
    lines = listen(
        repo,
        call=call_id(args.market, args.symbol, args.date),
        symbol=args.symbol,
        source=args.source,
        chunks=pcm_chunks(args.source, replay=args.replay, chunk_seconds=args.chunk_seconds),
        transcribe=whisper_transcriber(args.model),
    )
    logger.info("%s lines written", lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
