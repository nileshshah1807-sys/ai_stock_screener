"""Shareholding patterns and bulk/block deals, read from NSE's own disclosures.

The figures in the fixtures are ONWARDTEC's September 2026 filing, which
StockScans prints as Promoter 40.20, FII 9.28, DII 1.74, Public 48.78.
"""

import unittest
from datetime import date
from unittest import mock

from screener.shareholding import PARSER_VERSION, parse_deals, parse_pattern, quarter_filings
from workers.shareholding import run

PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"


def document(categories, holders=(), *, scale=1.0):
    """A shareholding-pattern XBRL instance with the given facts.

    ``categories``: member -> fraction of shares; ``holders``: (axis, name,
    fraction, extra facts). ``scale`` 100 writes percentages, as filings did
    before mid-2025.
    """
    contexts, facts = [], []
    for member, fraction in categories.items():
        cid = f"{member}_I"
        contexts.append(
            f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:segment>'
            f'<xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
            f"in-bse-shp:{member}</xbrldi:explicitMember>"
            "</xbrli:segment></xbrli:entity></xbrli:context>"
        )
        facts.append(f'<in-bse-shp:{PCT} contextRef="{cid}">{fraction * scale:g}</in-bse-shp:{PCT}>')
        if member == "ShareholdingPatternMember":
            facts.append(
                f'<in-bse-shp:NumberOfShareholders contextRef="{cid}">21521</in-bse-shp:NumberOfShareholders>'
            )
    for index, (axis, name, fraction, extra) in enumerate(holders):
        for cid in (f"D_{index}", f"H_{index}"):
            contexts.append(
                f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:segment>'
                f'<xbrldi:typedMember dimension="in-bse-shp:{axis}"><x>{index}</x></xbrldi:typedMember>'
                "</xbrli:segment></xbrli:entity></xbrli:context>"
            )
        facts.append(f'<in-bse-shp:NameOfTheShareholder contextRef="D_{index}">{name}</in-bse-shp:NameOfTheShareholder>')
        facts.append(f'<in-bse-shp:{PCT} contextRef="H_{index}">{fraction * scale:g}</in-bse-shp:{PCT}>')
        for tag, value in extra.items():
            facts.append(f'<in-bse-shp:{tag} contextRef="D_{index}">{value}</in-bse-shp:{tag}>')
    return (
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:in-bse-shp="http://example/shp">'
        + "".join(contexts) + "".join(facts) + "</xbrli:xbrl>"
    )


ONWARD = {
    "ShareholdingPatternMember": 1,
    "ShareholdingOfPromoterAndPromoterGroupMember": 0.402,
    "InstitutionsForeignMember": 0.0928,
    "InstitutionsDomesticMember": 0.0174,
    "PublicShareholdingMember": 0.5828,
}
ONWARD_HOLDERS = [
    ("DetailsOfSharesHeldByOthersIndianShareholdersAxis", "Jhm Enterprises Private Limited",
     0.3539, {"TypeOfPromoterShareholding": "Promoter Group"}),
    ("DetailsOfSharesHeldByInstitutionsForeignPortfolioInvestorOneAxis",
     "INFINITY PORTFOLIO HOLDINGS", 0.0829, {}),
    ("DetailsOfSharesHeldByMutualFundsOrUTIAxis", "ICICI PRUDENTIAL TECHNOLOGY FUND", 0.0143, {}),
    ("DetailsOfSharesHeldByForeignCompaniesAxis", "INFINITY DIRECT HOLDINGS", 0.0855, {}),
    # A category's total, named after the category.
    ("DetailsOfSharesHeldByOtherNonInstitutionsAxis", "HUF", 0.0225,
     {"CategoryOfOtherNonInstitutions": "HUF"}),
    # Below 1%: a category total, not a holder the format names.
    ("DetailsOfSharesHeldByOtherNonInstitutionsAxis", "Clearing Members", 0.0007, {}),
]


class ParsePatternTest(unittest.TestCase):
    def test_groups_are_the_exchanges_subtotals(self):
        parsed = parse_pattern(document(ONWARD, ONWARD_HOLDERS))
        self.assertEqual(
            (parsed["promoter"], parsed["fii"], parsed["dii"], parsed["public"]),
            (40.2, 9.28, 1.74, 48.78),
        )
        self.assertEqual(parsed["shareholders"], 21521)

    def test_named_holders_are_grouped_and_category_totals_dropped(self):
        holders = parse_pattern(document(ONWARD, ONWARD_HOLDERS))["holders"]
        self.assertEqual(
            [(h["group"], h["pct"]) for h in holders],
            [("promoter", 35.39), ("public", 8.55), ("fii", 8.29), ("dii", 1.43)],
        )

    def test_percent_filings_read_the_same_and_promoters_by_their_table(self):
        # Before mid-2025: percentages rather than fractions, and no
        # TypeOfPromoterShareholding on promoter rows.
        holders = [(axis, name, share, {}) for axis, name, share, _ in ONWARD_HOLDERS[:2]]
        parsed = parse_pattern(document(ONWARD, holders, scale=100))
        self.assertEqual(parsed["promoter"], 40.2)
        self.assertEqual([h["group"] for h in parsed["holders"]], ["promoter", "fii"])

    def test_a_group_nobody_is_in_is_zero_not_missing(self):
        no_promoter = {k: v for k, v in ONWARD.items() if "Promoter" not in k}
        no_promoter.pop("InstitutionsDomesticMember")
        parsed = parse_pattern(document(no_promoter))
        self.assertEqual((parsed["promoter"], parsed["dii"]), (0.0, 0.0))
        self.assertEqual(parsed["public"], 90.72)

    def test_no_grand_total_reads_nothing(self):
        parsed = parse_pattern(document({"InstitutionsForeignMember": 0.1}))
        self.assertIsNone(parsed["promoter"])
        self.assertIsNone(parsed["public"])


