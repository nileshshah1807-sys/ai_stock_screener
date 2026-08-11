"""Validation runs read shared transcript data but must never mutate it.

Blanking the credentials was the previous safeguard. That also blocked reads, so
the 2026-08-11 candidate run scored every row "Not configured" while the
baseline had 1,152 transcripts -- the comparison silently lost that axis.
"""

import unittest
from unittest.mock import patch

from storage.supabase_repository import (
    SupabaseReadOnlyError,
    SupabaseRepository,
)


class SupabaseReadOnlyTests(unittest.TestCase):
    def repository(self, read_only):
        return SupabaseRepository(
            "https://example.supabase.co", "service-role-key", 5, read_only=read_only
        )

    def test_read_only_blocks_every_mutating_verb(self):
        repository = self.repository(True)
        with patch.object(repository.session, "request") as request:
            for method in ("POST", "PATCH", "PUT", "DELETE"):
                with self.subTest(method=method):
                    with self.assertRaises(SupabaseReadOnlyError):
                        repository._request(method, "transcripts")
            request.assert_not_called()

    def test_read_only_allows_reads(self):
        repository = self.repository(True)
        with patch.object(repository.session, "request") as request:
            request.return_value.content = b"[]"
            request.return_value.json.return_value = []

            self.assertEqual(repository._request("GET", "transcripts"), [])
            request.assert_called_once()

    def test_writes_are_permitted_when_not_read_only(self):
        repository = self.repository(False)
        with patch.object(repository.session, "request") as request:
            request.return_value.content = b"[]"
            request.return_value.json.return_value = []

            self.assertEqual(repository._request("POST", "transcripts"), [])
            request.assert_called_once()

    def test_environment_flag_enables_read_only(self):
        environment = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
            "SUPABASE_READ_ONLY": "true",
        }
        with patch.dict("os.environ", environment, clear=False):
            self.assertTrue(SupabaseRepository.from_environment().read_only)

    def test_repository_defaults_to_writable(self):
        environment = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
            "SUPABASE_READ_ONLY": "",
        }
        with patch.dict("os.environ", environment, clear=False):
            self.assertFalse(SupabaseRepository.from_environment().read_only)


if __name__ == "__main__":
    unittest.main()
