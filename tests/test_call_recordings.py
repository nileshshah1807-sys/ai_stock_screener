"""Reading a call from its recording, the day it is held.

The rules worth pinning: only a notice that names an audio file is served; a
call is stored only when every piece of it came back; a recording that cannot
be read as English is left for the filed transcript; and the filed transcript,
when it comes, replaces the recording's.
"""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import requests

from transcripts.recordings import (
    DIRECT,
    EMBEDDED,
    NONE,
    PAGE,
    SAMPLE_RATE,
    VIDEO,
    classify_links,
    cut_points,
    is_recording_notice,
    piece_count,
    stitch,
)
from workers.call_recordings import (
    ALREADY_FILED_ERROR,
    NOT_ENGLISH_ERROR,
    CallRecordingWorker,
    RecordingSettings,
    matrix,
    piece_path,
)
from workers.transcript_worker import TranscriptSettings, TranscriptWorker

SPOKEN = "Revenue grew eighteen percent and we expect margins to hold through the year. "


def notice(description, attachment_text=""):
    return {"desc": description, "attchmntText": attachment_text}


class RecordingNoticeTests(unittest.TestCase):
    def test_a_recording_notice_is_recognised(self):
        self.assertTrue(is_recording_notice(notice("Analysts/Institutional Investor Meet/Con. Call Updates", "Link of Recording")))
        self.assertTrue(is_recording_notice(notice("Con. Call Updates", "Audio recording of the earnings call")))

    def test_a_schedule_is_not_a_recording(self):
        self.assertFalse(is_recording_notice(notice("Con. Call Updates", "Schedule of meet; webcast details")))

    def test_a_notice_that_carries_the_transcript_belongs_to_the_transcript_collector(self):
        self.assertFalse(is_recording_notice(notice("Con. Call Updates", "Audio recording and transcript of the call")))

    def test_other_announcements_are_ignored(self):
        self.assertFalse(is_recording_notice(notice("Press Release", "Recording of the event")))


class LinkTests(unittest.TestCase):
    def test_an_audio_file_is_direct(self):
        self.assertEqual(
            classify_links(["https://example.test/ir/Q2-call.mp3"]),
            (DIRECT, "https://example.test/ir/Q2-call.mp3"),
        )

    def test_a_link_rejoined_with_the_text_after_it_is_cut_back_to_the_file(self):
        self.assertEqual(
            classify_links(["https://example.test/ir/Q2-call.mp3Thankingyou"]),
            (DIRECT, "https://example.test/ir/Q2-call.mp3"),
        )

    def test_a_player_link_yields_the_file_it_names(self):
        kind, url = classify_links(["https://example.test/player?file=/media/q2.m4a&autoplay=1"])
        self.assertEqual((kind, url), (EMBEDDED, "https://example.test/media/q2.m4a"))

    def test_the_most_usable_link_wins(self):
        links = ["https://example.test/investors", "https://youtu.be/abc", "https://example.test/q2.mp3."]
        self.assertEqual(classify_links(links), (DIRECT, "https://example.test/q2.mp3"))

    def test_a_page_a_video_and_the_exchange_are_not_downloads(self):
        self.assertEqual(classify_links(["https://example.test/investors"])[0], PAGE)
        self.assertEqual(classify_links(["https://www.youtube.com/watch?v=abc"])[0], VIDEO)
        self.assertEqual(classify_links(["https://www.nseindia.com/corporate/x.mp3"]), (NONE, None))
        self.assertEqual(classify_links([]), (NONE, None))


class CuttingTests(unittest.TestCase):
    def test_each_cut_moves_to_the_pause_nearest_its_even_position(self):
        samples = np.random.default_rng(0).normal(0, 0.3, SAMPLE_RATE * 600).astype(np.float32)
        for second in (148, 305, 441):
            samples[second * SAMPLE_RATE : (second + 1) * SAMPLE_RATE] = 0
        points = cut_points(samples, 4)
        self.assertEqual((points[0], points[-1]), (0.0, 600.0))
        for cut, pause in zip(points[1:-1], (148, 305, 441)):
            self.assertTrue(pause <= cut <= pause + 1, (cut, pause))

    def test_one_piece_is_the_whole_recording(self):
        self.assertEqual(cut_points(np.zeros(SAMPLE_RATE * 60, dtype=np.float32), 1), [0.0, 60.0])

    def test_a_short_call_is_not_cut_into_four(self):
        self.assertEqual(piece_count(20 * 60, 900, 4), 2)
        self.assertEqual(piece_count(5 * 60, 900, 4), 1)
        self.assertEqual(piece_count(3 * 3600, 900, 4), 4)

    def test_pieces_join_in_order_and_empty_ones_vanish(self):
        self.assertEqual(stitch(["first\nsecond ", "", "  third"]), "first\nsecond\nthird")


