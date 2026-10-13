"""Earnings-call recordings filed with NSE: finding, fetching and cutting them.

A company files the transcript of its call days after it is held, but a "link
of recording" notice the same evening. This module is what lets the call be
read that evening: it recognises the notice, finds the audio file the notice
points at, and cuts the recording at pauses so that each piece can be
transcribed on a machine of its own (`workers/call_recordings.py`).

A notice that names an audio file is served from here. One that points at an
investor page, a shared drive or a video, or at nothing, is resolved by
`transcripts/recording_sources.py`, which would rather find nothing than the
wrong quarter's call.
"""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests

from transcripts.collector import is_earnings_transcript

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SAMPLE_RATE = 16_000
MAX_AUDIO_BYTES = 250 * 1024 * 1024
# Smaller than this is an error page or a jingle, not a call.
MIN_AUDIO_BYTES = 100_000

#: How a transcript made from a recording is told from a filed one: the prefix
#: of its document's ``extraction_method``, followed by the model's name.
SPEECH_METHOD_PREFIX = "speech:"

_CALL_CATEGORY = "con. call"
_RECORDING_WORDS = re.compile(r"\b(?:audio|recording|webcast)\b", re.IGNORECASE)
_SCHEDULE_WORDS = re.compile(r"schedule of meet", re.IGNORECASE)
# Not anchored: a link that wraps across lines in the notice is rejoined with
# whatever text followed it ("...call.mp3Thanking you"), and is cut back to the
# extension. Only the extension ignores case: a capital after it starts the
# next sentence, while a lower-case letter or a digit is more of the name.
_AUDIO_PATH = re.compile(r"(?i:\.(?:mp3|m4a|wav|aac|ogg|wma|mp4))(?![a-z0-9])")
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")
_EXCHANGE_HOSTS = ("nseindia.com", "bseindia.com")
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

# What a notice's link lets an unattended job do, best first.
DIRECT = "direct audio file"
EMBEDDED = "audio file named in a player link"
VIDEO = "video platform"
PAGE = "web page"
NONE = "no link"
_ORDER = (DIRECT, EMBEDDED, VIDEO, PAGE, NONE)
DOWNLOADABLE = frozenset({DIRECT, EMBEDDED})


def is_recording_notice(record: dict[str, Any]) -> bool:
    """A notice that a call's recording is available.

    A notice that also mentions the transcript belongs to the transcript
    collector, which reads the same announcements: one filing has one owner.
    """
    text = _notice_text(record)
    return (
        _CALL_CATEGORY in text
        and bool(_RECORDING_WORDS.search(text))
        and not _SCHEDULE_WORDS.search(text)
        and not is_earnings_transcript(record)
    )


def _notice_text(record: dict[str, Any]) -> str:
    return " ".join(str(record.get(key) or "") for key in ("desc", "attchmntText")).lower()


def classify_links(links: list[str]) -> tuple[str, str | None]:
    """The most usable link among those a notice carries, and what kind it is."""
    best: tuple[str, str | None] = (NONE, None)
    for link in links:
        candidate = _classify(link)
        if _ORDER.index(candidate[0]) < _ORDER.index(best[0]):
            best = candidate
    return best


def _classify(link: str) -> tuple[str, str | None]:
    link = link.rstrip(".,;")
    parts = urlsplit(link)
    host = parts.netloc.lower()
    if not host or any(host.endswith(exchange) for exchange in _EXCHANGE_HOSTS):
        return NONE, None
    audio = _AUDIO_PATH.search(parts.path)
    if audio:
        whole = audio.end() == len(parts.path)
        return DIRECT, link if whole else f"{parts.scheme}://{parts.netloc}{parts.path[: audio.end()]}"
    for _, value in parse_qsl(parts.query):
        audio = _AUDIO_PATH.search(urlsplit(value).path)
        if audio:
            return EMBEDDED, urljoin(link, value[: value.index(audio.group()) + len(audio.group())])
    if any(host.endswith(video) for video in _VIDEO_HOSTS):
        return VIDEO, link
    return PAGE, link


