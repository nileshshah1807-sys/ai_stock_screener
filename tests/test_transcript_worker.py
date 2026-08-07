import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from workers.transcript_worker import TranscriptSettings, TranscriptWorker


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
                return_value=SimpleNamespace(text="Revenue rose materially this quarter.", method="pymupdf"),
            ):
                self.assertTrue(worker._process_filing(self.record, Path(temporary_directory)))

        self.assertEqual(repository.upserted_transcripts[0]["document_id"], "existing-document")
        self.assertEqual(repository.links, [("filing-1", "existing-document")])
        self.assertEqual(repository.updates[-1][1]["status"], "document_ready")

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


if __name__ == "__main__":
    unittest.main()