class FakeRepository:
    read_only = False

    def __init__(self, filing=None, has_transcript=False):
        self.filing = {"id": "filing-1", "status": "discovered", "attempt_count": 0, **(filing or {})}
        self._has_transcript = has_transcript
        self.updates = []
        self.documents = []
        self.transcripts = []
        self.links = []
        self.deleted = []

    def upsert_filing(self, filing):
        return self.filing

    def update_filing(self, filing_id, **fields):
        self.updates.append((filing_id, fields))

    def has_transcript(self, symbol, quarter):
        self.asked = (symbol, quarter)
        return self._has_transcript

    def find_document_by_sha256(self, sha256):
        return None

    def find_transcript_by_document_id(self, document_id):
        return None

    def create_document(self, document):
        self.documents.append(document)
        return {"id": "document-1", **document}

    def upsert_transcript(self, transcript):
        self.transcripts.append(transcript)
        return transcript

    def link_filing_document(self, filing_id, document_id):
        self.links.append((filing_id, document_id))

    def delete_speech_transcripts(self, symbol, quarter):
        self.deleted.append((symbol, quarter))
        return 1


RECORD = {
    "seq_id": "900",
    "symbol": "ALPHA",
    "sm_name": "Alpha Limited",
    "desc": "Analysts/Institutional Investor Meet/Con. Call Updates",
    "attchmntText": "Link of Recording",
    "attchmntFile": "https://nsearchives.test/900.pdf",
    "an_dt": "2026-10-12T19:40:00",
}


