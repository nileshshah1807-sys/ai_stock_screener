"""Finding a call's recording when its notice names no audio file."""

from __future__ import annotations

import io
import unittest
from datetime import date
from unittest.mock import patch

import requests

from transcripts.page_browser import RenderedPage, _press_audio_labels
from transcripts.recording_sources import (
    fiscal_quarter,
    further_pages,
    page_media,
    pick_by_upload_date,
    pick_call_file,
    shared_drive_download,
    source_from_notice,
)
from transcripts.recordings import _BARE_URL, DIRECT, NONE, PAGE, VIDEO, page_links

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


class FileHeaders:
    """What a site says about one file: when it was uploaded, how large it is, what it is."""

    def __init__(self, modified=None, size=6_000_000, content_type="audio/mpeg", status=200):
        self.status_code = status
        self.headers = {"Content-Length": str(size), "Content-Type": content_type}
        if modified:
            self.headers["Last-Modified"] = modified

    def close(self):
        pass


CALL_DAY = "Mon, 12 Oct 2026 14:30:00 GMT"
LAST_QUARTER = "Mon, 13 Jul 2026 14:30:00 GMT"
ANNOUNCED = date(2026, 10, 12)


class SiteSession:
    """A site: one page, and headers for each file it holds."""

    def __init__(self, page=None, files=None):
        self.page = page
        self.files = files or {}
        self.asked = []

    def get(self, url, **kwargs):
        if "Range" in kwargs.get("headers", {}):
            return self.files.get(url, FileHeaders(status=404))
        if isinstance(self.page, Exception):
            raise self.page
        return self.page

    def head(self, url, **kwargs):
        self.asked.append(url)
        return self.files.get(url, FileHeaders(status=404))


class UploadDateTests(unittest.TestCase):
    def pick(self, files):
        return pick_by_upload_date(list(files), ANNOUNCED, "https://alpha.test/investors", SiteSession(files=files))

    def test_the_one_audio_file_uploaded_for_this_call_is_taken_whatever_its_name(self):
        files = {
            "https://alpha.test/audio/10047244.mp3": FileHeaders(CALL_DAY),
            "https://alpha.test/audio/10041180.mp3": FileHeaders(LAST_QUARTER),
        }
        self.assertEqual(self.pick(files), "https://alpha.test/audio/10047244.mp3")

    def test_a_file_uploaded_a_few_days_before_the_notice_still_counts(self):
        self.assertIsNotNone(self.pick({"https://alpha.test/a.mp3": FileHeaders("Wed, 07 Oct 2026 09:00:00 GMT")}))
        self.assertIsNone(self.pick({"https://alpha.test/a.mp3": FileHeaders("Mon, 05 Oct 2026 09:00:00 GMT")}))

    def test_a_video_uploaded_that_day_is_not_a_recording(self):
        files = {"https://alpha.test/videos/about.mp4": FileHeaders(CALL_DAY, content_type="video/mp4")}
        self.assertIsNone(self.pick(files))

    def test_a_file_with_no_extension_counts_when_the_site_serves_it_as_audio(self):
        self.assertIsNotNone(self.pick({"https://alpha.test/downloads/call-october": FileHeaders(CALL_DAY)}))

    def test_a_clip_or_a_file_with_no_date_is_not_taken(self):
        self.assertIsNone(self.pick({"https://alpha.test/jingle.mp3": FileHeaders(CALL_DAY, size=300_000)}))
        self.assertIsNone(self.pick({"https://alpha.test/a.mp3": FileHeaders(None)}))

    def test_two_audio_files_uploaded_that_week_are_a_choice_that_is_not_made(self):
        files = {"https://alpha.test/a.mp3": FileHeaders(CALL_DAY), "https://alpha.test/b.mp3": FileHeaders(CALL_DAY)}
        self.assertIsNone(self.pick(files))

    def test_a_page_s_numbered_recording_is_found_by_its_upload_date(self):
        html = '<audio src="/audio/10047244.mp3"></audio><audio src="/audio/10041180.mp3"></audio>'
        session = SiteSession(
            FakeResponse(html),
            {
                "https://alpha.test/audio/10047244.mp3": FileHeaders(CALL_DAY),
                "https://alpha.test/audio/10041180.mp3": FileHeaders(LAST_QUARTER),
            },
        )
        source = source_from_notice(PAGE, "https://alpha.test/investors", Q2, session, announced=ANNOUNCED)
        self.assertEqual(source.url, "https://alpha.test/audio/10047244.mp3")
        self.assertIn("uploaded for this call", source.found)

    def test_without_the_notice_s_day_no_file_is_asked_about(self):
        session = SiteSession(FakeResponse('<audio src="/audio/10047244.mp3"></audio>'))
        self.assertIsNone(source_from_notice(PAGE, "https://alpha.test/investors", Q2, session))
        self.assertEqual(session.asked, [])


