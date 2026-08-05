"""Scheduled, idempotent NSE transcript collection and sentiment worker."""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sentiment.analyzer import ANALYSIS_VERSION, analyze_transcript
from sentiment.openrouter_client import OpenRouterClient, OpenRouterResponseError, OpenRouterUnavailable
from storage.supabase_repository import SupabaseRepository
from transcripts.cleaner import clean_transcript_text
from transcripts.collector import discover_nse_transcripts, filing_payload
from transcripts.extractor import extract_pdf_text


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptSettings:
    lookback_days: int = 7
    max_pages: int = 120
    min_text_characters: int = 1000
    enable_ocr: bool = True
    analysis_limit: int = 25
    model_name: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    max_retries: int = 2
    timeout_seconds: int = 90

    @classmethod
    def from_environment(cls) -> "TranscriptSettings":
        return cls(
            lookback_days=int(os.getenv("TRANSCRIPT_LOOKBACK_DAYS", "7")),
            max_pages=int(os.getenv("TRANSCRIPT_MAX_PAGES", "120")),
            min_text_characters=int(os.getenv("TRANSCRIPT_MIN_TEXT_CHARACTERS", "1000")),
            enable_ocr=os.getenv("TRANSCRIPT_OCR_ENABLED", "true").lower() in {"1", "true", "yes"},
            analysis_limit=int(os.getenv("TRANSCRIPT_ANALYSIS_LIMIT", "25")),
            model_name=os.getenv("OPENROUTER_MODEL", cls.model_name),
            max_retries=int(os.getenv("OPENROUTER_MAX_RETRIES", "2")),
            timeout_seconds=int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "90")),
        )


class TranscriptWorker:
    def __init__(self, repository: SupabaseRepository, settings: TranscriptSettings):
        self.repository = repository
        self.settings = settings

    def run(self) -> dict[str, int]:
        summary = {"discovered": 0, "documents_ready": 0, "analyzed": 0, "deferred": 0, "failed": 0}
        records = discover_nse_transcripts(self.settings.lookback_days)
        summary["discovered"] = len(records)
        with TemporaryDirectory(prefix="nse_transcripts_") as temporary_directory:
            download_directory = Path(temporary_directory)
            for record in records:
                try:
                    if self._process_filing(record, download_directory):
                        summary["documents_ready"] += 1
                except Exception as exc:
                    summary["failed"] += 1
                    logger.exception("Transcript collection failed: %s", exc)
        analysis_summary = self._analyze_pending_transcripts()
        summary["analyzed"] = analysis_summary["analyzed"]
        summary["deferred"] = analysis_summary["deferred"]
        return summary

    def _process_filing(self, record: dict, download_directory: Path) -> bool:
        filing = filing_payload(record)
        if filing is None:
            logger.warning("Skipping NSE record without seq_id or symbol")
            return False
        stored_filing = self.repository.upsert_filing(filing)
        if stored_filing["status"] in {"document_ready", "rejected"}:
            return False
        try:
            attachment_url = filing.get("attachment_url") or ""
            if ".pdf" not in attachment_url.lower():
                self.repository.update_filing(stored_filing["id"], status="rejected", last_error="attachment is not a PDF")
                return False

            pdf_path = self._download_pdf(attachment_url, download_directory)
            sha256 = _sha256(pdf_path)
            document = self.repository.find_document_by_sha256(sha256)
            transcript = self.repository.find_transcript_by_document_id(document["id"]) if document else None
            if transcript is None:
                extracted = extract_pdf_text(
                    pdf_path,
                    self.settings.min_text_characters,
                    self.settings.enable_ocr,
                    self.settings.max_pages,
                )
                cleaned_text = clean_transcript_text(extracted.text)
                if len(cleaned_text) < self.settings.min_text_characters:
                    raise ValueError("cleaned transcript text is too short")
                if document is None:
                    document = self.repository.create_document({
                        "sha256": sha256,
                        "size_bytes": pdf_path.stat().st_size,
                        "extraction_method": extracted.method,
                    })
                self.repository.upsert_transcript({
                    "document_id": document["id"],
                    "symbol": filing["symbol"],
                    "quarter": _announcement_quarter(filing.get("announcement_date")),
                    "call_date": _announcement_date(filing.get("announcement_date")),
                    "cleaned_text": cleaned_text,
                    "token_count": (len(cleaned_text) + 3) // 4,
                    "text_hash": hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest(),
                })
            self.repository.link_filing_document(stored_filing["id"], document["id"])
            self.repository.update_filing(stored_filing["id"], status="document_ready", last_error=None)
            return True
        except Exception as exc:
            self.repository.update_filing(
                stored_filing["id"],
                status="failed",
                attempt_count=int(stored_filing.get("attempt_count") or 0) + 1,
                last_error=str(exc)[:1000],
            )
            raise

    def _download_pdf(self, attachment_url: str, download_directory: Path) -> Path:
        from nse import NSE

        with NSE(download_folder=download_directory, server=False, timeout=60) as nse:
            downloaded_path = Path(nse.download_document(attachment_url))
        if not downloaded_path.is_file() or downloaded_path.stat().st_size == 0:
            raise ValueError("NSE download returned no file")
        if downloaded_path.read_bytes()[:5] != b"%PDF-":
            raise ValueError("NSE attachment is not a valid PDF")
        return downloaded_path

    def _analyze_pending_transcripts(self) -> dict[str, int]:
        if not self.settings.model_name.endswith(":free"):
            raise ValueError("Paid OpenRouter models are disabled until a priced reservation policy is configured")
        client = OpenRouterClient(
            os.getenv("OPENROUTER_API_KEY", ""),
            self.settings.model_name,
            self.settings.max_retries,
            self.settings.timeout_seconds,
        )
        summary = {"analyzed": 0, "deferred": 0}
        for transcript in self.repository.list_transcripts_for_analysis(self.settings.analysis_limit):
            if self.repository.get_sentiment(transcript["id"], self.settings.model_name, ANALYSIS_VERSION):
                continue
            try:
                result = analyze_transcript(transcript["cleaned_text"], client)
                self.repository.save_sentiment({
                    "transcript_id": transcript["id"],
                    "overall_score": result["overall_score"],
                    "optimism_score": result["optimism"],
                    "guidance_score": result["guidance_strength"],
                    "risk_score": result["risk_intensity"],
                    "confidence_score": result["confidence_score"],
                    "analyst_pressure": result["analyst_pressure"],
                    "management_confidence": result["management_confidence"],
                    "answer_quality": result["answer_quality"],
                    "guidance_direction": result["guidance_direction"],
                    "structured_output": result,
                    "model_name": self.settings.model_name,
                    "analysis_version": ANALYSIS_VERSION,
                    "estimated_cost_usd": 0,
                })
                summary["analyzed"] += 1
            except OpenRouterUnavailable as exc:
                summary["deferred"] += 1
                logger.warning("Deferred transcript %s: %s", transcript["id"], exc)
            except OpenRouterResponseError as exc:
                summary["deferred"] += 1
                logger.warning("Invalid model response for transcript %s: %s", transcript["id"], exc)
        return summary


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _announcement_date(value: str | None) -> str | None:
    return value[:10] if value else None


def _announcement_quarter(value: str | None) -> str | None:
    if not value:
        return None
    announcement = datetime.fromisoformat(value)
    return f"{announcement.year}-Q{(announcement.month - 1) // 3 + 1}"


def main() -> None:
    settings = TranscriptSettings.from_environment()
    summary = TranscriptWorker(SupabaseRepository.from_environment(), settings).run()
    logger.info("Transcript worker summary: %s", summary)


if __name__ == "__main__":
    main()