def index_record(symbol, quarter, record_id, broadcast):
    return {
        "symbol": symbol,
        "date": quarter,
        "recordId": record_id,
        "broadcastDate": broadcast,
        "xbrl": f"https://archive.example/SHP_{record_id}_WEB.xml",
        "name": f"{symbol} Limited",
    }


class QuarterFilingsTest(unittest.TestCase):
    def test_keeps_quarter_ends_and_the_latest_revision(self):
        rows = quarter_filings([
            index_record("ONWARDTEC", "30-SEP-2026", "1", "12-OCT-2026 14:51:34"),
            index_record("ONWARDTEC", "30-SEP-2026", "2", "14-OCT-2026 10:00:00"),
            # Filed for an allotment, as of that day.
            index_record("ONWARDTEC", "11-JUN-2026", "3", "19-JUN-2026 17:33:47"),
        ])
        self.assertEqual([(r["period_end"], r["record_id"]) for r in rows], [(date(2026, 9, 30), "2")])


class ParseDealsTest(unittest.TestCase):
    def test_reads_the_export(self):
        text = (
            '﻿"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ",'
            '"Quantity Traded ","Trade Price / Wght. Avg. Price ","Remarks "\n'
            '"16-OCT-2026","AAATECH","AAA Technologies Limited","M7 GLOBAL FUND","SELL",'
            '"4,80,999","1,113.66","-"\n'
        )
        self.assertEqual(parse_deals(text, "bulk"), [{
            "kind": "bulk", "deal_date": "2026-10-16", "symbol": "AAATECH",
            "client_name": "M7 GLOBAL FUND", "side": "SELL", "quantity": 480999,
            "price": 1113.66, "remarks": None,
        }])


class FakeFetcher:
    def __init__(self, documents):
        self.documents = documents
        self.asked = []

    def fetch_many(self, urls):
        self.asked += urls
        return [self.documents.get(url) for url in urls]


class FakeRepository:
    def __init__(self, market="NSE", stored=None):
        self.market = market
        self.stored = stored or {}
        self.patterns, self.deals = [], []

    def shareholding_state(self):
        return self.stored

    def upsert_shareholding_patterns(self, rows):
        self.patterns += rows

    def upsert_bulk_block_deals(self, rows):
        self.deals += rows


DEAL = {"kind": "bulk", "deal_date": "2026-10-16", "symbol": "ONWARDTEC", "client_name": "X",
        "side": "BUY", "quantity": 100, "price": 1.0, "remarks": None}


class WorkerTest(unittest.TestCase):
    def _run(self, repo, records, documents, **kwargs):
        fetcher = FakeFetcher(documents)
        counts = run(
            repo,
            index_loader=lambda start, end: records if end == date(2026, 10, 18) else [],
            deals_loader=lambda kind, start, end: [dict(DEAL, kind=kind)] * 2,
            fetcher=fetcher,
            today=date(2026, 10, 18),
            **kwargs,
        )
        return counts, fetcher

    def test_stores_new_filings_and_skips_what_is_stored(self):
        records = [
            index_record("ONWARDTEC", "30-SEP-2026", "9", "12-OCT-2026 14:51:34"),
            index_record("TCS", "30-SEP-2026", "7", "11-OCT-2026 10:00:00"),
        ]
        repo = FakeRepository(stored={
            ("TCS", "2026-09-30"): {"record_id": "7", "parser_version": PARSER_VERSION},
        })
        documents = {"https://archive.example/SHP_9_WEB.xml": document(ONWARD)}
        counts, fetcher = self._run(repo, records, documents)
        self.assertEqual(fetcher.asked, ["https://archive.example/SHP_9_WEB.xml"])
        self.assertEqual([r["symbol"] for r in repo.patterns], ["ONWARDTEC"])
        self.assertEqual(repo.patterns[0]["filed_at"], "2026-10-12T14:51:34+05:30")
        # A trade printed twice is one row; each kind is read.
        self.assertEqual(sorted(d["kind"] for d in repo.deals), ["block", "bulk"])
        self.assertEqual(counts["stored"], 1)

    def test_a_refused_batch_stops_the_run(self):
        records = [
            index_record(f"S{i}", "30-SEP-2026", str(i), "12-OCT-2026 14:51:34")
            for i in range(130)
        ]
        repo = FakeRepository(stored={("TCS", "2026-09-30"): {}})
        with mock.patch("workers.shareholding._answer", return_value="HTTP 403"):
            counts, fetcher = self._run(repo, records, {})
        self.assertEqual(len(fetcher.asked), 60)
        self.assertEqual((counts["failed"], counts["deferred"]), (60, 70))
        # Deals come from a different host and are still stored.
        self.assertTrue(repo.deals)

    def test_a_dry_run_writes_nothing(self):
        repo = FakeRepository(stored={("TCS", "2026-09-30"): {}})
        records = [index_record("ONWARDTEC", "30-SEP-2026", "9", "12-OCT-2026 14:51:34")]
        self._run(repo, records, {"https://archive.example/SHP_9_WEB.xml": document(ONWARD)},
                  dry_run=True)
        self.assertEqual((repo.patterns, repo.deals), ([], []))

    def test_us_has_nothing_to_store(self):
        self.assertEqual(run(FakeRepository(market="US")), {})


if __name__ == "__main__":
    unittest.main()