class BrowserTests(unittest.TestCase):
    RENDERED = RenderedPage(
        url="https://alpha.test/investors",
        html="<div id='player'></div>",
        media=["https://cdn.alpha.test/downloads/call-october"],
    )
    FILES = {"https://cdn.alpha.test/downloads/call-october": FileHeaders(CALL_DAY)}

    def resolve(self, page, browse=True, rendered=RENDERED):
        session = SiteSession(page, self.FILES)
        with patch("transcripts.recording_sources.render_page", return_value=rendered) as self.render:
            return source_from_notice(
                PAGE, "https://alpha.test/investors", Q2, session, announced=ANNOUNCED, browse=browse
            )

    def test_a_page_whose_player_is_built_by_a_script_yields_the_file_the_browser_saw_it_ask_for(self):
        source = self.resolve(FakeResponse("<div id='player'></div>"))
        self.assertEqual(source.url, "https://cdn.alpha.test/downloads/call-october")
        self.assertIn("rendered", source.found)

    def test_a_site_that_refuses_a_plain_request_is_opened_in_the_browser(self):
        self.assertIsNotNone(self.resolve(FakeResponse(status=403)))
        self.assertIsNotNone(self.resolve(requests.ConnectionError("refused")))

    def test_a_page_read_plainly_is_not_opened_again(self):
        html = '<a href="/ir/call_Q2_FY27.mp3">Q2</a>'
        self.assertEqual(self.resolve(FakeResponse(html)).url, "https://alpha.test/ir/call_Q2_FY27.mp3")
        self.render.assert_not_called()

    def test_no_browser_is_opened_unless_it_is_switched_on(self):
        self.assertIsNone(self.resolve(FakeResponse("<div></div>"), browse=False))
        self.render.assert_not_called()

    def test_a_page_the_browser_cannot_open_yields_nothing(self):
        self.assertIsNone(self.resolve(FakeResponse("<div></div>"), rendered=None))


class NoticeLinksTests(unittest.TestCase):
    def test_the_deepest_page_is_tried_first_and_the_home_page_last(self):
        links = [
            "http://www.alpha.test/",
            "https://www.alpha.test/investor-relations/disclosures/financial-highlights.",
            "https://www.alpha.test/",
            "https://www.alpha.test/investor-relations",
            "https://alpha.test/q2.mp3",
            "https://www.nseindia.com/",
        ]
        self.assertEqual(
            page_links(links),
            [
                "https://www.alpha.test/investor-relations/disclosures/financial-highlights",
                "https://www.alpha.test/investor-relations",
                "http://www.alpha.test/",
            ],
        )

    def test_an_address_printed_without_its_scheme_is_still_an_address(self):
        text = "available at www.alpha.test/investors/calls. Write to ir@www.alpha.test or see https://www.beta.test/x"
        self.assertEqual(_BARE_URL.findall(text), ["www.alpha.test/investors/calls."])

    def test_each_page_is_tried_until_one_holds_the_recording(self):
        pages = {
            "https://alpha.test/investors/calls": FakeResponse("<p>Nothing this quarter</p>"),
            "https://alpha.test/investors": FakeResponse('<a href="/ir/call_Q2_FY27.mp3">Q2</a>'),
            "https://alpha.test/": FakeResponse("<p>Welcome</p>"),
        }
        asked = []

        class Site:
            def get(self, url, **kwargs):
                asked.append(url)
                return pages[url]

        source = source_from_notice(PAGE, "https://alpha.test/", Q2, Site(), pages=list(pages))
        self.assertEqual(source.url, "https://alpha.test/ir/call_Q2_FY27.mp3")
        self.assertEqual(asked, ["https://alpha.test/investors/calls", "https://alpha.test/investors"])


