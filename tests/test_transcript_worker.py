import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from workers.transcript_worker import (
    COVER_LETTER_ERROR,
    COVER_LETTER_MAX_ATTEMPTS,
    TranscriptSettings,
    TranscriptWorker,
)

# Long enough to be a call rather than a cover letter.
CALL_TEXT = "Revenue rose materially this quarter. " * 200
LETTER_TEXT = "Sub: Transcript of the earnings call. The transcript is available on the below link."


class FakeRepository:
    def __init__(self, document=None):
        self.document = document
        self.upserted_transcripts = []
        self.links = []
        self.updates = []

    def upsert_filing(self, filing):
        return {"id": "filing-1", "status": "discovered", "attempt_count": 2}

    def find_document_by_sha256(self, sha256):
        return self.document

    def find_transcript_by_document_id(self, document_id):
        return None

    def create_document(self, document):
        self.document = {"id": "document-1", **document}
        return self.document

    def upsert_transcript(self, transcript):
        self.upserted_transcripts.append(transcript)
        return transcript

    def link_filing_document(self, filing_id, document_id):
        self.links.append((filing_id, document_id))

    def update_filing(self, filing_id, **fields):
        self.updates.append((filing_id, fields))


class TranscriptWorkerTests(unittest.TestCase):
    def setUp(self):
        self.settings = TranscriptSettings(min_text_characters=20, enable_ocr=False)
        self.record = {
            "seq_id": "123",
            "symbol": "RELIANCE",
            "sm_name": "Reliance Industries Limited",
            "an_desc": "Earnings call transcript",
            "attchmntFile": "https://example.test/transcript.pdf",
            "an_dt": "2026-08-05T00:00:00+05:30",
        }

    def test_recovers_missing_transcript_for_existing_document(self):
        repository = FakeRepository({"id": "existing-document"})
        worker = TranscriptWorker(repository, self.settings)
        with tempfile.TemporaryDirectory() as temporary_directory:
            pdf_path = Path(temporary_directory) / "call.pdf"
            pdf_path.write_bytes(b"%PDF- existing document")
            worker._download_pdf = lambda url, directory: pdf_path
            with patch(
                "workers.transcript_worker.extract_pdf_text",
                return_value=SimpleNamespace(text=CALL_TEXT, method="pymupdf"),
            ):
                self.assertTrue(worker._process_filing(self.record, Path(temporary_directory)))

        self.assertEqual(repository.upserted_transcripts[0]["document_id"], "existing-document")
        self.assertEqual(repository.upserted_transcripts[0]["quarter"], "2026-06-30")
        self.assertEqual(repository.links, [("filing-1", "existing-document")])
        self.assertEqual(repository.updates[-1][1]["status"], "document_ready")

    def process_cover_letter(self, linked, repository=None):
        repository = repository or FakeRepository()
        worker = TranscriptWorker(repository, self.settings)
        with tempfile.TemporaryDirectory() as temporary_directory:
            pdf_path = Path(temporary_directory) / "letter.pdf"
            pdf_path.write_bytes(b"%PDF- cover letter")
            worker._download_pdf = lambda url, directory: pdf_path
            with patch(
                "workers.transcript_worker.extract_pdf_text",
                return_value=SimpleNamespace(text=LETTER_TEXT, method="pymupdf"),
            ), patch(
                "workers.transcript_worker.fetch_linked_transcript", return_value=linked
            ) as fetch:
                ready = worker._process_filing(self.record, Path(temporary_directory))
        return ready, repository, worker, fetch

    def test_a_cover_letter_is_stored_as_the_transcript_it_links_to(self):
        linked = (SimpleNamespace(text=CALL_TEXT, method="linked-pymupdf"), "https://example.test/call.pdf")
        ready, repository, worker, fetch = self.process_cover_letter(linked)

        self.assertTrue(ready)
        self.assertEqual(repository.upserted_transcripts[0]["cleaned_text"], CALL_TEXT)
        self.assertEqual(repository.document["extraction_method"], "linked-pymupdf")
        self.assertEqual(repository.updates[-1][1]["status"], "document_ready")
        self.assertEqual(fetch.call_args.args[2].isoformat(), "2026-08-05")
        self.assertEqual(worker._cover_letters, {"resolved": 1, "unresolved": 0})

    def test_a_cover_letter_with_no_reachable_transcript_is_not_stored(self):
        ready, repository, worker, _ = self.process_cover_letter(None)

        self.assertFalse(ready)
        self.assertEqual(repository.upserted_transcripts, [])
        self.assertEqual(repository.updates[-1], (
            "filing-1",
            {"status": "failed", "attempt_count": 3, "last_error": COVER_LETTER_ERROR},
        ))
        self.assertEqual(worker._cover_letters, {"resolved": 0, "unresolved": 1})

    def test_a_cover_letter_is_given_up_on_after_enough_attempts(self):
        repository = FakeRepository()
        repository.upsert_filing = lambda filing: {
            "id": "filing-1", "status": "failed",
            "attempt_count": COVER_LETTER_MAX_ATTEMPTS, "last_error": COVER_LETTER_ERROR,
        }
        worker = TranscriptWorker(repository, self.settings)
        worker._download_pdf = MagicMock()

        self.assertFalse(worker._process_filing(self.record, Path(".")))
        worker._download_pdf.assert_not_called()

    def repair(self, linked, **repository_fields):
        repository = MagicMock()
        repository.read_only = False
        repository.short_transcripts.return_value = [{
            "id": "t1", "symbol": "MARUTI", "call_date": "2026-08-06",
            "filing": {
                "id": "f1", "attachment_url": "https://example.test/letter.pdf",
                "announcement_date": "2026-08-06T10:00:00", "attempt_count": 0,
            },
        }]
        for name, value in repository_fields.items():
            setattr(repository, name, value)
        worker = TranscriptWorker(repository, self.settings)
        worker._download_pdf = lambda url, directory: Path("letter.pdf")
        with patch("workers.transcript_worker.fetch_linked_transcript", return_value=linked):
            summary = worker._repair_stored_cover_letters(Path("."))
        return summary, repository

    def test_a_stored_cover_letter_is_replaced_by_the_call(self):
        linked = (SimpleNamespace(text=CALL_TEXT, method="linked-pymupdf"), "https://example.test/call.pdf")
        summary, repository = self.repair(linked)

        self.assertEqual(summary, {"cover_letters_repaired": 1, "cover_letters_removed": 0})
        transcript, text = repository.replace_transcript_text.call_args.args
        self.assertEqual((transcript["id"], text), ("t1", CALL_TEXT))
        repository.delete_transcript.assert_not_called()
        # 6,000 characters, as tokens.
        repository.short_transcripts.assert_called_once_with(1500)

    def test_a_stored_cover_letter_with_no_transcript_is_removed_and_left_to_retry(self):
        summary, repository = self.repair(None)

        self.assertEqual(summary, {"cover_letters_repaired": 0, "cover_letters_removed": 1})
        repository.delete_transcript.assert_called_once_with("t1")
        repository.update_filing.assert_called_once_with(
            "f1", status="failed", attempt_count=1, last_error=COVER_LETTER_ERROR
        )

    def test_a_cover_letter_that_cannot_be_downloaded_is_left_alone(self):
        repository = MagicMock()
        repository.read_only = False
        repository.short_transcripts.return_value = [{
            "id": "t1", "symbol": "MARUTI", "call_date": "2026-08-06",
            "filing": {"id": "f1", "attachment_url": "https://example.test/letter.pdf"},
        }]
        worker = TranscriptWorker(repository, self.settings)
        worker._download_pdf = MagicMock(side_effect=ValueError("NSE unavailable"))

        summary = worker._repair_stored_cover_letters(Path("."))

        self.assertEqual(summary, {"cover_letters_repaired": 0, "cover_letters_removed": 0})
        repository.delete_transcript.assert_not_called()

    def test_a_read_only_run_repairs_nothing(self):
        summary, repository = self.repair(None, read_only=True)

        self.assertEqual(summary, {"cover_letters_repaired": 0, "cover_letters_removed": 0})
        repository.short_transcripts.assert_not_called()

    def test_records_collection_failure_for_later_retry(self):
        repository = FakeRepository()
        worker = TranscriptWorker(repository, self.settings)
        worker._download_pdf = lambda url, directory: (_ for _ in ()).throw(ValueError("NSE unavailable"))

        with self.assertRaisesRegex(ValueError, "NSE unavailable"):
            worker._process_filing(self.record, Path("."))

        self.assertEqual(repository.updates[-1], (
            "filing-1",
            {"status": "failed", "attempt_count": 3, "last_error": "NSE unavailable"},
        ))

    def test_uses_fixed_local_model_identity(self):
        # Workflow-level throughput overrides must not change this defaults test.
        with patch.dict(
            "os.environ",
            {"TRANSCRIPT_ENABLE_FINBERT": "false"},
            clear=True,
        ):
            settings = TranscriptSettings.from_environment()

        self.assertEqual(settings.model_name, "textblob-finance-lexicon")
        self.assertEqual(settings.lookback_days, 120)
        self.assertEqual(settings.max_documents_per_run, 60)
        self.assertEqual(settings.max_analyses_per_run, 60)

    def test_finbert_enabled_environment_uses_matching_model_identity(self):
        with patch.dict("os.environ", {"TRANSCRIPT_ENABLE_FINBERT": "true"}):
            settings = TranscriptSettings.from_environment()

        self.assertEqual(settings.model_name, "finbert-finance-hybrid")

    def test_pending_transcripts_are_analyzed_in_configured_batches(self):
        repository = MagicMock()
        repository.list_transcripts_for_analysis.return_value = [
            {"id": f"transcript-{index}", "symbol": f"STOCK{index}", "cleaned_text": "Revenue grew."}
            for index in range(5)
        ]
        repository.save_sentiment.side_effect = lambda payload: {
            "id": f"sentiment-{payload['transcript_id']}"
        }
        settings = TranscriptSettings(max_analyses_per_run=5, analysis_batch_size=2)
        worker = TranscriptWorker(repository, settings)
        result = {
            "overall_score": 70,
            "optimism": 70,
            "guidance_strength": 65,
            "risk_intensity": 20,
            "confidence_score": 70,
            "analyst_pressure": 30,
            "management_confidence": 70,
            "answer_quality": 75,
            "guidance_direction": "maintained",
        }

        with patch(
            "workers.transcript_worker.analyze_transcripts",
            side_effect=lambda texts: [result.copy() for _ in texts],
        ) as analyze_batch:
            summary = worker._analyze_pending_transcripts()

        self.assertEqual([len(call.args[0]) for call in analyze_batch.call_args_list], [2, 2, 1])
        self.assertEqual(repository.save_sentiment.call_count, 5)
        self.assertEqual(summary, {"analyzed": 5, "deferred": 0})

    def _worker_with(self, pending):
        repository = MagicMock()
        repository.read_only = False
        repository.list_transcripts_for_analysis.return_value = pending
        repository.save_sentiment.side_effect = lambda payload: {"id": "s"}
        return repository, TranscriptWorker(repository, TranscriptSettings(max_analyses_per_run=5))

    RESULT = {
        "overall_score": 60, "optimism": 60, "guidance_strength": 60, "risk_intensity": 20,
        "confidence_score": 60, "analyst_pressure": 30, "management_confidence": 60,
        "answer_quality": 60, "guidance_direction": "maintained",
    }

    def test_archived_text_is_restored_before_scoring_never_scored_as_empty(self):
        repository, worker = self._worker_with([
            {"id": "t1", "symbol": "A", "cleaned_text": ""},
            {"id": "t2", "symbol": "B", "cleaned_text": ""},
        ])
        repository.restore_transcript_text.side_effect = (
            lambda transcript: "Revenue grew." if transcript["id"] == "t1" else None
        )

        with patch(
            "workers.transcript_worker.analyze_transcripts",
            side_effect=lambda texts: [dict(self.RESULT) for _ in texts],
        ) as analyze:
            summary = worker._analyze_pending_transcripts()

        # t1 is scored on its archived text; t2 has none anywhere and is skipped.
        self.assertEqual(analyze.call_args_list[0].args[0], ["Revenue grew."])
        self.assertEqual(summary, {"analyzed": 1, "deferred": 1})

    def test_a_scored_transcript_has_its_text_archived(self):
        repository, worker = self._worker_with([{"id": "t1", "symbol": "A", "cleaned_text": "Margins rose."}])

        with patch(
            "workers.transcript_worker.analyze_transcripts",
            side_effect=lambda texts: [dict(self.RESULT) for _ in texts],
        ):
            worker._analyze_pending_transcripts()

        archived = repository.archive_transcript_text.call_args.args[0]
        self.assertEqual((archived["id"], archived["cleaned_text"]), ("t1", "Margins rose."))

    def test_an_archive_failure_keeps_the_saved_sentiment(self):
        repository, worker = self._worker_with([{"id": "t1", "symbol": "A", "cleaned_text": "Margins rose."}])
        repository.archive_transcript_text.side_effect = RuntimeError("storage down")

        with patch(
            "workers.transcript_worker.analyze_transcripts",
            side_effect=lambda texts: [dict(self.RESULT) for _ in texts],
        ):
            summary = worker._analyze_pending_transcripts()

        self.assertEqual(summary, {"analyzed": 1, "deferred": 0})
        self.assertEqual(repository.save_sentiment.call_count, 1)