class PlanTests(unittest.TestCase):
    def plan(
        self,
        repository,
        links=("https://alpha.test/q2.mp3",),
        audio_minutes=40,
        downloaded=True,
        settings=None,
    ):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        audio_path = self.directory / "audio" / "900.mp3"
        self.fetched = []

        def download(url, folder, name):
            self.fetched.append(("file", url))
            if not downloaded:
                return None
            audio_path.write_bytes(b"audio" * 100)
            return audio_path

        samples = np.zeros(int(SAMPLE_RATE * 60 * audio_minutes), dtype=np.float32)
        with (
            patch("workers.call_recordings.discover_nse_announcements", return_value=[RECORD]),
            patch("workers.call_recordings.download_notice", return_value=Path("notice.pdf")) as self.notice,
            patch("workers.call_recordings.pdf_links", return_value=list(links)),
            patch("workers.call_recordings.download_audio", side_effect=download),
            patch("workers.call_recordings.decode_audio", return_value=samples),
            # An investor page is never asked for in a test: it does not answer.
            patch("transcripts.recording_sources.requests.get", side_effect=requests.ConnectionError("offline")),
        ):
            return CallRecordingWorker(repository, settings or RecordingSettings()).plan(self.directory)

    def test_a_recording_is_cut_into_pieces_and_written_to_the_plan(self):
        repository = FakeRepository()
        plan = self.plan(repository)
        (call,) = plan["calls"]
        self.assertEqual((call["key"], call["symbol"], call["audio"]), ("900", "ALPHA", "900.mp3"))
        self.assertEqual([piece["part"] for piece in call["pieces"]], [1, 2, 3])
        self.assertEqual((call["pieces"][0]["start"], call["pieces"][-1]["end"]), (0.0, 2400.0))
        self.assertEqual(repository.asked, ("ALPHA", "2026-09-30"))
        self.assertEqual(json.loads((self.directory / "plan.json").read_text()), plan)
        self.assertEqual(
            matrix(plan)["include"][0], {"key": "900", "symbol": "ALPHA", "part": 1, "parts": 3}
        )

    def test_a_file_the_site_refuses_to_a_script_is_downloaded_by_the_browser(self):
        repository = FakeRepository()
        settings = RecordingSettings(browse_pages=True)
        browser = patch("workers.call_recordings.download_in_browser")
        with browser as fetch:
            def save(url, folder, name):
                (folder / "900.mp3").write_bytes(b"x" * 200_000)
                return folder / "900.mp3"

            fetch.side_effect = save
            plan = self.plan(repository, downloaded=False, settings=settings)
        self.assertEqual([call["key"] for call in plan["calls"]], ["900"])
        self.assertEqual(fetch.call_args.args[0], "https://alpha.test/q2.mp3")

    def test_a_refused_file_is_not_sent_to_the_browser_unless_the_run_has_one(self):
        repository = FakeRepository()
        with patch("workers.call_recordings.download_in_browser") as fetch:
            plan = self.plan(repository, downloaded=False)
        fetch.assert_not_called()
        self.assertEqual(plan["calls"], [])
        self.assertIn("could not be downloaded", repository.updates[0][1]["last_error"])

    def test_a_call_whose_transcript_is_already_stored_is_not_transcribed(self):
        repository = FakeRepository(has_transcript=True)
        self.assertEqual(self.plan(repository)["calls"], [])
        self.assertEqual(repository.updates, [("filing-1", {"status": "rejected", "last_error": ALREADY_FILED_ERROR})])

    def test_a_notice_that_points_at_a_page_is_left_for_the_filed_transcript(self):
        repository = FakeRepository()
        self.assertEqual(self.plan(repository, links=["https://alpha.test/investors"])["calls"], [])
        self.assertEqual(repository.updates[0][1]["status"], "rejected")
        self.assertIn("web page", repository.updates[0][1]["last_error"])

    def test_a_video_is_not_fetched_and_waits_for_the_filed_transcript(self):
        repository = FakeRepository()
        self.assertEqual(self.plan(repository, links=["https://youtu.be/abcdefghijk"])["calls"], [])
        self.assertEqual(self.fetched, [])
        self.assertIn("video platform", repository.updates[0][1]["last_error"])

    def test_a_page_is_resolved_with_the_notice_s_day_and_the_browser_switch(self):
        with patch("workers.call_recordings.source_from_notice", return_value=None) as resolve:
            self.plan(FakeRepository(), links=["https://alpha.test/investors"])
        self.assertEqual(
            resolve.call_args.kwargs,
            {"announced": date(2026, 10, 12), "browse": False, "pages": ["https://alpha.test/investors"]},
        )

    def test_every_page_a_notice_names_is_handed_over_the_most_specific_first(self):
        links = ["https://www.alpha.test/", "https://www.alpha.test/investors/calls", "https://www.alpha.test"]
        with patch("workers.call_recordings.source_from_notice", return_value=None) as resolve:
            self.plan(FakeRepository(), links=links)
        self.assertEqual(
            resolve.call_args.kwargs["pages"], ["https://www.alpha.test/investors/calls", "https://www.alpha.test/"]
        )

    def test_a_page_not_opened_because_the_run_s_browser_time_is_spent_is_left_for_the_next_run(self):
        repository = FakeRepository()
        settings = RecordingSettings(browse_pages=True, browse_seconds_per_run=0)
        with patch("workers.call_recordings.source_from_notice", return_value=None) as resolve:
            self.plan(repository, links=["https://alpha.test/investors"], settings=settings)
        self.assertFalse(resolve.call_args.kwargs["browse"])
        self.assertEqual(repository.updates, [])

    def test_a_page_opened_in_the_browser_and_found_empty_is_rejected(self):
        repository = FakeRepository()
        settings = RecordingSettings(browse_pages=True)
        with patch("workers.call_recordings.source_from_notice", return_value=None) as resolve:
            self.plan(repository, links=["https://alpha.test/investors"], settings=settings)
        self.assertTrue(resolve.call_args.kwargs["browse"])
        self.assertEqual(repository.updates[0][1]["status"], "rejected")

    def test_a_refused_download_is_tried_again_on_a_later_run(self):
        repository = FakeRepository(filing={"attempt_count": 2})
        self.assertEqual(self.plan(repository, downloaded=False)["calls"], [])
        self.assertEqual(repository.updates[0][1]["status"], "failed")
        self.assertEqual(repository.updates[0][1]["attempt_count"], 3)

    def test_a_filing_that_is_done_or_out_of_attempts_is_skipped(self):
        for filing in ({"status": "document_ready"}, {"status": "rejected"}, {"status": "failed", "attempt_count": 6}):
            repository = FakeRepository(filing=filing)
            self.assertEqual(self.plan(repository)["calls"], [])
            self.assertEqual(repository.updates, [])

    def test_a_clip_too_short_to_be_a_call_is_rejected(self):
        repository = FakeRepository()
        self.assertEqual(self.plan(repository, audio_minutes=2)["calls"], [])
        self.assertEqual(repository.updates[0][1]["status"], "rejected")


