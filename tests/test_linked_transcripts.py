import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pymupdf

from transcripts import linked
from transcripts.linked import (
    candidate_links,
    dates_in,
    fetch_linked_transcript,
    held_near,
    is_cover_letter,
    looks_like_call_transcript,
    pdf_links_on_page,
)

LETTER = (
    "Sub: Transcript of investors' call\nDear Sir,\nThe transcript of the call held on "
    "31st July 2026 is available on the below link.\n"
)
# Numbered, because the cleaner drops a line repeated down the document as a
# page header.
TURN = (
    "Moderator: Question {n} is from the line of an analyst.\n"
    "Analyst: On point {n}, how do you see demand over the rest of the year?\n"
    "Management: On point {n}, demand remains healthy and volumes keep growing.\n"
)


def call_text(held="31 July 2026"):
    return f"Q1 FY27 Earnings Conference Call\n{held}\n" + "".join(TURN.format(n=n) for n in range(60))


def pdf_bytes(text, uri=None):
    document = pymupdf.open()
    lines = text.split("\n")
    for start in range(0, len(lines), 40):
        page = document.new_page()
        page.insert_text((50, 60), "\n".join(lines[start:start + 40]), fontsize=9)
        if uri and start == 0:
            page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(50, 50, 300, 70), "uri": uri})
    data = document.tobytes()
    document.close()
    return data


class Response:
    def __init__(self, body=b"", status=200, location=None):
        self.body, self.status_code = body, status
        self.headers = {"location": location} if location else {}
        self.is_redirect = location is not None

    def iter_content(self, size):
        yield self.body

    def close(self):
        pass


class Session:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def get(self, url, **kwargs):
        self.requested.append(url)
        return self.pages.get(url, Response(status=404))


class RecognitionTests(unittest.TestCase):
    def test_a_letter_is_short_and_a_call_is_people_taking_turns(self):
        self.assertTrue(is_cover_letter(LETTER))
        self.assertFalse(is_cover_letter(call_text()))
        self.assertTrue(looks_like_call_transcript(call_text()))

    def test_a_long_document_that_is_not_a_call_is_refused(self):
        presentation = "".join(f"Slide {n}: revenue grew 18% year on year.\\n" for n in range(400))
        self.assertFalse(is_cover_letter(presentation))
        self.assertFalse(looks_like_call_transcript(presentation))

    def test_dates_are_read_in_the_forms_filings_use(self):
        text = "held on 31st July 2026, filed August 6, 2026; ref 05/08/2026 and 13-Aug-2026"
        self.assertEqual(
            dates_in(text),
            [date(2026, 7, 31), date(2026, 8, 6), date(2026, 8, 5), date(2026, 8, 13)],
        )
        self.assertEqual(dates_in("31 February 2026"), [])

    def test_a_call_must_be_dated_just_before_the_filing(self):
        filed = date(2026, 8, 6)
        self.assertTrue(held_near(call_text("31 July 2026"), filed))
        # Last quarter's transcript, on the same investor page.
        self.assertFalse(held_near(call_text("5 May 2026"), filed))
        self.assertFalse(held_near(call_text("31 July 2026"), None))


