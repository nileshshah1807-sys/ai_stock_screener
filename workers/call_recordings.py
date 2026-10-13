"""Read an earnings call the day it is held, from the recording the company files.

The transcript worker waits for the filed transcript, which arrives days after
the call. A "link of recording" notice arrives the same evening. This worker
turns that recording into text with an open-source speech model and stores it
as the call's transcript, so the tone score, the outlook and the screener pick
it up without knowing the difference.

It runs as three steps of one workflow (`call-recordings.yml`), because an
hour of audio takes twenty minutes to transcribe on one hosted runner and five
on four:

``plan``
    Reads the recording notices, downloads each new recording, cuts it at
    pauses and writes the plan: one entry per call, one job per piece. A
    notice without an audio file is resolved by
    `transcripts/recording_sources.py`. A call with no recording to fetch is
    stored here from a vendor's transcript (`transcripts/vendor_transcripts.py`)
    when there is one, and otherwise left waiting and looked for again while
    its notice is still being read.
``piece``
    Transcribes one piece. Runs once per piece, in parallel, with no secrets.
``assemble``
    Joins the pieces of each call, stores the text, and scores what is pending.

A transcript made this way is marked by its document's ``extraction_method``
(``speech:<model>``). When the company files its own transcript the transcript
worker stores that and removes this one: the filed text has the speakers and
the figures as the company wrote them.

Usage::

    python -m workers.call_recordings plan --out call-recordings
    python -m workers.call_recordings piece --plan call-recordings/plan.json --key 123 --part 1 --out pieces
    python -m workers.call_recordings assemble --plan call-recordings/plan.json --pieces pieces
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from transcripts.cleaner import clean_transcript_text
from transcripts.collector import discover_nse_announcements, filing_payload
from transcripts.periods import reporting_period_end_for_call
from transcripts.recording_sources import RecordingSource, source_from_notice
from transcripts.recordings import (
    DOWNLOADABLE,
    NONE,
    SAMPLE_RATE,
    SPEECH_METHOD_PREFIX,
    VENDOR_METHOD_PREFIX,
    classify_links,
    cut_points,
    decode_audio,
    download_audio,
    download_notice,
    is_recording_notice,
    pdf_links,
    piece_count,
    stitch,
)
from transcripts.speech import DEFAULT_MODEL
from transcripts.vendor_transcripts import fetch_transcript, find_transcript, list_transcripts, vendor_name

logger = logging.getLogger(__name__)

ALREADY_FILED_ERROR = "a transcript of this call is already stored"
NOT_ENGLISH_ERROR = "recording is not in English; left for the filed transcript"
#: A filing left as it is, to be looked for again on every run that still
#: reads its notice: the vendor posts a call an hour or so after it starts.
WAITING_ERROR = "no recording found yet"


@dataclass(frozen=True)
class RecordingSettings:
    lookback_days: int = 3
    # Four pieces a call and twenty concurrent jobs on a public repository.
    max_calls_per_run: int = 5
    max_parts: int = 4
    piece_seconds: int = 900
    model_name: str = DEFAULT_MODEL
    # A site that refuses the download six runs in a row is not going to serve it.
    max_attempts: int = 6
    min_audio_minutes: float = 5.0
    max_audio_minutes: float = 240.0
    min_text_characters: int = 3000
    # A site that publishes its own transcript of each call, asked when the
    # notice leads to no recording this job can fetch. Unset, such a call
    # waits for its filed transcript.
    vendor_url: str = ""

    @classmethod
    def from_environment(cls) -> RecordingSettings:
        return cls(
            lookback_days=max(1, int(os.getenv("CALL_RECORDING_LOOKBACK_DAYS", "3"))),
            max_calls_per_run=max(1, int(os.getenv("CALL_RECORDING_MAX_CALLS_PER_RUN", "5"))),
            max_parts=max(1, int(os.getenv("CALL_RECORDING_MAX_PARTS", "4"))),
            piece_seconds=max(60, int(os.getenv("CALL_RECORDING_PIECE_SECONDS", "900"))),
            model_name=os.getenv("CALL_RECORDING_MODEL", "").strip() or DEFAULT_MODEL,
            max_attempts=max(1, int(os.getenv("CALL_RECORDING_MAX_ATTEMPTS", "6"))),
            min_text_characters=max(1, int(os.getenv("CALL_RECORDING_MIN_TEXT_CHARACTERS", "3000"))),
            vendor_url=os.getenv("CALL_TRANSCRIPT_VENDOR_URL", "").strip(),
        )


class CallRecordingWorker:
    def __init__(self, repository, settings: RecordingSettings):
        self.repository = repository
        self.settings = settings
        self._vendor_listing: list[dict[str, Any]] | None = None
        #: Calls stored this run from a vendor's transcript, with no audio to cut.
        self.vendor_stored = 0

    # -- plan -----------------------------------------------------------------

    def plan(self, out_directory: Path) -> dict[str, Any]:
        """Choose this run's calls and cut their recordings; returns the plan."""
        audio_directory = out_directory / "audio"
        audio_directory.mkdir(parents=True, exist_ok=True)
        records = discover_nse_announcements(self.settings.lookback_days, is_recording_notice)
        logger.info("NSE discovery completed: %s recording notice(s)", len(records))
        calls: list[dict[str, Any]] = []
        with TemporaryDirectory(prefix="nse_recordings_") as notices:
            for record in records:
                if len(calls) >= self.settings.max_calls_per_run:
                    logger.info("Recording batch limit reached: %s call(s)", len(calls))
                    break
                try:
                    call = self._plan_call(record, Path(notices), audio_directory)
                except Exception as exc:  # noqa: BLE001 - one notice must not stop the others
                    logger.exception("Planning a recording failed: %s", exc)
                    continue
                if call:
                    calls.append(call)
        plan = {"model": self.settings.model_name, "calls": calls, "vendor_transcripts": self.vendor_stored}
        (out_directory / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return plan

    def _plan_call(self, record: dict, notices: Path, audio_directory: Path) -> dict[str, Any] | None:
        filing = filing_payload(record)
        if filing is None:
            return None
        stored = self.repository.upsert_filing(filing)
        attempts = int(stored.get("attempt_count") or 0)
        if stored["status"] in {"document_ready", "rejected"} or attempts >= self.settings.max_attempts:
            return None
        quarter = _results_period(filing.get("announcement_date"))
        if quarter and self.repository.has_transcript(filing["symbol"], quarter):
            self.repository.update_filing(stored["id"], status="rejected", last_error=ALREADY_FILED_ERROR)
            return None
        source = self._find_source(filing, stored, quarter, notices)
        if source is None:
            return None
        audio = download_audio(source.url, audio_directory, filing["seq_id"])
        if audio is None:
            # A refused recording is tried again; a vendor's text ends the wait.
            if not self._store_vendor_transcript(filing, stored, quarter):
                self._failed(stored, f"recording could not be downloaded ({source.found})")
            return None
        try:
            samples = decode_audio(audio)
        except Exception as exc:  # noqa: BLE001 - a shared file can be anything; ffmpeg says so
            audio.unlink(missing_ok=True)
            self._failed(stored, f"recording could not be decoded ({source.found}): {exc}")
            return None
        minutes = len(samples) / SAMPLE_RATE / 60
        if not self.settings.min_audio_minutes <= minutes <= self.settings.max_audio_minutes:
            audio.unlink()
            self.repository.update_filing(
                stored["id"], status="rejected", last_error=f"recording is {minutes:.0f} minutes long"
            )
            return None
        points = cut_points(
            samples, piece_count(minutes * 60, self.settings.piece_seconds, self.settings.max_parts)
        )
        logger.info(
            "Planned %s: %.0f minutes in %s piece(s) from %s (%s)",
            filing["symbol"], minutes, len(points) - 1, source.url, source.found,
        )
        return {
            "key": filing["seq_id"],
            "filing_id": stored["id"],
            "attempt_count": attempts,
            "symbol": filing["symbol"],
            "announcement_date": filing.get("announcement_date"),
            "url": source.url,
            "source": source.found,
            "audio": audio.name,
            "sha256": _sha256(audio),
            "size_bytes": audio.stat().st_size,
            "pieces": [
                {"part": part, "start": round(points[part - 1], 3), "end": round(points[part], 3)}
                for part in range(1, len(points))
            ],
        }

    def _find_source(
        self, filing: dict, stored: dict, quarter: str | None, notices: Path
    ) -> RecordingSource | None:
        """Where this call's recording is; or None, with the call stored from a vendor or marked for why not."""
        quarter_end = date.fromisoformat(quarter) if quarter else None
        # A filing already waiting has had its notice read: only the vendor can have changed.
        waiting = str(stored.get("last_error") or "").startswith(WAITING_ERROR)
        kind = NONE
        if not waiting:
            try:
                kind, url = classify_links(pdf_links(download_notice(filing.get("attachment_url") or "", notices)))
            except Exception as exc:
                self._failed(stored, f"notice could not be read: {exc}")
                raise
            # Past a direct file, every rule needs to know which quarter it is looking for.
            source = source_from_notice(kind, url, quarter_end) if quarter_end or kind in DOWNLOADABLE else None
            if source:
                return source
        if self._store_vendor_transcript(filing, stored, quarter):
            return None
        if self.settings.vendor_url and quarter_end:
            if not waiting:
                self.repository.update_filing(stored["id"], last_error=f"{WAITING_ERROR} ({kind})")
            return None
        # The notice will not change, so neither will this.
        self.repository.update_filing(
            stored["id"], status="rejected", last_error=f"no downloadable recording ({kind})"
        )
        logger.info("No downloadable recording for %s: %s", filing["symbol"], kind)
        return None

    def _store_vendor_transcript(self, filing: dict, stored: dict, quarter: str | None) -> bool:
        """Store the vendor's transcript of this call, if it has one; whether it did."""
        base_url = self.settings.vendor_url
        if not base_url or not quarter:
            return False
        if self._vendor_listing is None:
            self._vendor_listing = list_transcripts(base_url)
            logger.info("Transcript vendor listed: %s transcript(s)", len(self._vendor_listing))
        entry = find_transcript(self._vendor_listing, filing["symbol"], date.fromisoformat(quarter))
        if entry is None:
            return False
        text = clean_transcript_text(fetch_transcript(base_url, entry) or "")
        if len(text) < self.settings.min_text_characters:
            return False
        encoded = text.encode("utf-8")
        self._store_text(
            filing_id=stored["id"],
            symbol=filing["symbol"],
            announcement_date=filing.get("announcement_date"),
            text=text,
            sha256=hashlib.sha256(encoded).hexdigest(),
            size_bytes=len(encoded),
            extraction_method=f"{VENDOR_METHOD_PREFIX}{vendor_name(base_url)}",
        )
        self.vendor_stored += 1
        logger.info(
            "Stored the call of %s from a vendor's transcript: %s characters (%s)",
            filing["symbol"], len(text), entry.get("link"),
        )
        return True

    def _store_text(
        self,
        *,
        filing_id: str,
        symbol: str,
        announcement_date: str | None,
        text: str,
        sha256: str,
        size_bytes: int,
        extraction_method: str,
    ) -> None:
        """Store a call's text as its transcript, marked by how the text was obtained."""
        document = self.repository.find_document_by_sha256(sha256) or self.repository.create_document({
            "sha256": sha256,
            "size_bytes": size_bytes,
            "extraction_method": extraction_method,
        })
        self.repository.upsert_transcript({
            "document_id": document["id"],
            "symbol": symbol,
            "quarter": _results_period(announcement_date),
            "call_date": _announcement_date(announcement_date),
            "cleaned_text": text,
            "token_count": (len(text) + 3) // 4,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
        self.repository.link_filing_document(filing_id, document["id"])
        self.repository.update_filing(filing_id, status="document_ready", last_error=None)

    def _failed(self, stored: dict, error: str) -> None:
        self.repository.update_filing(
            stored["id"],
            status="failed",
            attempt_count=int(stored.get("attempt_count") or 0) + 1,
            last_error=error[:1000],
        )

    # -- assemble -------------------------------------------------------------

    def assemble(self, plan: dict[str, Any], pieces_directory: Path) -> dict[str, int]:
        """Store each planned call whose every piece came back."""
        summary = {"planned": len(plan.get("calls") or []), "stored": 0, "incomplete": 0, "rejected": 0}
        for call in plan.get("calls") or []:
            try:
                outcome = self._assemble_call(call, plan.get("model") or self.settings.model_name, pieces_directory)
            except Exception as exc:  # noqa: BLE001 - one call must not stop the others
                logger.exception("Storing the call of %s failed: %s", call.get("symbol"), exc)
                outcome = "incomplete"
            summary[outcome] += 1
        return summary

    def _assemble_call(self, call: dict[str, Any], model_name: str, pieces_directory: Path) -> str:
        stored = {"id": call["filing_id"], "attempt_count": call.get("attempt_count")}
        pieces = [read_piece(pieces_directory, call["key"], piece["part"]) for piece in call["pieces"]]
        missing = sum(1 for piece in pieces if piece is None)
        if missing:
            self._failed(stored, f"{missing} of {len(pieces)} piece(s) were not transcribed")
            return "incomplete"
        if any(piece.get("language") not in (None, "en") for piece in pieces):
            # The tone score and the outlook both read English.
            self.repository.update_filing(call["filing_id"], status="rejected", last_error=NOT_ENGLISH_ERROR)
            return "rejected"
        text = clean_transcript_text(stitch([piece["text"] for piece in pieces]))
        if len(text) < self.settings.min_text_characters:
            self.repository.update_filing(
                call["filing_id"], status="rejected", last_error=f"recording gave {len(text)} characters of text"
            )
            return "rejected"
        self._store_text(
            filing_id=call["filing_id"],
            symbol=call["symbol"],
            announcement_date=call.get("announcement_date"),
            text=text,
            sha256=call["sha256"],
            size_bytes=call["size_bytes"],
            extraction_method=f"{SPEECH_METHOD_PREFIX}{model_name}",
        )
        logger.info("Stored the call of %s from its recording: %s characters", call["symbol"], len(text))
        return "stored"


# The piece jobs install the speech packages only, so nothing here may import
# the transcript worker at module level: it brings the whole scoring stack.


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _announcement_date(value: str | None) -> str | None:
    return value[:10] if value else None


def _results_period(value: str | None) -> str | None:
    """The quarter a call explains, by the transcript worker's own rule."""
    try:
        return reporting_period_end_for_call(date.fromisoformat(str(value)[:10])).isoformat()
    except ValueError:
        return None


def piece_path(directory: Path, key: str, part: int) -> Path:
    return directory / f"piece-{key}-{part}.json"


def read_piece(directory: Path, key: str, part: int) -> dict[str, Any] | None:
    """A transcribed piece, wherever the artifact download put it; None when absent."""
    name = piece_path(directory, key, part).name
    for path in [directory / name, *directory.glob(f"*/{name}")]:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def transcribe_piece(plan: dict[str, Any], key: str, part: int, plan_directory: Path, out_directory: Path) -> Path:
    from transcripts.speech import transcribe

    call = next(call for call in plan["calls"] if call["key"] == key)
    piece = next(piece for piece in call["pieces"] if piece["part"] == part)
    result = transcribe(
        plan_directory / "audio" / call["audio"], piece["start"], piece["end"], model_name=plan["model"]
    )
    logger.info(
        "%s piece %s: %.0f s of audio in %.0f s", call["symbol"], part, result["audio_seconds"], result["seconds"]
    )
    out_directory.mkdir(parents=True, exist_ok=True)
    path = piece_path(out_directory, key, part)
    path.write_text(json.dumps({"key": key, "part": part, **result}), encoding="utf-8")
    return path


def matrix(plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The plan as a job matrix: one entry per piece."""
    return {
        "include": [
            {"key": call["key"], "symbol": call["symbol"], "part": piece["part"], "parts": len(call["pieces"])}
            for call in plan.get("calls") or []
            for piece in call["pieces"]
        ]
    }


def _write_outputs(**outputs: str) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            handle.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    steps = parser.add_subparsers(dest="step", required=True)
    plan_step = steps.add_parser("plan")
    plan_step.add_argument("--out", type=Path, required=True)
    piece_step = steps.add_parser("piece")
    piece_step.add_argument("--plan", type=Path, required=True)
    piece_step.add_argument("--key", required=True)
    piece_step.add_argument("--part", type=int, required=True)
    piece_step.add_argument("--out", type=Path, required=True)
    assemble_step = steps.add_parser("assemble")
    assemble_step.add_argument("--plan", type=Path, required=True)
    assemble_step.add_argument("--pieces", type=Path, required=True)
    assemble_step.add_argument("--no-analysis", action="store_true", help="store the text and leave the scoring")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if args.step == "piece":
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        transcribe_piece(plan, args.key, args.part, args.plan.parent, args.out)
        return 0

    from storage.supabase_repository import SupabaseRepository

    worker = CallRecordingWorker(SupabaseRepository.from_environment(), RecordingSettings.from_environment())
    if args.step == "plan":
        plan = worker.plan(args.out)
        _write_outputs(
            calls=str(len(plan["calls"])),
            vendor_transcripts=str(plan["vendor_transcripts"]),
            matrix=json.dumps(matrix(plan)),
        )
        logger.info(
            "Call recordings planned: %s call(s); %s stored from a vendor's transcript",
            len(plan["calls"]), plan["vendor_transcripts"],
        )
        return 0

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    summary = worker.assemble(plan, args.pieces)
    logger.info("Call recordings summary: %s", summary)
    # A vendor's transcript was stored by the plan step and is as unscored as these.
    if (summary["stored"] or plan.get("vendor_transcripts")) and not args.no_analysis:
        from workers.transcript_worker import TranscriptSettings, TranscriptWorker

        analysis = TranscriptWorker(worker.repository, TranscriptSettings.from_environment()).analyze_pending()
        logger.info("Tone analysis: %s", analysis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