class AssembleTests(unittest.TestCase):
    CALL = {
        "key": "900",
        "filing_id": "filing-1",
        "attempt_count": 1,
        "symbol": "ALPHA",
        "announcement_date": "2026-10-12T19:40:00",
        "sha256": "a" * 64,
        "size_bytes": 5_000_000,
        "pieces": [{"part": 1, "start": 0.0, "end": 900.0}, {"part": 2, "start": 900.0, "end": 1800.0}],
    }

    def assemble(self, pieces, nested=False, has_transcript=False):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for part, piece in pieces.items():
            path = piece_path(directory / f"call-piece-900-{part}" if nested else directory, "900", part)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"key": "900", "part": part, "language": "en", **piece}))
        repository = FakeRepository(has_transcript=has_transcript)
        plan = {"model": "large-v3-turbo", "calls": [self.CALL]}
        return CallRecordingWorker(repository, RecordingSettings()).assemble(plan, directory), repository

    def test_a_complete_call_is_stored_as_a_transcript_marked_as_speech(self):
        summary, repository = self.assemble({1: {"text": SPOKEN * 30}, 2: {"text": SPOKEN * 30}})
        self.assertEqual(summary, {"planned": 1, "stored": 1, "incomplete": 0, "rejected": 0})
        self.assertEqual(repository.documents[0]["extraction_method"], "speech:large-v3-turbo")
        (transcript,) = repository.transcripts
        self.assertEqual(
            (transcript["symbol"], transcript["quarter"], transcript["call_date"]),
            ("ALPHA", "2026-09-30", "2026-10-12"),
        )
        self.assertGreater(len(transcript["cleaned_text"]), 3000)
        self.assertEqual(repository.updates[-1], ("filing-1", {"status": "document_ready", "last_error": None}))

    def test_pieces_are_found_in_the_folders_an_artifact_download_makes(self):
        summary, _ = self.assemble({1: {"text": SPOKEN * 30}, 2: {"text": SPOKEN * 30}}, nested=True)
        self.assertEqual(summary["stored"], 1)

    def test_a_call_missing_a_piece_is_not_stored_and_is_tried_again(self):
        summary, repository = self.assemble({1: {"text": SPOKEN * 60}})
        self.assertEqual((summary["stored"], summary["incomplete"]), (0, 1))
        self.assertEqual(repository.transcripts, [])
        self.assertEqual(repository.updates[0][1]["status"], "failed")
        self.assertEqual(repository.updates[0][1]["attempt_count"], 2)

    def test_a_recording_not_in_english_is_left_for_the_filed_transcript(self):
        summary, repository = self.assemble({1: {"text": SPOKEN * 30}, 2: {"text": SPOKEN * 30, "language": "hi"}})
        self.assertEqual(summary["rejected"], 1)
        self.assertEqual(repository.transcripts, [])
        self.assertEqual(repository.updates, [("filing-1", {"status": "rejected", "last_error": NOT_ENGLISH_ERROR})])

    def test_a_transcript_filed_while_the_pieces_ran_is_not_joined_by_the_recording(self):
        # Stored after the filed one, the recording's text would never be
        # removed and would read as that call's previous quarter.
        summary, repository = self.assemble(
            {1: {"text": SPOKEN * 30}, 2: {"text": SPOKEN * 30}}, has_transcript=True
        )
        self.assertEqual(summary["rejected"], 1)
        self.assertEqual(repository.transcripts, [])
        self.assertEqual(repository.asked, ("ALPHA", "2026-09-30"))
        self.assertEqual(repository.updates, [("filing-1", {"status": "rejected", "last_error": ALREADY_FILED_ERROR})])

    def test_a_recording_that_gave_almost_no_text_is_rejected(self):
        summary, repository = self.assemble({1: {"text": "Hello."}, 2: {"text": "Thank you."}})
        self.assertEqual(summary["rejected"], 1)
        self.assertEqual(repository.transcripts, [])


class SupersedeTests(unittest.TestCase):
    """The filed transcript replaces the one made from the recording."""

    RECORD = {
        "seq_id": "950",
        "symbol": "ALPHA",
        "sm_name": "Alpha Limited",
        "desc": "Earnings call transcript",
        "attchmntFile": "https://nsearchives.test/950.pdf",
        "an_dt": "2026-10-16T18:00:00",
    }

    def process(self, repository):
        worker = TranscriptWorker(repository, TranscriptSettings(min_text_characters=20, enable_ocr=False))
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "950.pdf"
            pdf.write_bytes(b"%PDF-1.7 filed transcript")
            extracted = type("Extraction", (), {"text": "Management: " + SPOKEN * 200, "method": "text"})()
            with (
                patch.object(worker, "_download_pdf", return_value=pdf),
                patch("workers.transcript_worker.extract_pdf_text", return_value=extracted),
            ):
                return worker._process_filing(self.RECORD, Path(directory))

    def test_storing_a_filed_transcript_removes_the_recording_transcript_of_that_quarter(self):
        repository = FakeRepository()
        self.assertTrue(self.process(repository))
        self.assertEqual(repository.deleted, [("ALPHA", "2026-09-30")])

    def test_a_failure_to_remove_it_does_not_fail_the_filed_transcript(self):
        repository = FakeRepository()
        repository.delete_speech_transcripts = lambda symbol, quarter: 1 / 0
        self.assertTrue(self.process(repository))
        self.assertEqual(repository.updates[-1][1]["status"], "document_ready")

    def test_a_read_only_run_removes_nothing(self):
        repository = FakeRepository()
        repository.read_only = True
        self.assertTrue(self.process(repository))
        self.assertEqual(repository.deleted, [])


if __name__ == "__main__":
    unittest.main()
