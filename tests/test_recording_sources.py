"""Finding a call's recording when its notice names no audio file."""

from __future__ import annotations

import io
import unittest
from datetime import date

import requests

from transcripts.recording_sources import (
    fiscal_quarter,
    page_media,
    pick_call_file,
    shared_drive_download,
    source_from_notice,
)
from transcripts.recordings import DIRECT, NONE, PAGE, VIDEO

Q2 = date(2026, 9, 30)


class QuarterTests(unittest.TestCase):
    def test_a_quarter_end_is_numbered_in_a_year_that_ends_in_march(self):
        self.assertEqual(fiscal_quarter(date(2026, 6, 30)), (1, 2027))
        self.assertEqual(fiscal_quarter(Q2), (2, 2027))
        self.assertEqual(fiscal_quarter(date(2026, 12, 31)), (3, 2027))
        self.assertEqual(fiscal_quarter(date(2027, 3, 31)), (4, 2027))


class SharedDriveTests(unittest.TestCase):
    def test_a_viewer_link_becomes_the_file_s_own_address(self):
        link = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/view?usp=sharing"
        self.assertEqual(
            shared_drive_download(link),
            "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOpQrStUvWx&export=download&confirm=t",
        )
        self.assertIn("id=1AbCdEfGhIjKlMnOpQrStUvWx", shared_drive_download(
            "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWx"
        ))

    def test_a_share_link_is_asked_for_the_download(self):
        self.assertEqual(
            shared_drive_download("https://alpha-my.sharepoint.com/:u:/g/personal/ir/Eabc?e=xyz"),
            "https://alpha-my.sharepoint.com/:u:/g/personal/ir/Eabc?e=xyz&download=1",
        )

    def test_a_folder_is_every_quarter_and_is_not_taken(self):
        self.assertIsNone(shared_drive_download("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWx"))
        self.assertIsNone(shared_drive_download("https://alpha.sharepoint.com/:f:/s/ir/Eabc?e=xyz"))
        self.assertIsNone(shared_drive_download("https://alpha.test/investors"))


class PickTests(unittest.TestCase):
    def test_the_one_file_that_names_this_quarter_is_taken(self):
        files = [
            "https://alpha.test/media/brand-film.mp4",
            "https://alpha.test/ir/Earnings_Call_Q1_FY27.mp3",
            "https://alpha.test/ir/Earnings_Call_Q2_FY27.mp3",
        ]
        self.assertEqual(pick_call_file(files, Q2), files[2])

    def test_the_quarter_is_read_however_the_year_is_written(self):
        for name in ("q2fy27-call.mp3", "Call-Q2-FY-2026-27.mp3", "audio_recording_Q2_26-27.mp4", "Q2%20FY2027.m4a"):
            self.assertEqual(pick_call_file([f"https://alpha.test/{name}"], Q2), f"https://alpha.test/{name}")

    def test_a_press_briefing_beside_the_analyst_call_is_left_aside(self):
        files = ["https://alpha.test/Audio_Analysts_Q2_FY27.mp3", "https://alpha.test/Audio_Media_Call_Q2_FY27.mp3"]
        self.assertEqual(pick_call_file(files, Q2), files[0])

    def test_two_recordings_of_this_quarter_are_a_choice_that_is_not_made(self):
        files = ["https://alpha.test/Q2_FY27_call_part1.mp3", "https://alpha.test/Q2_FY27_call_part2.mp3"]
        self.assertIsNone(pick_call_file(files, Q2))

    def test_a_lone_call_recording_that_names_no_quarter_is_taken(self):
        files = ["https://alpha.test/jingle.mp3", "https://alpha.test/Earnings-Call-Recording_12-October.mp3"]
        self.assertEqual(pick_call_file(files, Q2), files[1])

    def test_another_quarter_s_recording_is_never_taken(self):
        self.assertIsNone(pick_call_file(["https://alpha.test/Earnings_Call_Q1_FY27.mp3"], Q2))
        self.assertIsNone(pick_call_file(["https://alpha.test/Earnings_Call_Q2_FY26.mp3"], Q2))

    def test_promotional_clips_are_not_a_call(self):
        self.assertIsNone(pick_call_file(["https://alpha.test/banner.mp4", "https://alpha.test/10047244.mp3"], Q2))

    def test_media_is_found_in_markup_whether_absolute_or_relative(self):
        html = '<audio src="/files/q2fy27-call.mp3"></audio> <a href="https://cdn.alpha.test/a.MP4?x=1">watch</a>'
        self.assertEqual(
            page_media(html, "https://alpha.test/investors/"),
            ["https://alpha.test/files/q2fy27-call.mp3", "https://cdn.alpha.test/a.MP4?x=1"],
        )


class FakeResponse:
    def __init__(self, body="", content_type="text/html", status=200, url="https://alpha.test/investors"):
        self.raw = self
        self._body = io.BytesIO(body.encode())
        self.headers = {"Content-Type": content_type}
        self.status_code = status
        self.url = url

    def read(self, amount, decode_content=False):
        return self._body.read(amount)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, url, **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class NoticeLinkTests(unittest.TestCase):
    def resolve(self, response, kind=PAGE, link="https://alpha.test/investors"):
        return source_from_notice(kind, link, Q2, session=FakeSession(response))

    def test_a_direct_file_needs_no_looking(self):
        self.assertEqual(source_from_notice(DIRECT, "https://alpha.test/q2.mp3", Q2).url, "https://alpha.test/q2.mp3")

    def test_a_link_that_serves_a_file_is_that_file(self):
        source = self.resolve(FakeResponse(content_type="audio/mpeg", url="https://cdn.alpha.test/9f3"))
        self.assertEqual(source.url, "https://cdn.alpha.test/9f3")

    def test_a_page_yields_the_one_recording_of_this_quarter(self):
        html = '<a href="/ir/call_Q1_FY27.mp3">Q1</a><a href="/ir/call_Q2_FY27.mp3">Q2</a>'
        self.assertEqual(self.resolve(FakeResponse(html)).url, "https://alpha.test/ir/call_Q2_FY27.mp3")

    def test_a_page_built_around_one_shared_file_yields_it(self):
        html = '<iframe src="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/preview"></iframe>'
        self.assertIn("id=1AbCdEfGhIjKlMnOpQrStUvWx", self.resolve(FakeResponse(html)).url)

    def test_a_video_on_a_page_is_not_a_recording_this_job_can_fetch(self):
        html = '<iframe src="https://www.youtube.com/embed/abcdefghijk"></iframe>'
        self.assertIsNone(self.resolve(FakeResponse(html)))

    def test_a_page_that_refuses_or_fails_yields_nothing(self):
        self.assertIsNone(self.resolve(FakeResponse(status=403)))
        self.assertIsNone(self.resolve(requests.ConnectionError("offline")))
        self.assertIsNone(self.resolve(FakeResponse(content_type="application/pdf")))

    def test_a_shared_drive_link_is_downloaded_without_opening_its_page(self):
        source = source_from_notice(PAGE, "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/view", Q2)
        self.assertIn("drive.usercontent.google.com", source.url)

    def test_a_video_link_is_left_alone(self):
        self.assertIsNone(source_from_notice(VIDEO, "https://youtu.be/abcdefghijk", Q2))

    def test_no_link_is_nothing(self):
        self.assertIsNone(source_from_notice(NONE, None, Q2))


if __name__ == "__main__":
    unittest.main()
