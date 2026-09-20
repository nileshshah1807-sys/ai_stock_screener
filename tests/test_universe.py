import unittest
from types import SimpleNamespace
from unittest import mock

from screener import universe
from screener.markets import resolve

NSE_CSV = (
    "SYMBOL,NAME OF COMPANY\n"
    "RELIANCE,Reliance Industries Limited\n"
    "TCS,Tata Consultancy Services\n"
    " INFY ,Infosys Limited\n"
)

# Two constituent rows in the shape Wikipedia actually publishes, plus a
# "recent changes" table below that names a departed symbol.
WIKITEXT = """
{| class="wikitable sortable sticky-header" id="constituents"
|-
! [[Symbol]] !! Security
|-
| {{NyseSymbol|AA}} || [[Alcoa]]
|-
| {{NasdaqSymbol|AAPL}} || [[Apple Inc.]]
|-
| {{NyseSymbol|BRK.B}} || [[Berkshire Hathaway]]
|}

== Selected changes ==
{| class="wikitable"
|-
| {{NyseSymbol|GONE}} || Removed last year
|}
"""

NASDAQ_LISTED = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
    "Round Lot Size|ETF|NextShares\n"
    "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
    "QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N\n"
    "ZTEST|Nasdaq Test Stock|Q|Y|N|100|N|N\n"
    "ABCW|Some Corp - Warrant|Q|N|N|100|N|N\n"
    "File Creation Time: 0920202618:30|||||||\n"
)

OTHER_LISTED = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
    "Test Issue|NASDAQ Symbol\n"
    "BRK.B|Berkshire Hathaway Inc. Class B Common Stock|N|BRK.B|N|100|N|BRK.B\n"
    "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
    "ABC$A|Some Corp Preferred|N|ABC$A|N|100|N|ABC$A\n"
    "File Creation Time: 0920202618:30|||||||\n"
)


def _response(text, status=200, content=None):
    response = mock.Mock()
    response.status_code = status
    response.text = text
    response.content = content if content is not None else text.encode()
    response.json.return_value = {"parse": {"wikitext": text}}
    response.raise_for_status = mock.Mock()
    if status >= 400:
        response.raise_for_status.side_effect = RuntimeError(f"HTTP {status}")
    return response


class NseUniverseTests(unittest.TestCase):
    def test_master_list_is_parsed_and_hashed_over_raw_bytes(self):
        with mock.patch.object(universe, "_get", return_value=_response(NSE_CSV)):
            result = universe.nse_equity_l()

        self.assertEqual(result.status, "ok")
        self.assertEqual(set(result.symbols), {"RELIANCE", "TCS", "INFY"})
        self.assertEqual(result.source_symbol_count, 3)
        # The manifest hash is over the response bytes, unchanged from v5.1.
        self.assertEqual(len(result.source_sha256), 64)

    def test_http_failure_reports_status_without_raising(self):
        with mock.patch.object(universe, "_get", return_value=_response("", 503)):
            result = universe.nse_equity_l()

        self.assertEqual(result.status, "http_503")
        self.assertEqual(result.symbols, ())

    def test_transport_failure_reports_the_exception_type(self):
        with mock.patch.object(universe, "_get", side_effect=TimeoutError("slow")):
            result = universe.nse_equity_l()

        self.assertEqual(result.status, "error:TimeoutError")
        self.assertEqual(result.symbols, ())


