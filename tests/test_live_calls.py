import io
import tempfile
import unittest
import wave
from datetime import date
from pathlib import Path

from workers.live_calls import SAMPLE_RATE, call_id, listen, pcm_chunks, read_exactly


class FakeRepo:
    def __init__(self):
        self.calls, self.lines = [], []

    def upsert_live_call(self, row):
        self.calls.append(row)

    def append_live_lines(self, rows):
        self.lines.extend(rows)


class ListenTests(unittest.TestCase):
    def test_lines_are_numbered_across_chunks_and_call_ends(self):
        repo = FakeRepo()
        said = {0.0: [(0.5, "Good morning"), (3.0, "revenue grew")], 8.0: [], 16.0: [(1.0, "thank you")]}
        n = listen(
            repo, call="NSE:ABC:2026-11-07", symbol="abc", source="x.mp3",
            chunks=[(s, s) for s in said], transcribe=lambda s: said[s],
        )
        self.assertEqual(n, 3)
        self.assertEqual([(r["seq"], r["start_seconds"]) for r in repo.lines], [(1, 0.5), (2, 3.0), (3, 17.0)])
        self.assertEqual([c["state"] for c in repo.calls], ["live", "ended"])

    def test_call_ends_when_transcription_fails(self):
        repo = FakeRepo()

        def boom(_):
            raise RuntimeError("model died")

        with self.assertRaises(RuntimeError):
            listen(repo, call="c", symbol="a", source="s", chunks=[(0.0, 0)], transcribe=boom)
        self.assertEqual(repo.calls[-1]["state"], "ended")

    def test_call_id(self):
        self.assertEqual(call_id("NSE", "abc", date(2026, 11, 7)), "NSE:ABC:2026-11-07")


class ChunkTests(unittest.TestCase):
    def test_read_exactly_joins_short_reads(self):
        class Slow(io.BytesIO):
            def read(self, n=-1):
                return super().read(min(n, 3))

        self.assertEqual(read_exactly(Slow(b"abcdefgh"), 7), b"abcdefg")
        self.assertEqual(read_exactly(Slow(b"ab"), 7), b"ab")

    def test_pcm_chunks_cuts_a_file_by_seconds(self):
        try:
            from transcripts.recordings import ffmpeg_executable

            ffmpeg_executable()
        except Exception:
            self.skipTest("no ffmpeg")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tone.wav"
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(SAMPLE_RATE)
                out.writeframes(b"\x10\x00" * SAMPLE_RATE * 5)  # 5 s
            got = list(pcm_chunks(str(path), chunk_seconds=2))
        self.assertEqual([round(s, 1) for s, _ in got], [0.0, 2.0, 4.0])
        self.assertAlmostEqual(len(got[-1][1]) / SAMPLE_RATE, 1.0, places=1)


if __name__ == "__main__":
    unittest.main()
