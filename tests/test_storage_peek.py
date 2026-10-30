import gzip
import unittest

from tools.storage_peek import readable, viewer_store


class StoragePeekTests(unittest.TestCase):
    def test_a_gzipped_object_is_read_as_text_and_plain_bytes_pass_through(self):
        self.assertEqual(readable(gzip.compress(b"{}")), b"{}")
        self.assertEqual(readable(b"plain"), b"plain")

    def test_the_viewer_store_carries_the_viewers_token_not_the_service_key(self):
        store = viewer_store("https://x.supabase.co", "anon", "user-token")
        self.assertEqual(store.headers["Authorization"], "Bearer user-token")
        self.assertTrue(store.read_only)