class SpIndexUniverseTests(unittest.TestCase):
    def test_constituents_are_parsed_from_wikitext(self):
        with mock.patch.object(universe, "_get", return_value=_response(WIKITEXT)):
            result = universe.sp500()

        self.assertEqual(result.status, "ok")
        self.assertIn("AAPL", result.symbols)
        self.assertIn("AA", result.symbols)

    def test_share_classes_use_the_vendor_hyphen_convention(self):
        """Wikipedia writes BRK.B; yfinance only answers to BRK-B."""
        with mock.patch.object(universe, "_get", return_value=_response(WIKITEXT)):
            result = universe.sp500()

        self.assertIn("BRK-B", result.symbols)
        self.assertNotIn("BRK.B", result.symbols)

    def test_symbols_below_the_constituents_table_are_ignored(self):
        """The 'selected changes' table names symbols that have left the index."""
        with mock.patch.object(universe, "_get", return_value=_response(WIKITEXT)):
            result = universe.sp500()

        self.assertNotIn("GONE", result.symbols)

    def test_composite_unions_its_three_indices(self):
        pages = {
            "sp500": "{{NyseSymbol|AAA}}",
            "sp400": "{{NyseSymbol|BBB}}",
            "sp600": "{{NyseSymbol|CCC}}",
        }

        def fake_get(url, timeout=15, user_agent=""):
            for key, page in universe._SP_INDEX_PAGES.items():
                if page in url:
                    return _response(pages[key])
            raise AssertionError(f"unexpected url {url}")

        with mock.patch.object(universe, "_get", side_effect=fake_get):
            result = universe.sp1500()

        self.assertEqual(set(result.symbols), {"AAA", "BBB", "CCC"})
        self.assertEqual(result.notes, ("sp500:1", "sp400:1", "sp600:1"))

    def test_one_failed_index_degrades_to_a_partial_universe(self):
        """A partial composite still screens; an empty one would lose the day."""
        def fake_get(url, timeout=15, user_agent=""):
            if universe._SP_INDEX_PAGES["sp400"] in url:
                raise TimeoutError("slow")
            return _response("{{NyseSymbol|AAA}}")

        with mock.patch.object(universe, "_get", side_effect=fake_get):
            result = universe.sp1500()

        self.assertEqual(result.status, "ok:partial")
        self.assertIn("AAA", result.symbols)
        self.assertIn("sp400:error:TimeoutError", result.notes)

    def test_every_index_failing_reports_no_constituents(self):
        with mock.patch.object(universe, "_get", side_effect=TimeoutError("slow")):
            result = universe.sp1500()

        self.assertEqual(result.status, "error:no_constituents")
        self.assertEqual(result.symbols, ())

    def test_digest_tracks_membership_not_page_edits(self):
        """Wikipedia prose churns daily; the universe digest must not."""
        first = universe._digest_symbols({"AAA", "BBB"})
        reordered = universe._digest_symbols({"BBB", "AAA"})
        changed = universe._digest_symbols({"AAA", "CCC"})

        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)


class AllListedUniverseTests(unittest.TestCase):
    def _fetch(self):
        def fake_get(url, timeout=15, user_agent=""):
            if "nasdaqlisted" in url:
                return _response(NASDAQ_LISTED)
            return _response(OTHER_LISTED)

        with mock.patch.object(universe, "_get", side_effect=fake_get):
            return universe.all_listed()

    def test_common_stock_is_kept(self):
        self.assertIn("AAPL", self._fetch().symbols)

    def test_etfs_test_issues_warrants_and_preferred_are_dropped(self):
        symbols = self._fetch().symbols
        self.assertNotIn("QQQ", symbols)      # ETF flag
        self.assertNotIn("SPY", symbols)      # ETF flag
        self.assertNotIn("ZTEST", symbols)    # Test Issue flag
        self.assertNotIn("ABCW", symbols)     # "Warrant" in security name
        self.assertNotIn("ABC$A", symbols)    # "$" marks a preferred line

    def test_the_file_creation_trailer_is_not_a_symbol(self):
        for symbol in self._fetch().symbols:
            self.assertNotIn("File Creation Time", symbol)

    def test_share_classes_are_normalised_here_too(self):
        self.assertIn("BRK-B", self._fetch().symbols)


class SourceResolutionTests(unittest.TestCase):
    def test_each_market_has_a_default_source_and_a_known_url(self):
        for profile in (resolve("NSE"), resolve("US")):
            with self.subTest(market=profile.code):
                source = universe.resolve_source(profile, SimpleNamespace())
                self.assertIn(source, universe.SOURCES)
                self.assertIn(source, universe.SOURCE_URLS)

    def test_us_universe_source_is_overridable(self):
        profile = resolve("US")
        config = SimpleNamespace(US_UNIVERSE_SOURCE="all_listed")
        self.assertEqual(universe.resolve_source(profile, config), "all_listed")

    def test_blank_override_falls_back_to_the_profile_default(self):
        profile = resolve("US")
        config = SimpleNamespace(US_UNIVERSE_SOURCE="")
        self.assertEqual(universe.resolve_source(profile, config), "sp1500")

    def test_unknown_override_raises(self):
        profile = resolve("US")
        config = SimpleNamespace(US_UNIVERSE_SOURCE="russell3000")
        with self.assertRaises(ValueError):
            universe.resolve_source(profile, config)

    def test_the_override_does_not_leak_into_other_markets(self):
        """US_UNIVERSE_SOURCE must never redirect the NSE universe."""
        profile = resolve("NSE")
        config = SimpleNamespace(US_UNIVERSE_SOURCE="all_listed")
        self.assertEqual(universe.resolve_source(profile, config), "nse_equity_l")


if __name__ == "__main__":
    unittest.main()
