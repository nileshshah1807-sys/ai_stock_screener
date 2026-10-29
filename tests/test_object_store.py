"""Transient-failure handling in the Supabase Storage client."""

import json
import unittest
from unittest import mock

import requests

from storage.object_store import ObjectStore


def _response(status=200, body=b"ok"):
    response = requests.Response()
    response.status_code = status
    response._content = body
    return response


class TransferRetryTests(unittest.TestCase):
    """The NSE chart publish of 30 Sept 2026 died on one read timeout."""

    def setUp(self):
        self.store = ObjectStore("https://x.test", "key")

    def send(self, *outcomes):
        patcher = mock.patch(
            "storage.object_store.requests.request", side_effect=list(outcomes)
        )
        self.addCleanup(patcher.stop)
        sleeper = mock.patch("storage.object_store.time.sleep")
        self.addCleanup(sleeper.stop)
        self.sleep = sleeper.start()
        return patcher.start()

    def test_put_survives_a_transient_timeout(self):
        request = self.send(requests.ReadTimeout("read timed out"), _response())
        self.store.put("NSE/TCS.json.gz", b"body")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.args[0], "POST")
        self.assertEqual(request.call_args.kwargs["headers"]["x-upsert"], "true")
        self.sleep.assert_called_once_with(5)

    def test_get_survives_a_dropped_connection(self):
        self.send(requests.ConnectionError("reset"), _response(body=b"payload"))
        self.assertEqual(self.store.get("NSE/TCS.json.gz"), b"payload")

    def test_gives_up_after_the_last_retry(self):
        request = self.send(*[requests.ConnectionError("down")] * 4)
        with self.assertRaises(requests.ConnectionError):
            self.store.put("NSE/TCS.json.gz", b"body")
        self.assertEqual(request.call_count, 4)

    def test_an_http_error_is_not_retried(self):
        request = self.send(_response(status=403, body=b"denied"))
        with self.assertRaises(requests.HTTPError):
            self.store.put("NSE/TCS.json.gz", b"body")
        self.assertEqual(request.call_count, 1)



def _listing(*entries):
    """A Storage list response: files carry an id, folders do not."""
    response = _response()
    response._content = json.dumps(
        [{"name": name, "id": None if folder else "id"} for name, folder in entries]
    ).encode()
    return response


class ListAndRemoveTests(unittest.TestCase):
    def setUp(self):
        self.store = ObjectStore("https://x.test", "key")

    def send(self, *outcomes):
        patcher = mock.patch("storage.object_store.requests.request", side_effect=list(outcomes))
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_list_returns_full_paths_of_objects_only(self):
        request = self.send(_listing(("a.json.gz", False), ("sub", True)))

        self.assertEqual(self.store.list("p/q"), ["p/q/a.json.gz"])
        method, url = request.call_args.args
        self.assertEqual((method, url), ("POST", "https://x.test/storage/v1/object/list/market-data"))
        self.assertEqual(request.call_args.kwargs["json"]["prefix"], "p/q")

    def test_folders_returns_names_of_folders_only(self):
        self.send(_listing(("a.json.gz", False), ("2026-10-28", True)))

        self.assertEqual(self.store.folders("p"), ["2026-10-28"])

    def test_a_full_page_is_followed_by_the_next(self):
        with mock.patch("storage.object_store.LIST_PAGE_SIZE", 2):
            request = self.send(
                _listing(("a", False), ("b", False)), _listing(("c", False))
            )
            self.assertEqual(self.store.list("p"), ["p/a", "p/b", "p/c"])

        self.assertEqual([call.kwargs["json"]["offset"] for call in request.call_args_list], [0, 2])

    def test_remove_deletes_in_batches(self):
        with mock.patch("storage.object_store.REMOVE_BATCH_SIZE", 2):
            request = self.send(_response(), _response())
            self.assertEqual(self.store.remove(["p/a", "p/b", "p/c"]), 3)

        self.assertEqual(
            [call.kwargs["json"]["prefixes"] for call in request.call_args_list],
            [["p/a", "p/b"], ["p/c"]],
        )
        self.assertEqual(request.call_args.args, ("DELETE", "https://x.test/storage/v1/object/market-data"))

    def test_remove_of_nothing_sends_nothing(self):
        request = self.send()
        self.assertEqual(self.store.remove([]), 0)
        request.assert_not_called()

    def test_a_read_only_client_cannot_remove(self):
        store = ObjectStore("https://x.test", "key", read_only=True)
        with self.assertRaises(PermissionError):
            store.remove(["p/a"])


if __name__ == "__main__":
    unittest.main()
