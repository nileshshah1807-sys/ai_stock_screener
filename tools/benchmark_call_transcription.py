"""Measure whether earnings-call recordings can be transcribed on a CI runner.

A company files a transcript days after its call, but a "link of recording"
notice the same evening. Before the transcript worker reads those notices,
this measures the two things that decide whether it can:

* **reach** -- of the recording notices in a window, how many carry a link an
  unattended job can download, as opposed to a web page or no link at all;
* **speed** -- how long an open-source speech-to-text model takes on the
  recording, on the cores the job is given.

Usage::

    python -m tools.benchmark_call_transcription --days 14
    python -m tools.benchmark_call_transcription --days 14 --transcribe 2 --models small large-v3-turbo
    python -m tools.benchmark_call_transcription --url https://example.com/call.mp3 --transcribe 1
    python -m tools.benchmark_call_transcription --days 14 --transcribe 2 --plan 4
    python -m tools.benchmark_call_transcription --url https://example.com/call.mp3 --start 0 --end 780.5

``--plan`` cuts each recording into that many pieces at a quiet moment and
prints them as a job matrix; ``--start``/``--end`` transcribe one piece. One
runner per piece is how a call is finished in a fraction of its own length.

``--transcribe`` needs ``faster-whisper``, which is not in the locks: the
benchmark workflow installs it for the run. Under GitHub Actions the report is
also written to the job summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MAX_AUDIO_BYTES = 250 * 1024 * 1024
SAMPLE_CHARACTERS = 700
SAMPLE_RATE = 16_000

_CALL_CATEGORY = "con. call"
_RECORDING_WORDS = re.compile(r"\b(?:audio|recording|webcast)\b", re.IGNORECASE)
_SCHEDULE_WORDS = re.compile(r"schedule of meet", re.IGNORECASE)
# Not anchored: a link that wraps across lines in the notice is rejoined with
# whatever text followed it, and is cut back to the extension.
_AUDIO_PATH = re.compile(r"\.(?:mp3|m4a|wav|aac|ogg|wma|mp4)(?![a-z0-9])", re.IGNORECASE)
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


@dataclass(frozen=True)
class RecordingNotice:
    symbol: str
    filed_at: str
    kind: str
    url: str | None


def is_recording_notice(record: dict) -> bool:
    text = _notice_text(record)
    return _CALL_CATEGORY in text and bool(_RECORDING_WORDS.search(text)) and not _SCHEDULE_WORDS.search(text)


def is_schedule_notice(record: dict) -> bool:
    text = _notice_text(record)
    return _CALL_CATEGORY in text and bool(_SCHEDULE_WORDS.search(text))


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


def _notice_text(record: dict) -> str:
    return " ".join(str(record.get(key) or "") for key in ("desc", "attchmntText")).lower()


def _pdf_links(path: Path) -> list[str]:
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


def discover(days: int, attempts: int = 3) -> tuple[list[RecordingNotice], int]:
    """Recording notices in the window, classified, and the count of call schedules.

    NSE turns away a share of first requests from a hosted runner, so the read
    is retried the way the transcript collector retries its own.
    """
    for attempt in range(1, attempts + 1):
        try:
            return _discover_once(days)
        except Exception as exc:
            if attempt == attempts:
                raise
            print(f"  discovery attempt {attempt}/{attempts} failed: {exc}", file=sys.stderr)
            time.sleep(10 * attempt)
    raise AssertionError("unreachable")


def _discover_once(days: int) -> tuple[list[RecordingNotice], int]:
    from nse import NSE

    end = datetime.now()
    start = end - timedelta(days=max(1, days))
    notices: list[RecordingNotice] = []
    with (
        TemporaryDirectory(prefix="call_recordings_") as folder,
        NSE(download_folder=folder, timeout=60, server=False) as nse,
    ):
        records = nse.announcements(index="equities", from_date=start, to_date=end)
        schedules = sum(1 for record in records if is_schedule_notice(record))
        for record in records:
            if not is_recording_notice(record):
                continue
            kind, url = NONE, None
            try:
                kind, url = classify_links(_pdf_links(Path(nse.download_document(record["attchmntFile"]))))
            except Exception as exc:  # one unreadable notice must not end the measurement
                print(f"  could not read the notice for {record.get('symbol')}: {exc}", file=sys.stderr)
            notices.append(RecordingNotice(str(record.get("symbol")), str(record.get("an_dt")), kind, url))
            time.sleep(0.3)
    return notices, schedules


def download_audio(url: str, folder: Path, index: int) -> Path | None:
    try:
        parts = urlsplit(url)
        # Some investor sites serve the file only to a request that names their own page.
        headers = {"User-Agent": USER_AGENT, "Referer": f"{parts.scheme}://{parts.netloc}/"}
        with requests.get(url, headers=headers, timeout=120, stream=True) as response:
            response.raise_for_status()
            if "html" in response.headers.get("Content-Type", "").lower():
                return None
            suffix = Path(urlsplit(url).path).suffix or ".mp3"
            path = folder / f"recording_{index}{suffix}"
            size = 0
            with path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        return None
                    handle.write(chunk)
        return path if size > 100_000 else None
    except requests.RequestException as exc:
        print(f"  download failed: {exc}", file=sys.stderr)
        return None


def decode_audio(path: Path, start: float | None = None, end: float | None = None):
    """The recording, or one piece of it, as 16 kHz mono samples decoded by ffmpeg.

    faster-whisper's own decoder passes PyAV an argument a newer PyAV rejects;
    handing it samples keeps the benchmark independent of that pairing.
    """
    import numpy as np

    command = ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path)]
    if start:
        command += ["-ss", f"{start:.3f}"]
    if end is not None:
        command += ["-t", f"{end - (start or 0.0):.3f}"]
    command += ["-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    raw = subprocess.run(command, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


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


def plan(urls: list[str], recordings: int, parts: int, models: list[str], folder: Path) -> list[dict]:
    """One matrix entry per recording, model and piece, for recordings this machine can fetch."""
    entries: list[dict] = []
    planned = 0
    for url in urls:
        if planned >= recordings:
            break
        path = download_audio(url, folder, planned + 1)
        if path is None:
            continue
        planned += 1
        points = cut_points(decode_audio(path), parts)
        path.unlink()
        for model_name in models:
            entries += [
                {
                    "recording": planned,
                    "url": url,
                    "model": model_name,
                    "part": part,
                    "parts": len(points) - 1,
                    "start": round(points[part - 1], 3),
                    "end": round(points[part], 3),
                }
                for part in range(1, len(points))
            ]
    return entries


def transcribe(path: Path, model_name: str, threads: int, start: float | None = None, end: float | None = None) -> dict:
    from faster_whisper import WhisperModel

    audio = decode_audio(path, start, end)
    loaded_at = time.monotonic()
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads)
    started_at = time.monotonic()
    segments, info = model.transcribe(audio, vad_filter=True, beam_size=1, condition_on_previous_text=False)
    text = " ".join(segment.text.strip() for segment in segments)
    seconds = time.monotonic() - started_at
    middle = max(0, len(text) // 2 - SAMPLE_CHARACTERS // 2)
    return {
        "model": model_name,
        "language": f"{info.language} ({info.language_probability:.2f})",
        "audio_minutes": info.duration / 60,
        "load_seconds": started_at - loaded_at,
        "seconds": seconds,
        "speed": info.duration / seconds if seconds else 0.0,
        "words": len(text.split()),
        "sample": text[middle : middle + SAMPLE_CHARACTERS],
    }


def report(notices: list[RecordingNotice], schedules: int, days: int, runs: list[dict], threads: int) -> str:
    lines = ["# Call recording transcription benchmark", ""]
    if notices or schedules:
        counts = Counter(notice.kind for notice in notices)
        usable = counts[DIRECT] + counts[EMBEDDED]
        lines += [
            f"Window: last {days} day(s). Recording notices: {len(notices)}. Call schedules filed: {schedules}.",
            "",
            "| What the notice links to | Notices |",
            "|---|---|",
            *(f"| {kind} | {counts[kind]} |" for kind in _ORDER),
            "",
            f"Downloadable without a browser: {usable} of {len(notices)}.",
            "",
        ]
    if runs:
        lines += [
            f"Transcription on {threads} CPU thread(s):",
            "",
            "| Recording | Model | Audio (min) | Language | Model load (s) | Transcribe (s) | Speed (x real time) | Words |",
            "|---|---|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {run['recording']} | {run['model']} | {run['audio_minutes']:.1f} | {run['language']} | "
            f"{run['load_seconds']:.0f} | {run['seconds']:.0f} | {run['speed']:.1f} | {run['words']} |"
            for run in runs
        ]
        for run in runs:
            lines += ["", f"**{run['recording']} / {run['model']}** (from the middle of the call)", "", f"> {run['sample']}"]
    return "\n".join(lines) + "\n"


def _annotate(level: str, message: str) -> None:
    """Surface a line as a run annotation, which is readable without the log."""
    if os.getenv("GITHUB_ACTIONS"):
        print(f"::{level}::" + message.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))


def main() -> None:
    try:
        _run()
    except Exception:
        _annotate("error", traceback.format_exc()[-3000:])
        raise


def _run() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--days", type=int, default=14, help="window of NSE announcements to read")
    parser.add_argument("--url", action="append", default=[], help="a recording to transcribe instead of discovering one")
    parser.add_argument("--transcribe", type=int, default=0, help="how many recordings to transcribe")
    parser.add_argument("--models", nargs="+", default=["small"], help="faster-whisper model names")
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--plan", type=int, default=0, help="cut each recording into this many pieces and print the job matrix")
    parser.add_argument("--start", type=float, default=None, help="transcribe from this second of the recording")
    parser.add_argument("--end", type=float, default=None, help="transcribe up to this second of the recording")
    parser.add_argument("--label", default=None, help="what to call the recording in the report")
    arguments = parser.parse_args()

    notices: list[RecordingNotice] = []
    schedules = 0
    urls = list(arguments.url)
    if not urls:
        notices, schedules = discover(arguments.days)
        urls = [notice.url for notice in notices if notice.kind in (DIRECT, EMBEDDED) and notice.url]

    if arguments.plan:
        with TemporaryDirectory(prefix="call_audio_") as folder:
            entries = plan(urls, arguments.transcribe, arguments.plan, arguments.models, Path(folder))
        if not entries:
            raise SystemExit("no recording could be downloaded, so there is nothing to plan")
        matrix = json.dumps({"include": entries})
        print(matrix)
        kinds = Counter(notice.kind for notice in notices)
        _annotate("notice", f"notices={len(notices)} schedules={schedules} " + " ".join(f"[{kind}]={kinds[kind]}" for kind in _ORDER))
        output_path = os.getenv("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as handle:
                handle.write(f"matrix={matrix}\n")
        return

    runs: list[dict] = []
    with TemporaryDirectory(prefix="call_audio_") as folder:
        transcribed = 0
        for url in urls:
            if transcribed >= arguments.transcribe:
                break
            path = download_audio(url, Path(folder), transcribed + 1)
            if path is None:
                continue
            transcribed += 1
            megabytes = path.stat().st_size / 1e6
            for model_name in arguments.models:
                print(f"Transcribing recording {transcribed} with {model_name}...", file=sys.stderr)
                result = transcribe(path, model_name, arguments.threads, arguments.start, arguments.end)
                runs.append({"recording": arguments.label or f"#{transcribed} ({megabytes:.1f} MB)", **result})
            path.unlink()

    text = report(notices, schedules, arguments.days, runs, arguments.threads)
    print(text)
    kinds = Counter(notice.kind for notice in notices)
    _annotate("notice", f"notices={len(notices)} schedules={schedules} " + " ".join(f"[{kind}]={kinds[kind]}" for kind in _ORDER))
    for run in runs:
        _annotate(
            "notice",
            f"{run['recording']} {run['model']}: audio {run['audio_minutes']:.1f} min, language {run['language']}, "
            f"load {run['load_seconds']:.0f}s, transcribe {run['seconds']:.0f}s, {run['speed']:.1f}x real time, "
            f"{run['words']} words\n{run['sample']}",
        )
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(text)


if __name__ == "__main__":
    main()
