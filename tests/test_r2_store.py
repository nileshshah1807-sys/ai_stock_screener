"""R2 client, the dual-write store, the backend switch and the copy tool."""

import hashlib
import os
import unittest
from unittest import mock

import requests

from storage.object_backend import DualStore, open_object_store
from storage.object_store import ObjectStore
from storage.r2_store import R2Store, sha256_hex, sigv4_signature
from tools.copy_objects_to_r2 import copy_prefix

NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'
R2_ENV = {
    "R2_ACCOUNT_ID": "acct", "R2_BUCKET": "market-data",
    "R2_ACCESS_KEY_ID": "AKID", "R2_SECRET_ACCESS_KEY": "secret",
}


def _response(status=200, body=b""):
    response = requests.Response()
    response.status_code = status
    response._content = body
    return response


class SigV4Tests(unittest.TestCase):
    def test_matches_the_aws_documented_get_object_example(self):
        # "Signature Calculations for the Authorization Header", GET /test.txt with a Range.
        empty = sha256_hex(b"")
        signature, signed = sigv4_signature(
            "GET", "/test.txt", "",
            {"host": "examplebucket.s3.amazonaws.com", "range": "bytes=0-9",
             "x-amz-content-sha256": empty, "x-amz-date": "20130524T000000Z"},
            empty, "20130524T000000Z", "us-east-1", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        self.assertEqual(signed, "host;range;x-amz-content-sha256;x-amz-date")
        self.assertEqual(signature, "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")


class R2StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = R2Store("acct", "market-data", "AKID", "secret")

    def send(self, *outcomes):
        patcher = mock.patch("storage.object_store.requests.request", side_effect=list(outcomes))
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_put_is_a_signed_path_style_put(self):
        request = self.send(_response())
        self.store.put("price-series/NSE/A B.json.gz", b"body")
        method, url = request.call_args.args
        self.assertEqual(method, "PUT")
        self.assertEqual(url, "https://acct.r2.cloudflarestorage.com/market-data/price-series/NSE/A%20B.json.gz")
        headers = request.call_args.kwargs["headers"]
        self.assertTrue(headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKID/"))
        self.assertEqual(headers["x-amz-content-sha256"], hashlib.sha256(b"body").hexdigest())
        self.assertEqual(request.call_args.kwargs["data"], b"body")

    def test_get_returns_none_for_a_missing_key_and_raises_on_other_errors(self):
        self.send(_response(404, b"<Error><Code>NoSuchKey</Code></Error>"), _response(403, b"denied"))
        self.assertIsNone(self.store.get("a"))
        with self.assertRaises(requests.HTTPError):
            self.store.get("a")

    def test_list_and_folders_read_every_page(self):
        page1 = (f'<ListBucketResult {NS}><IsTruncated>true</IsTruncated>'
                 '<Contents><Key>p/a.gz</Key><Size>3</Size></Contents>'
                 '<CommonPrefixes><Prefix>p/2026-11-10/</Prefix></CommonPrefixes>'
                 '<NextContinuationToken>tok 1</NextContinuationToken></ListBucketResult>')
        page2 = (f'<ListBucketResult {NS}><Contents><Key>p/b.gz</Key><Size>5</Size></Contents>'
                 '<CommonPrefixes><Prefix>p/2026-11-11/</Prefix></CommonPrefixes></ListBucketResult>')
        request = self.send(_response(body=page1.encode()), _response(body=page2.encode()))
        self.assertEqual(self.store.list("p"), ["p/a.gz", "p/b.gz"])
        urls = [call.args[1] for call in request.call_args_list]
        self.assertIn("prefix=p%2F", urls[0])
        self.assertIn("continuation-token=tok%201", urls[1])
        self.send(_response(body=page2.encode()))
        self.assertEqual(self.store.folders("p"), ["2026-11-11"])

    def test_sizes_lists_without_a_delimiter(self):
        body = f'<ListBucketResult {NS}><Contents><Key>p/x/a.gz</Key><Size>7</Size></Contents></ListBucketResult>'
        request = self.send(_response(body=body.encode()))
        self.assertEqual(self.store.sizes("p"), {"p/x/a.gz": 7})
        self.assertNotIn("delimiter", request.call_args.args[1])

    def test_remove_sends_one_delete_request_per_batch_with_a_md5(self):
        request = self.send(_response(body=b"<DeleteResult/>"))
        self.assertEqual(self.store.remove(["a&b", "c"]), 2)
        self.assertEqual(request.call_args.args[0], "POST")
        self.assertTrue(request.call_args.args[1].endswith("/market-data?delete="))
        self.assertIn(b"<Key>a&amp;b</Key>", request.call_args.kwargs["data"])
        self.assertIn("content-md5", request.call_args.kwargs["headers"])

    def test_remove_raises_when_a_200_reports_a_failed_key(self):
        self.send(_response(body=b"<DeleteResult><Error><Key>a</Key></Error></DeleteResult>"))
        with self.assertRaises(requests.HTTPError):
            self.store.remove(["a"])

    def test_read_only_refuses_writes(self):
        store = R2Store("acct", "b", "k", "s", read_only=True)
        with self.assertRaises(PermissionError):
            store.put("a", b"x")
        with self.assertRaises(PermissionError):
            store.remove(["a"])

    def test_gzip_text_round_trips(self):
        stored = {}
        self.store.put = lambda path, body, content_type="": stored.update({path: body})
        self.store.get = stored.get
        self.store.put_gzip_text("t", "héllo")
        self.assertEqual(self.store.get_gzip_text("t"), "héllo")


class DualStoreTests(unittest.TestCase):
    def setUp(self):
        self.primary = mock.Mock(spec=ObjectStore)
        self.secondary = mock.Mock(spec=R2Store)
        self.dual = DualStore(self.primary, self.secondary)

    def test_put_writes_both_and_times_them(self):
        self.dual.put("a", b"x")
        self.primary.put.assert_called_once_with("a", b"x", "application/gzip")
        self.secondary.put.assert_called_once_with("a", b"x", "application/gzip")
        self.assertEqual(self.dual.puts, 1)
        self.assertGreaterEqual(self.dual.seconds["r2"], 0)

    def test_an_r2_failure_is_counted_not_raised(self):
        self.secondary.put.side_effect = requests.ConnectionError("down")
        self.dual.put("a", b"x")
        self.assertEqual(self.dual.r2_failures, 1)

    def test_a_supabase_failure_stops_before_r2(self):
        self.primary.put.side_effect = requests.HTTPError("403")
        with self.assertRaises(requests.HTTPError):
            self.dual.put("a", b"x")
        self.secondary.put.assert_not_called()

    def test_reads_come_from_supabase_and_removes_go_to_both(self):
        self.primary.get.return_value = b"p"
        self.primary.remove.return_value = 2
        self.assertEqual(self.dual.get("a"), b"p")
        self.assertEqual(self.dual.remove(iter(["a", "b"])), 2)
        self.secondary.remove.assert_called_once_with(["a", "b"])
        self.secondary.get.assert_not_called()


class BackendSwitchTests(unittest.TestCase):
    def open(self, **env):
        with mock.patch.dict(os.environ, env, clear=True):
            return open_object_store("https://x.test", "key")

    def test_unset_and_empty_mean_supabase(self):
        # A workflow passes an unset repository variable as "".
        self.assertIsInstance(self.open(), ObjectStore)
        self.assertIsInstance(self.open(OBJECT_STORE_BACKEND=""), ObjectStore)

    def test_dual_and_r2(self):
        self.assertIsInstance(self.open(OBJECT_STORE_BACKEND="dual", **R2_ENV), DualStore)
        self.assertIsInstance(self.open(OBJECT_STORE_BACKEND="r2", **R2_ENV), R2Store)

    def test_a_missing_r2_key_names_itself(self):
        env = {**R2_ENV, "R2_BUCKET": ""}
        with self.assertRaisesRegex(ValueError, "R2_BUCKET"):
            self.open(OBJECT_STORE_BACKEND="dual", **env)

    def test_an_unknown_backend_is_refused(self):
        with self.assertRaises(ValueError):
            self.open(OBJECT_STORE_BACKEND="s3")


class CopyToolTests(unittest.TestCase):
    def setUp(self):
        self.source = mock.Mock(spec=ObjectStore)
        folders = {"snap": ["d1"], "snap/d1": []}
        files = {"snap": [], "snap/d1": ["snap/d1/a", "snap/d1/b"]}
        self.source.folders.side_effect = lambda p: folders[p]
        self.source.list.side_effect = lambda p: files[p]
        self.source.get.side_effect = lambda k: {"snap/d1/a": b"aaa", "snap/d1/b": b"bb"}[k]
        self.target = mock.Mock(spec=R2Store)
        self.target.sizes.return_value = {"snap/d1/b": 9}  # b is there, wrong size

    def test_dry_run_counts_and_writes_nothing(self):
        counts = copy_prefix(self.source, self.target, "snap", apply=False)
        self.assertEqual((counts["seen"], counts["missing"], counts["copied"]), (2, 1, 0))
        self.target.put.assert_not_called()
        self.source.get.assert_not_called()

    def test_apply_copies_missing_and_different_sizes(self):
        counts = copy_prefix(self.source, self.target, "snap", apply=True)
        self.assertEqual((counts["copied"], counts["differs"], counts["bytes"]), (2, 1, 5))
        self.assertEqual(self.target.put.call_count, 2)

    def test_apply_skips_what_r2_already_holds(self):
        self.target.sizes.return_value = {"snap/d1/a": 3, "snap/d1/b": 2}
        self.assertEqual(copy_prefix(self.source, self.target, "snap", apply=True)["copied"], 0)
