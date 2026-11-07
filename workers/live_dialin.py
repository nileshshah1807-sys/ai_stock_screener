"""Dial into a call by phone, say who we are, and transcribe what follows. DESIGN, NOT RUN.

Most NSE earnings calls are dial-in only. A caller who has not pre-registered
(Chorus Call's DiamondPass) reaches an operator, who asks for a name and
company and connects them. This worker is that caller, and it says what it is:
``identity.wav`` is a short recorded clip ("Chirayu Shah, Cupel"), played once
the operator is on, and only once. The job never answers a further question.
If the conference has not started within ``JOIN_DEADLINE_SECONDS`` of the
recording's start, it hangs up, logs why and leaves the call to the evening
recording; it does not retry in the same call. It does not pretend to be a
person and it never touches a CAPTCHA.

Pieces:
* ``pjsua`` (PJSIP's command-line client) dials ``--uri`` through the SIP
  account in ``SIP_USER`` / ``SIP_PASSWORD`` / ``SIP_HOST`` (opened by the human;
  never created by this code) and records the call to a WAV file.
* ``tail_chunks`` reads that growing file and cuts it into the same
  ``(start_seconds, samples)`` chunks ``workers.live_calls.listen`` takes, so the
  transcriber and the ``live_call_lines`` tables are shared with the webcast path.

Open design points:
* The conference has started when a transcribed passage has a moderator's
  opening in it (``JOINED``); a crude test, to be replaced by what the first real
  call sounds like.
* When to play the clip. ``pjsua --play-file`` starts at once, over the
  conference greeting. Pad the clip with silence as a stopgap; the proper fix
  is PJSUA2 (``AudioMediaPlayer.startTransmit``) triggered when the operator's
  speech ends.
* Whether a GitHub runner's NAT passes SIP/RTP. Untested.

    python -m workers.live_dialin --uri sip:18667462133@sip.example.net --symbol ABC --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from workers.live_calls import CHUNK_SECONDS, PrintRepo, call_id, listen, whisper_transcriber

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
WAV_HEADER_BYTES = 44
_BYTES_PER_SECOND = SAMPLE_RATE * 2  # 16-bit mono
#: How long the recording may stay unchanged before the call is taken as over.
IDLE_SECONDS = 20.0
#: Hang up if the conference has not started this far into the recording.
JOIN_DEADLINE_SECONDS = 90.0
JOINED = re.compile(r"ladies and gentlemen|welcome to|good (?:morning|afternoon|evening)", re.IGNORECASE)


class Join:
    """Has the conference started, and if the job gave up, why."""

    def __init__(self) -> None:
        self.joined = False
        self.gave_up: str | None = None


def watch_transcribe(transcribe: Callable[[Any], list[tuple[float, str]]], join: Join):
    def watching(samples: Any) -> list[tuple[float, str]]:
        passages = transcribe(samples)
        if any(JOINED.search(text) for _, text in passages):
            join.joined = True
        return passages

    return watching


def until_joined(chunks: Iterator[tuple[float, Any]], join: Join, deadline: float = JOIN_DEADLINE_SECONDS):
    """The chunks, ending the call (no retry) if the conference has not started by ``deadline``."""
    for start, samples in chunks:
        if not join.joined and start >= deadline:
            join.gave_up = f"conference audio had not started {deadline:.0f} s into the call"
            logger.warning("Hanging up: %s; the evening recording will be used", join.gave_up)
            return
        yield start, samples


def pjsua_command(uri: str, *, identity_clip: Path, record_to: Path) -> list[str]:
    """The pjsua call: register, dial ``uri``, play the identity clip once, record the far end."""
    return [
        "pjsua", "--null-audio", "--clock-rate", str(SAMPLE_RATE), "--snd-clock-rate", str(SAMPLE_RATE),
        "--id", f"sip:{os.environ['SIP_USER']}@{os.environ['SIP_HOST']}",
        "--registrar", f"sip:{os.environ['SIP_HOST']}",
        "--realm", "*", "--username", os.environ["SIP_USER"], "--password", os.environ["SIP_PASSWORD"],
        "--play-file", str(identity_clip), "--auto-play", "--auto-rec", "--rec-file", str(record_to),
        uri,
    ]


def tail_chunks(
    path: Path,
    *,
    chunk_seconds: float = CHUNK_SECONDS,
    idle_seconds: float = IDLE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[tuple[float, Any]]:
    """Chunks of a WAV file that is still being written; ends when it stops growing.

    pjsua writes the WAV header when it closes the file, so the data is read as
    raw 16-bit samples after the 44-byte header.
    """
    import numpy as np

    size = int(chunk_seconds * _BYTES_PER_SECOND)
    position, start, last_growth = WAV_HEADER_BYTES, 0.0, clock()
    while True:
        available = path.stat().st_size - position if path.exists() else 0
        if available >= size:
            with path.open("rb") as handle:
                handle.seek(position)
                raw = handle.read(size)
            position += len(raw)
            last_growth = clock()
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            yield start, samples
            start += len(samples) / SAMPLE_RATE
        elif clock() - last_growth > idle_seconds:
            return
        else:
            sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--uri", required=True, help="sip: address of the number to dial")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", default=os.getenv("MARKET", "NSE"))
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date())
    parser.add_argument("--identity-clip", type=Path, default=Path("identity.wav"))
    parser.add_argument("--record-to", type=Path, default=Path("call.wav"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.dry_run:
        repo: Any = PrintRepo()
    else:
        from storage.dashboard_repository import DashboardRepository

        repo = DashboardRepository.from_environment(args.market)
    args.record_to.unlink(missing_ok=True)
    phone = subprocess.Popen(pjsua_command(args.uri, identity_clip=args.identity_clip, record_to=args.record_to))
    join = Join()
    try:
        listen(
            repo,
            call=call_id(args.market, args.symbol, args.date),
            symbol=args.symbol,
            source="dial-in",  # not a URL: the number is not stored with the call
            chunks=until_joined(tail_chunks(args.record_to), join),
            transcribe=watch_transcribe(whisper_transcriber(), join),
        )
    finally:
        phone.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