class ArchiveTranscriptTextTests(unittest.TestCase):
    """The repository side: never clear a column the archive does not match."""

    def repository(self, stored_text):
        from storage.supabase_repository import SupabaseRepository

        repository = SupabaseRepository("https://x.test", "key")
        repository.objects = MagicMock()
        repository.objects.get_gzip_text.return_value = stored_text
        repository._request = MagicMock()
        return repository

    def transcript(self, text):
        import hashlib

        return {"id": "t1", "market": "NSE", "cleaned_text": text,
                "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}

    def test_clears_the_column_only_after_a_verified_upload(self):
        repository = self.repository("Revenue grew.")

        self.assertTrue(repository.archive_transcript_text(self.transcript("Revenue grew.")))
        path = repository.objects.put_gzip_text.call_args.args[0]
        self.assertEqual(path, "transcripts/NSE/t1.txt.gz")
        method, url = repository._request.call_args.args[:2]
        self.assertEqual((method, url), ("PATCH", "transcripts?id=eq.t1"))
        self.assertEqual(repository._request.call_args.kwargs["json"], {"cleaned_text": ""})

    def test_a_mismatched_upload_leaves_the_text_in_place(self):
        repository = self.repository("corrupted")

        with self.assertRaises(ValueError):
            repository.archive_transcript_text(self.transcript("Revenue grew."))
        repository._request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
