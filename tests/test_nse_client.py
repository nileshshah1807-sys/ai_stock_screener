import unittest

from screener import nse_client


class NseHostTests(unittest.TestCase):
    def test_the_client_names_the_new_host_everywhere_it_names_one(self):
        self.assertEqual(nse_client.NSE.base_url, "https://www.nseindia.in/api")
        self.assertIs(nse_client.transport.Transport._setCookies, nse_client._set_cookies)


if __name__ == "__main__":
    unittest.main()