class LinkTests(unittest.TestCase):
    def letter(self, directory, text=LETTER, uri=None):
        path = Path(directory) / "letter.pdf"
        path.write_bytes(pdf_bytes(text, uri))
        return path

    def test_the_transcript_file_is_tried_before_the_home_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.letter(
                directory,
                LETTER + "Website: www.example.test\nhttps://example.test/files/Q1-transcript.pdf\n",
            )
            self.assertEqual(
                candidate_links(path),
                ["https://example.test/files/Q1-transcript.pdf", "https://www.example.test"],
            )

    def test_a_hyperlink_behind_the_text_is_found(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.letter(directory, LETTER + "Link: Conference Call July 2026.pdf\n",
                               uri="https://example.test/docs/call.pdf")
            self.assertEqual(candidate_links(path), ["https://example.test/docs/call.pdf"])

    def test_a_url_broken_across_two_lines_is_rejoined(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.letter(
                directory, LETTER + "https://example.test/wp-content/uploads/2026/08/Earning-call-\nTranscript-Q1.pdf\n"
            )
            self.assertEqual(
                candidate_links(path),
                ["https://example.test/wp-content/uploads/2026/08/Earning-call-Transcript-Q1.pdf"],
            )

    def test_only_transcript_pdfs_are_taken_from_an_investor_page(self):
        html = """
            <a href="/files/annual-report.pdf">Annual Report</a>
            <a href="/files/q1.pdf"><span>Earnings Call Transcript</span></a>
            <a href='docs/concall_q4.pdf'>Q4</a>
            <a href="/investors">Investors</a>
        """
        self.assertEqual(
            pdf_links_on_page(html, "https://example.test/ir/"),
            ["https://example.test/files/q1.pdf", "https://example.test/ir/docs/concall_q4.pdf"],
        )

    def test_private_and_loopback_addresses_are_not_fetched(self):
        for url in ("http://127.0.0.1/x.pdf", "http://169.254.169.254/latest", "http://10.0.0.5/a", "http://localhost/a"):
            self.assertFalse(linked._is_public_host(url), url)


class FetchTests(unittest.TestCase):
    def fetch(self, letter_text, pages, uri=None, filed=date(2026, 8, 6)):
        session = Session(pages)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            linked, "_is_public_host", lambda url: "internal" not in url
        ):
            path = Path(directory) / "letter.pdf"
            path.write_bytes(pdf_bytes(letter_text, uri))
            found = fetch_linked_transcript(
                path, Path(directory), filed, min_characters=1000, enable_ocr=False, max_pages=120, session=session
            )
        return found, session

    def test_a_direct_link_gives_the_call(self):
        url = "https://example.test/q1-transcript.pdf"
        found, _ = self.fetch(LETTER + url + "\n", {url: Response(pdf_bytes(call_text()))})

        extraction, source = found
        self.assertEqual(source, url)
        self.assertEqual(extraction.method, "linked-pymupdf")
        self.assertIn("demand remains healthy", extraction.text)

    def test_an_investor_page_is_followed_one_hop_to_this_quarters_call(self):
        page = "https://example.test/investors"
        html = b'<a href="/q4-transcript.pdf">Q4</a><a href="/q1-transcript.pdf">Q1</a>'
        found, session = self.fetch(LETTER + page + "\n", {
            page: Response(html),
            "https://example.test/q4-transcript.pdf": Response(pdf_bytes(call_text("5 May 2026"))),
            "https://example.test/q1-transcript.pdf": Response(pdf_bytes(call_text("31 July 2026"))),
        })

        self.assertEqual(found[1], "https://example.test/q1-transcript.pdf")
        self.assertIn("https://example.test/q4-transcript.pdf", session.requested)

    def test_the_call_date_is_found_even_where_it_is_a_page_header(self):
        # Printed on every page, so the cleaner drops it from the stored text.
        url = "https://example.test/q1-transcript.pdf"
        lines = call_text().split("\n")[2:]
        paged = "\n".join(
            "Example Limited\nJuly 31, 2026\n" + "\n".join(lines[start:start + 38])
            for start in range(0, len(lines), 38)
        )
        found, _ = self.fetch(LETTER + url + "\n", {url: Response(pdf_bytes(paged))})

        self.assertIsNotNone(found)
        self.assertNotIn("July 31, 2026", found[0].text)

    def test_a_linked_presentation_is_not_taken_for_the_call(self):
        url = "https://example.test/Investor_Presentation.pdf"
        deck = "Q1 FY27 results, 31 July 2026\n" + "Revenue grew 18% year on year.\n" * 600
        found, _ = self.fetch(LETTER + url + "\n", {url: Response(pdf_bytes(deck))})

        self.assertIsNone(found)

    def test_a_redirect_to_a_private_address_is_not_followed(self):
        url = "https://example.test/transcript.pdf"
        found, session = self.fetch(LETTER + url + "\n", {
            url: Response(location="http://internal.example/secret.pdf"),
            "http://internal.example/secret.pdf": Response(pdf_bytes(call_text())),
        })

        self.assertIsNone(found)
        self.assertEqual(session.requested, [url])

    def test_a_letter_with_no_link_gives_nothing(self):
        found, session = self.fetch(LETTER, {})

        self.assertIsNone(found)
        self.assertEqual(session.requested, [])


if __name__ == "__main__":
    unittest.main()