def pdf_links(path: Path) -> list[str]:
    """Every link in a notice: its annotations, and addresses printed in its text."""
    import pymupdf

    document = pymupdf.open(path)
    try:
        links: list[str] = []
        for page in document:
            links.extend(link["uri"] for link in page.get_links() if link.get("uri"))
            text = page.get_text("text")
            links.extend(_URL.findall(text))
            links.extend(_URL.findall(text.replace("\n", "")))
        return links
    finally:
        document.close()


def download_notice(attachment_url: str, folder: Path) -> Path:
    from nse import NSE

    with NSE(download_folder=folder, server=False, timeout=60) as nse:
        path = Path(nse.download_document(attachment_url))
    if not path.is_file() or path.read_bytes()[:5] != b"%PDF-":
        raise ValueError("NSE attachment is not a valid PDF")
    return path


def download_audio(url: str, folder: Path, name: str) -> Path | None:
    """The recording saved under ``folder``, or None when the site did not serve one."""
    parts = urlsplit(url)
    # Some investor sites serve the file only to a request that names their own page.
    headers = {"User-Agent": USER_AGENT, "Referer": f"{parts.scheme}://{parts.netloc}/"}
    path = folder / f"{name}{Path(parts.path).suffix.lower() or '.mp3'}"
    try:
        with requests.get(url, headers=headers, timeout=120, stream=True) as response:
            response.raise_for_status()
            if "html" in response.headers.get("Content-Type", "").lower():
                return None
            size = 0
            with path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        break
                    handle.write(chunk)
    except requests.RequestException as exc:
        logger.warning("Recording download failed: %s", exc)
        path.unlink(missing_ok=True)
        return None
    if not MIN_AUDIO_BYTES <= size <= MAX_AUDIO_BYTES:
        path.unlink(missing_ok=True)
        return None
    return path


def ffmpeg_executable() -> str:
    """The ffmpeg to decode with: the system's, else the one `imageio-ffmpeg` ships.

    The packaged binary is what the workflow relies on. Installing ffmpeg with
    apt hung a runner for an hour in the benchmark this design came from.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def decode_audio(path: Path, start: float | None = None, end: float | None = None):
    """The recording, or one piece of it, as 16 kHz mono float samples."""
    import numpy as np

    command = [ffmpeg_executable(), "-nostdin", "-loglevel", "error", "-i", str(path)]
    if start:
        command += ["-ss", f"{start:.3f}"]
    if end is not None:
        command += ["-t", f"{end - (start or 0.0):.3f}"]
    command += ["-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    raw = subprocess.run(command, check=True, capture_output=True, timeout=600).stdout
    return np.frombuffer(raw, dtype=np.float32)


def piece_count(seconds: float, piece_seconds: float, max_parts: int) -> int:
    """Pieces to cut a recording into: about ``piece_seconds`` each, never more than ``max_parts``."""
    return max(1, min(int(max_parts), math.ceil(seconds / max(1.0, piece_seconds))))


def cut_points(samples, parts: int, search_seconds: float = 20.0, window_seconds: float = 0.5) -> list[float]:
    """Where to cut a recording into ``parts`` pieces, in seconds, ends included.

    An even cut lands mid-word as often as not, and both pieces then guess at
    the half they got. Each cut moves to the quietest half second within
    ``search_seconds`` of its even position, which on a call is a pause
    between speakers.
    """
    import numpy as np

    total = len(samples)
    window = max(1, int(window_seconds * SAMPLE_RATE))
    reach = int(search_seconds * SAMPLE_RATE)
    points = [0.0]
    for part in range(1, max(1, parts)):
        target = total * part // parts
        low = max(0, target - reach)
        loudness = np.abs(samples[low : min(total, target + reach)])
        windows = len(loudness) // window
        if not windows:
            points.append(target / SAMPLE_RATE)
            continue
        quietest = int(loudness[: windows * window].reshape(windows, window).mean(axis=1).argmin())
        points.append((low + quietest * window + window // 2) / SAMPLE_RATE)
    points.append(total / SAMPLE_RATE)
    return points


def stitch(pieces: list[str]) -> str:
    """The call's text from its pieces, in order, one spoken passage per line."""
    return "\n".join(piece.strip() for piece in pieces if piece and piece.strip())
