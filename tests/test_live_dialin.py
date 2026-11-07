import tempfile
import unittest
from pathlib import Path

from workers.live_dialin import SAMPLE_RATE, WAV_HEADER_BYTES, tail_chunks


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


if __name__ == "__main__":
    unittest.main()