class StaleFileTests(unittest.TestCase):
    def resolve(self, name, modified):
        link = f"https://alpha.test/ir/{name}"
        session = SiteSession(FakeResponse(f'<a href="{link}">call</a>'), {link: FileHeaders(modified)})
        return source_from_notice(PAGE, "https://alpha.test/investors", Q2, session, announced=ANNOUNCED)

    def test_a_file_named_for_this_quarter_is_believed_unless_the_site_says_it_is_old(self):
        self.assertIsNotNone(self.resolve("call_Q2_FY27.mp3", CALL_DAY))
        self.assertIsNotNone(self.resolve("call_Q2_FY27.mp3", None))
        self.assertIsNone(self.resolve("call_Q2_FY27.mp3", LAST_QUARTER))

    def test_a_file_with_only_a_call_s_name_needs_the_site_to_say_it_is_new(self):
        self.assertIsNotNone(self.resolve("earnings_call.mp3", CALL_DAY))
        self.assertIsNone(self.resolve("earnings_call.mp3", LAST_QUARTER))
        # No date at all: a name reused every quarter cannot be told from last quarter's.
        link = "https://alpha.test/ir/earnings_call.mp3"
        session = SiteSession(FakeResponse(f'<a href="{link}">call</a>'), {link: FileHeaders(None, content_type="text/html")})
        self.assertIsNone(source_from_notice(PAGE, "https://alpha.test/investors", Q2, session, announced=ANNOUNCED))

    def test_a_shared_file_on_a_home_page_is_not_taken(self):
        html = '<iframe src="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/preview"></iframe>'
        self.assertIsNone(source_from_notice(PAGE, "https://alpha.test/", Q2, SiteSession(FakeResponse(html))))
        self.assertIsNotNone(source_from_notice(PAGE, "https://alpha.test/investors", Q2, SiteSession(FakeResponse(html))))


class FurtherPageTests(unittest.TestCase):
    LINKS = [
        ("https://alpha.test/about", "About us"),
        ("https://alpha.test/investors", "Investors"),
        ("https://alpha.test/investors/earnings-call#q2", "Earnings call"),
        ("https://alpha.test/investors/financial-results", "Results"),
        ("https://other.test/investors", "Investors"),
        ("https://alpha.test/ir/call_Q1_FY27.mp3", "Earnings call audio"),
        ("https://alpha.test/", "Home"),
        ("mailto:investors@alpha.test", "Investor contact"),
    ]

    def test_the_site_s_own_investor_pages_are_offered_those_about_calls_first(self):
        self.assertEqual(
            further_pages(self.LINKS, "https://alpha.test/"),
            [
                "https://alpha.test/investors/earnings-call",
                "https://alpha.test/investors/financial-results",
                "https://alpha.test/investors",
            ],
        )

    def test_a_home_page_s_recording_is_found_one_link_further_in(self):
        home = RenderedPage("https://alpha.test/", "<p>Welcome</p>", [], [("https://alpha.test/investors/calls", "Con call")])
        calls = RenderedPage("https://alpha.test/investors/calls", "", ["https://alpha.test/ir/call_Q2_FY27.mp3"])
        opened = []

        def render(link, quarter_end=None):
            opened.append(link)
            return {"https://alpha.test/": home, "https://alpha.test/investors/calls": calls}.get(link)

        session = SiteSession(FakeResponse("<p>Welcome</p>"))
        with patch("transcripts.recording_sources.render_page", side_effect=render):
            source = source_from_notice(PAGE, "https://alpha.test/", Q2, session, browse=True)
        self.assertEqual(source.url, "https://alpha.test/ir/call_Q2_FY27.mp3")
        self.assertEqual(opened, ["https://alpha.test/", "https://alpha.test/investors/calls"])
        self.assertIn("linked from", source.found)


class FakeLabel:
    def __init__(self, text, log):
        self.text, self.log = text, log

    def inner_text(self, timeout=None):
        return self.text

    def click(self, timeout=None, force=False):
        self.log.append(self.text)


class FakePage:
    def __init__(self, texts):
        self.clicked = []
        self.labels = [FakeLabel(text, self.clicked) for text in texts]

    def get_by_text(self, pattern):
        page = self

        class Found:
            def count(self):
                return len(page.labels)

            def nth(self, index):
                return page.labels[index]

        return Found()

    def wait_for_timeout(self, milliseconds):
        pass


class ClickTests(unittest.TestCase):
    def test_what_is_labelled_as_this_call_s_audio_is_pressed_and_other_quarters_are_left(self):
        page = FakePage([
            "Earnings Audio Call Q2 FY 27",
            "Earnings Call Q1 Audio",
            "Audio recording",
            "The audio recording of the call held with analysts and investors is available below " * 2,
        ])
        _press_audio_labels(page, 2)
        self.assertEqual(page.clicked, ["Earnings Audio Call Q2 FY 27", "Audio recording"])

    def test_a_page_of_many_recordings_is_not_clicked_through(self):
        page = FakePage([f"Concall recording {index}" for index in range(30)])
        _press_audio_labels(page, 2)
        self.assertEqual(len(page.clicked), 6)


if __name__ == "__main__":
    unittest.main()
