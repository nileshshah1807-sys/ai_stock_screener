import tempfile
import unittest
from pathlib import Path

from workers.live_dialin import SAMPLE_RATE, WAV_HEADER_BYTES, Join, tail_chunks, until_joined, watch_transcribe


class TailChunksTests(unittest.TestCase):
    def test_reads_whole_chunks_after_the_header_and_stops_when_idle(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "call.wav"
            # 2.5 s of samples: two 1 s chunks, then 0.5 s that never fills a chunk
            path.write_bytes(b"\0" * WAV_HEADER_BYTES + b"\x00\x40" * int(2.5 * SAMPLE_RATE))
            now = [0.0]

            def sleep(seconds):
                now[0] += seconds

            got = list(tail_chunks(path, chunk_seconds=1, idle_seconds=3, sleep=sleep, clock=lambda: now[0]))
        self.assertEqual([start for start, _ in got], [0.0, 1.0])
        self.assertTrue(all(len(samples) == SAMPLE_RATE for _, samples in got))
        self.assertAlmostEqual(float(got[0][1][0]), 0.5, places=3)  # 0x4000 / 32768


class JoinTests(unittest.TestCase):
    chunks = [(0.0, 0), (60.0, 1), (90.0, 2), (120.0, 3)]

    def test_gives_up_at_the_deadline_when_the_conference_never_starts(self):
        join = Join()
        got = list(until_joined(iter(self.chunks), join, deadline=90))
        self.assertEqual([s for s, _ in got], [0.0, 60.0])
        self.assertIn("90 s", join.gave_up)

    def test_stays_on_once_the_moderator_has_opened_the_call(self):
        join = Join()
        said = watch_transcribe(lambda s: [(0.0, "Ladies and gentlemen, good day and welcome")] if s == 1 else [], join)
        out = []
        for start, samples in until_joined(iter(self.chunks), join, deadline=90):
            said(samples)
            out.append(start)
        self.assertEqual(out, [0.0, 60.0, 90.0, 120.0])
        self.assertIsNone(join.gave_up)


if __name__ == "__main__":
    unittest.main()
