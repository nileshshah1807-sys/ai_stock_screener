"""NSDL's fortnightly sector-wise FPI report and the largest foreign deals (workers/fpi_flows.py)."""

import json
import unittest
from datetime import date
from pathlib import Path

from workers import fpi_flows

FIXTURES = Path(__file__).parent / "fixtures" / "fpi_flows"
SELECTION = """
<select id="ddlfortnighly">
<option value="~/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_Nov152026.html">NOV 15, 2026</option>
<option value="~/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_Jan152023.html">JAN 15, 2023</option>
<option value="~/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_Dec312022.html">DEC 31, 2022</option>
</select>"""


def report(name):
    return (FIXTURES / name).read_text()


def deal(client, symbol, side, quantity, price, when="2026-11-10"):
    return {"client_name": client, "symbol": symbol, "side": side, "quantity": quantity, "price": price,
            "deal_date": when}


class ParseReportTest(unittest.TestCase):
    def test_current_layout_reads_the_fortnight_equity_columns(self):
        parsed = fpi_flows.parse_report(report("sector_nov152026.html"))
        self.assertEqual((parsed["period_start"], parsed["period_end"]), ("2026-11-01", "2026-11-15"))
        self.assertEqual(parsed["sectors"][1], {"sector": "Financial Services", "net": 43102.0, "held": 2262071.0})
        self.assertEqual(parsed["total"], {"net": 84291.0, "held": 7168672.0})

    def test_2023_layout_with_fewer_columns(self):
        parsed = fpi_flows.parse_report(report("sector_jan152023.html"))
        self.assertEqual(parsed["period_end"], "2023-01-15")
        self.assertEqual(parsed["sectors"][0], {"sector": "Automobile and Auto Components", "net": -1064.0, "held": 261177.0})
        self.assertEqual(parsed["total"]["net"], -15068.0)

    def test_a_layout_whose_first_column_is_not_equity_is_refused(self):
        html = report("sector_jan152023.html").replace("<td>Equity</td>", "<td>Debt</td>")
        with self.assertRaises(ValueError):
            fpi_flows.parse_report(html)


class ReportLinksTest(unittest.TestCase):
    def test_links_and_period_ends(self):
        links = fpi_flows.report_links(SELECTION)
        self.assertEqual(links[0][0], date(2026, 11, 15))
        self.assertTrue(links[0][1].endswith("/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/"
                                             "FIIInvestSector_Nov152026.html"))

    def test_only_missing_reports_from_2023_are_fetched(self):
        fetched = []

        def fetch(url):
            fetched.append(url)
            return SELECTION if url == fpi_flows.SELECTION_URL else report("sector_jan152023.html")

        added = fpi_flows.new_fortnights({"2026-11-15"}, fetch, pause=0)
        self.assertEqual([row["period_end"] for row in added], ["2023-01-15"])
        self.assertEqual(len(fetched), 2)  # the list, then the one report; Dec 2022 predates the sectors


class ForeignInvestorTest(unittest.TestCase):
    def test_foreign_names(self):
        for name in ["GOLDMAN SACHS BANK EUROPE SE - ODI", "MORGAN STANLEY ASIA SINGAPORE PTE",
                     "CITIGROUP GLOBAL MARKETS MAURITIUS PRIVATE LIMITED", "SVF II MEERKAT (DE) LLC",
                     "GOVERNMENT OF SINGAPORE", "VANGUARD EMERGING MARKETS STOCK INDEX FUND",
                     "AUGMENT INDIA I HOLDINGS  LLC", "SAGILITY B.V.", "RIBBIT CAPITAL V L.P."]:
            self.assertTrue(fpi_flows.is_foreign_investor(name), name)

    def test_domestic_names(self):
        for name in ["GRAVITON RESEARCH CAPITAL LLP", "MICROCURVES TRADING PRIVATE LIMITED", "SBI MUTUAL FUND",
                     "HSBC MUTUAL FUND", "MORGAN STANLEY INDIA COMPANY PVT LTD", "DINESH R AGARWAL",
                     "NIRMA LIMITED"]:
            self.assertFalse(fpi_flows.is_foreign_investor(name), name)


