import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from tools.backfill_xbrl import Downloader, document_path, run_status


def response(status, content=b"", content_type="application/xml"):
    value = Mock()
    value.status_code = status
    value.content = content
    value.headers = {"Content-Type": content_type}
    return value


class DownloaderTests(unittest.TestCase):
    def test_does_not_retry_permanent_404(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = Downloader(directory, retries=3)
            session = Mock()
            session.get.return_value = response(404, b"missing", "text/html")
            downloader._session = Mock(return_value=session)

            result = downloader.fetch_one(
                "https://example.test/missing.xml",
                Path(directory) / "xbrl" / "2024" / "1.xml.gz",
            )

            self.assertEqual(result, "failed")
            self.assertEqual(session.get.call_count, 1)
            self.assertEqual(downloader.failure_summary(), "HTTP 404=1")

    @patch("tools.backfill_xbrl.time.sleep", return_value=None)
    def test_retries_transient_response_and_caches_xml(self, _sleep):
        with tempfile.TemporaryDirectory() as directory:
            downloader = Downloader(directory, retries=2)
            session = Mock()
            session.get.side_effect = [
                response(503, b"unavailable", "text/html"),
                response(200, b"<?xml version='1.0'?><xbrl/>")
            ]
            downloader._session = Mock(return_value=session)
            target = Path(directory) / "xbrl" / "2024" / "1.xml.gz"

            result = downloader.fetch_one("https://example.test/1.xml", target)

            self.assertEqual(result, "fetched")
            self.assertEqual(session.get.call_count, 2)
            with gzip.open(target, "rb") as handle:
                self.assertEqual(handle.read(), b"<?xml version='1.0'?><xbrl/>")

    def test_rejects_html_disguised_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = Downloader(directory, retries=1)
            session = Mock()
            session.get.return_value = response(
                200, b"<!doctype html><title>blocked</title>", "text/html"
            )
            downloader._session = Mock(return_value=session)
            target = Path(directory) / "xbrl" / "2024" / "1.xml.gz"

            result = downloader.fetch_one("https://example.test/1.xml", target)

            self.assertEqual(result, "failed")
            self.assertFalse(target.exists())
            self.assertEqual(
                downloader.failure_summary(),
                "HTTP 200 returned HTML/non-document content=1",
            )


class StatusTests(unittest.TestCase):
    def test_counts_only_files_belonging_to_current_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame(
                [
                    {
                        "ISIN": "INE000000001",
                        "Seq_Number": "1",
                        "Period_End": "2024-03-31",
                        "XBRL_URL": "https://example.test/1.xml",
                        "Is_Ind_AS": True,
                    }
                ]
            ).to_csv(root / "filings_annual.csv", index=False)
            target = document_path(root, "1", "2024-03-31")
            target.parent.mkdir(parents=True)
            with gzip.open(target, "wb") as handle:
                handle.write(b"<xbrl/>")
            unrelated = document_path(root, "old", "2020-03-31")
            unrelated.parent.mkdir(parents=True)
            with gzip.open(unrelated, "wb") as handle:
                handle.write(b"<xbrl/>")

            with patch("builtins.print") as print_mock:
                run_status(root)

            lines = [call.args[0] for call in print_mock.call_args_list]
            self.assertIn("documents cached   : 1", lines)
            self.assertIn("remaining          : 0", lines)


if __name__ == "__main__":
    unittest.main()
