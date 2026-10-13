"""A vendor's transcript of a call, and its removal when the company files its own."""

from __future__ import annotations

import unittest
from datetime import date

import requests

from storage.supabase_repository import SupabaseRepository
from transcripts.recordings import is_provisional
from transcripts.vendor_transcripts import (
    USER_AGENT,
    fetch_transcript,
    find_transcript,
    list_transcripts,
    page_text,
    vendor_name,
)

Q2 = date(2026, 9, 30)
BASE = "https://vendor.test/india"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(str(self.status))

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def row(identifier, title):
    return {"id": identifier, "title": {"rendered": title}, "link": f"{BASE}/{identifier}/"}


class ListingTests(unittest.TestCase):
    def test_the_listing_is_read_from_the_site_s_public_api_under_our_own_name(self):
        session = FakeSession(FakeResponse([row(1, "Alpha &amp; Co Ltd (ALPHA) Q2 2027 Earnings Call Transcript")]))
        listing = list_transcripts(BASE, session)
        self.assertEqual(
            listing,
            [{"id": 1, "title": "Alpha & Co Ltd (ALPHA) Q2 2027 Earnings Call Transcript", "link": f"{BASE}/1/"}],
        )
        url, kwargs = session.calls[0]
        self.assertEqual(url, f"{BASE}/wp-json/wp/v2/transcript")
        self.assertEqual(kwargs["headers"], {"User-Agent": USER_AGENT})
        self.assertNotIn("Mozilla", USER_AGENT)

    def test_a_full_page_is_followed_by_the_next(self):
        full = [row(index, "x") for index in range(100)]
        session = FakeSession(FakeResponse(full), FakeResponse([row(100, "y")]))
        self.assertEqual(len(list_transcripts(BASE, session)), 101)
        self.assertEqual([kwargs["params"]["page"] for _, kwargs in session.calls], [1, 2])

    def test_a_site_that_cannot_be_listed_is_an_empty_listing(self):
        for failure in (requests.ConnectionError("offline"), FakeResponse([], status=503), FakeResponse(ValueError("html"))):
            self.assertEqual(list_transcripts(BASE, FakeSession(failure)), [])


class MatchTests(unittest.TestCase):
    LISTING = [
        {"id": 1, "title": "Alpha Ltd (ALPHA) Q2 2027 Earnings Call Transcript"},
        {"id": 2, "title": "Alpha Ltd (ALPHA) Q1 2027 Earnings Call Transcript"},
        {"id": 3, "title": "Alpha Ltd (ALPHA) Q2 2026 Earnings Call Transcript"},
        {"id": 4, "title": "Alphabet Ltd (ALPHAB) Q2 2027 Earnings Call Transcript"},
        {"id": 5, "title": "Beta & Co Ltd (BETA-M&M) Q2 2027 Earnings Call Transcript"},
        {"id": 6, "title": "Markets close higher"},
    ]

    def test_a_transcript_is_matched_on_symbol_and_quarter(self):
        self.assertEqual(find_transcript(self.LISTING, "ALPHA", Q2)["id"], 1)
        self.assertEqual(find_transcript(self.LISTING, "alpha", date(2026, 6, 30))["id"], 2)
        self.assertEqual(find_transcript(self.LISTING, "BETA-M&M", Q2)["id"], 5)

    def test_a_longer_symbol_another_quarter_or_another_year_is_not_a_match(self):
        self.assertIsNone(find_transcript(self.LISTING, "ALPH", Q2))
        self.assertIsNone(find_transcript(self.LISTING, "ALPHA", date(2026, 12, 31)))
        self.assertIsNone(find_transcript(self.LISTING, "GAMMA", Q2))

    def test_two_transcripts_of_one_call_are_a_choice_that_is_not_made(self):
        twice = [*self.LISTING, {"id": 9, "title": "Alpha Limited (ALPHA) Q2 2027 Earnings Call Transcript"}]
        self.assertIsNone(find_transcript(twice, "ALPHA", Q2))


class TextTests(unittest.TestCase):
    def test_markup_becomes_one_paragraph_or_speaker_to_a_line(self):
        markup = (
            "<h2>Presentation:</h2><p><strong>A Speaker</strong> — <em>Chief Executive</em></p>"
            "<p>Revenue grew 12%&nbsp;&amp; margins held.<br>Thank you.</p><script>track()</script>"
        )
        self.assertEqual(
            page_text(markup),
            "Presentation:\nA Speaker — Chief Executive\nRevenue grew 12% & margins held.\nThank you.",
        )

    def test_a_transcript_s_text_is_fetched_by_its_id(self):
        session = FakeSession(FakeResponse({"content": {"rendered": "<p>Good evening.</p>", "protected": False}}))
        self.assertEqual(fetch_transcript(BASE, {"id": 7}, session), "Good evening.")
        self.assertEqual(session.calls[0][0], f"{BASE}/wp-json/wp/v2/transcript/7")

    def test_a_protected_or_unreadable_transcript_is_nothing(self):
        protected = FakeResponse({"content": {"rendered": "", "protected": True}})
        for response in (protected, FakeResponse({}, status=404), requests.Timeout("slow")):
            self.assertIsNone(fetch_transcript(BASE, {"id": 7}, FakeSession(response)))

    def test_the_vendor_is_named_by_its_host(self):
        self.assertEqual(vendor_name("https://www.vendor.test/india"), "vendor.test")


class ProvisionalTests(unittest.TestCase):
    def test_a_recording_s_text_and_a_vendor_s_are_provisional_and_a_filed_one_is_not(self):
        self.assertTrue(is_provisional("speech:large-v3-turbo"))
        self.assertTrue(is_provisional("vendor:vendor.test"))
        self.assertFalse(is_provisional("text"))
        self.assertFalse(is_provisional(None))

    def test_a_filed_transcript_removes_both_kinds_and_keeps_filed_ones(self):
        repository = SupabaseRepository("https://example.test", "service-role-key")
        rows = [
            {"id": "t1", "transcript_documents": {"extraction_method": "speech:large-v3-turbo"}},
            {"id": "t2", "transcript_documents": {"extraction_method": "vendor:vendor.test"}},
            {"id": "t3", "transcript_documents": {"extraction_method": "text"}},
            {"id": "t4", "transcript_documents": [{"extraction_method": "vendor:vendor.test"}]},
        ]
        deleted = []
        repository._request = lambda method, path, **kwargs: rows
        repository.delete_transcript = deleted.append
        self.assertEqual(repository.delete_speech_transcripts("ALPHA", "2026-09-30"), 3)
        self.assertEqual(deleted, ["t1", "t2", "t4"])


if __name__ == "__main__":
    unittest.main()