class TopDealsTest(unittest.TestCase):
    def test_netted_per_client_and_stock_and_ranked_by_value(self):
        deals = [
            deal("GOLDMAN SACHS BANK EUROPE SE - ODI", "TDPOWERSYS", "BUY", 1_000_000, 500.0, "2026-11-03"),
            deal("GOLDMAN SACHS BANK EUROPE SE - ODI", "TDPOWERSYS", "BUY", 200_000, 510.0, "2026-11-09"),
            deal("SOCIETE GENERALE", "INFY", "BUY", 100_000, 1500.0),
            deal("SOCIETE GENERALE", "INFY", "SELL", 100_000, 1500.0),  # a round trip keeps nothing
            deal("SVF II MEERKAT (DE) LLC", "SWIGGY", "SELL", 5_000_000, 400.0),
            deal("GRAVITON RESEARCH CAPITAL LLP", "TDPOWERSYS", "BUY", 9_000_000, 500.0),  # domestic
        ]
        top = fpi_flows.top_deals(deals)
        self.assertEqual(top["bought"], [{
            "client": "GOLDMAN SACHS BANK EUROPE SE - ODI", "symbol": "TDPOWERSYS", "net": 60.2,
            "shares": 1_200_000, "first": "2026-11-03", "last": "2026-11-09"}])
        self.assertEqual([(d["symbol"], d["net"]) for d in top["sold"]], [("SWIGGY", -200.0)])

    def test_limit(self):
        deals = [deal("GOVERNMENT OF SINGAPORE", f"S{i}", "BUY", 1000 * (i + 1), 100.0) for i in range(8)]
        self.assertEqual([d["symbol"] for d in fpi_flows.top_deals(deals)["bought"]], ["S7", "S6", "S5", "S4", "S3"])


class Repo:
    market = "NSE"

    def __init__(self, body=None, unreadable=False):
        self.body, self.unreadable, self.puts = body, unreadable, []

    def fpi_flows_object(self):
        if self.unreadable:
            raise RuntimeError("R2 down")
        return self.body

    def bulk_block_deals_since(self, since):
        self.since = since
        return [deal("GOVERNMENT OF SINGAPORE", "TCS", "BUY", 100_000, 3000.0)]

    def company_names(self, symbols):
        return {"TCS": "Tata Consultancy Services Limited"}

    def put_fpi_flows_object(self, rows, **extra):
        self.puts.append({"rows": rows, **extra})
        return True


class RunTest(unittest.TestCase):
    def fetch(self, url):
        return SELECTION if url == fpi_flows.SELECTION_URL else report("sector_nov152026.html")

    def test_adds_new_fortnights_to_the_object_and_names_the_deals(self):
        held = {"period_start": "2023-01-01", "period_end": "2023-01-15", "sectors": [], "total": {}}
        repo = Repo({"rows": [held]})
        counts = fpi_flows.run(repo, fetch=self.fetch, today=date(2026, 11, 22))
        self.assertEqual(counts, {"fortnights": 1, "deals": 1})
        put = repo.puts[0]
        self.assertEqual([row["period_end"] for row in put["rows"]], ["2023-01-15", "2026-11-15"])
        self.assertEqual(put["deals"]["bought"][0]["company"], "Tata Consultancy Services Limited")
        self.assertEqual((repo.since, put["deals_since"]), ("2026-10-23", "2026-10-23"))
        json.dumps(put)  # the object is plain JSON

    def test_an_unreadable_object_is_not_overwritten(self):
        repo = Repo(unreadable=True)
        self.assertEqual(fpi_flows.run(repo, fetch=self.fetch), {})
        self.assertEqual(repo.puts, [])

    def test_nsdl_refusing_still_refreshes_deals_and_keeps_history(self):
        def refuse(url):
            raise ConnectionError("refused")

        held = {"period_start": "2026-11-01", "period_end": "2026-11-15", "sectors": [], "total": {}}
        repo = Repo({"rows": [held]})
        fpi_flows.run(repo, fetch=refuse, today=date(2026, 11, 22))
        self.assertEqual(repo.puts[0]["rows"], [held])

    def test_us_writes_nothing(self):
        repo = Repo()
        repo.market = "US"
        self.assertEqual(fpi_flows.run(repo, fetch=self.fetch), {})
        self.assertEqual(repo.puts, [])


if __name__ == "__main__":
    unittest.main()
