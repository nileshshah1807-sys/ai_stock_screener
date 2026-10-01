"""Transient-failure handling in the Supabase Storage client."""

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


if __name__ == "__main__":
    unittest.main()
