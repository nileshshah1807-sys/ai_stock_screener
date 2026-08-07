import unittest

from transcripts.chunker import build_chunks
from transcripts.cleaner import clean_transcript_text
from transcripts.segmenter import segment_transcript


class TranscriptProcessingTests(unittest.TestCase):
    def test_cleaning_removes_pdf_noise_without_losing_financial_details(self):
        text = """Company Name\nPage 1 of 4\nSafe harbor statement: actual results may differ.\n
Revenue grew 18% to Rs 1,250 crore.\nCompany Name\nCompany Name\nCompany Name\n"""

        cleaned = clean_transcript_text(text)

        self.assertEqual(cleaned, "Revenue grew 18% to Rs 1,250 crore.")

    def test_cleaning_preserves_repeated_speaker_headings(self):
        speaker = "Jasbir S. Gujral - Managing Director, Syrma SGS Technology Limited"
        text = f"""Company Name
{speaker}
Opening remarks.
Company Name
{speaker}
First answer.
Company Name
{speaker}
Second answer.
"""

        cleaned = clean_transcript_text(text)

        self.assertEqual(cleaned.count(speaker), 3)
        self.assertNotIn("Company Name", cleaned)

    def test_segments_and_chunks_split_oversized_management_answer(self):
        answer = "We maintain our margin guidance and expect demand to improve. " * 20
        text = f"""Operator:\nWelcome to the earnings call.\n
Jane Analyst:\nWhat is your margin outlook?\n
Chief Financial Officer:\n{answer}\n"""

        segments = segment_transcript(text)
        chunks = build_chunks(segments, target_tokens=30, overlap_tokens=0)

        self.assertEqual([segment.section for segment in segments], ["prepared_remarks", "analyst_question", "management_answer"])
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(chunk.estimated_tokens <= 30 for chunk in chunks))
        management_text = " ".join(chunk.text for chunk in chunks if "management_answer" in chunk.text)
        self.assertIn("We maintain our margin guidance", management_text)

    def test_segments_stockscans_name_and_title_speaker_lines(self):
        text = """Jasbir S. Gujral - Managing Director, Syrma SGS Technology Limited
We expect to exceed what we have guided.
Nikhil Kandoi - Analyst, Axis Capital
What growth should we expect?
Jasbir S. Gujral - Managing Director, Syrma SGS Technology Limited
We expect 35% plus growth.
Operator
The next question follows.
"""

        segments = segment_transcript(text)

        self.assertEqual(
            [segment.role for segment in segments],
            ["management", "analyst", "management", "operator"],
        )
        self.assertEqual(
            [segment.section for segment in segments],
            ["prepared_remarks", "analyst_question", "management_answer", "closing"],
        )


if __name__ == "__main__":
    unittest.main()
