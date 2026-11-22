"""Sector pages: the cap-weighted level, the valuation summary and the R2 objects."""

import json
import unittest
from datetime import date, timedelta
from unittest import mock

import numpy as np

from workers import sectors
from workers.market_breadth import decode_sessions, undelta

SESSIONS = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(400)]


def observations(closes, start=0):
    return {SESSIONS[start + offset]: (float(value), 1) for offset, value in enumerate(closes)}


class SectorLevelTests(unittest.TestCase):
    def test_level_is_cap_weighted_from_the_previous_close(self):
        # A: 30 shares at 10, up 10%; B: 10 shares at 10, down 10%.
        levels = sectors.sector_levels(np.array([[10.0, 10.0], [11.0, 9.0]]), np.array([30.0, 10.0]))
        self.assertAlmostEqual(levels[0], 100.0)
        self.assertAlmostEqual(levels[1], 100.0 * (1 + (300 * 0.1 - 100 * 0.1) / 400))

    def test_no_cap_or_no_previous_close_carries_no_weight(self):
        closes = np.array([[10.0, np.nan, 10.0], [12.0, 50.0, 5.0]])
        levels = sectors.sector_levels(closes, np.array([1.0, 1.0, np.nan]))
        self.assertAlmostEqual(levels[1], 120.0)

    def test_an_untraded_session_holds_the_last_close(self):
        points = {"A": observations([10, 11, 12])}
        del points["A"][SESSIONS[1]]
        closes = sectors.close_panel(points, SESSIONS[:3], ["A"])
        self.assertEqual(closes[:, 0].tolist(), [10.0, 10.0, 12.0])


class SummaryTests(unittest.TestCase):
    ROWS = [
        {"market_cap": 300, "pe_ratio": 10, "pct_change_1d": 1, "roe": 0.2, "dividend_yield": 1, "pb_ratio": 2},
        {"market_cap": 100, "pe_ratio": 50, "pct_change_1d": -1, "roe": 0.1},
        {"market_cap": 50, "pe_ratio": None, "pct_change_1d": 0},
        {"market_cap": 50, "pe_ratio": -4, "pct_change_1d": float("nan")},
    ]

    def test_cap_weighted_pe_is_total_cap_over_total_earnings(self):
        summary = sectors.sector_summary(self.ROWS)
        self.assertEqual(summary["total_cap"], 500)
        self.assertAlmostEqual(summary["cap_weighted_pe"], 400 / (30 + 2))
        self.assertEqual(summary["median_pe"], 30)
        self.assertEqual(summary["no_positive_pe"], 2)
        self.assertAlmostEqual(summary["median_roe"], 0.15)
        self.assertEqual(summary["median_yield"], 1)
        self.assertEqual((summary["advancing"], summary["declining"], summary["traded"]), (1, 1, 3))

    def test_nothing_reported_is_none_not_zero(self):
        summary = sectors.sector_summary([{"market_cap": None, "pe_ratio": None}])
        self.assertIsNone(summary["total_cap"])
        self.assertIsNone(summary["cap_weighted_pe"])
        self.assertIsNone(summary["median_pb"])

    def test_pe_buckets_count_positive_pes_with_an_open_top(self):
        buckets = sectors.pe_buckets([{"pe_ratio": 5}, {"pe_ratio": 10}, {"pe_ratio": 250}, {"pe_ratio": -3}, {}])
        self.assertEqual([b["label"] for b in buckets], ["<10", "10–15", "15–20", "20–30", "30–50", "50–100", "100+"])
        self.assertEqual([b["count"] for b in buckets], [1, 1, 0, 0, 0, 0, 1])

    def test_slug_follows_the_index_rule(self):
        self.assertEqual(sectors.sector_slug("Oil, Gas & Consumable Fuels"), "oil-gas-consumable-fuels")


class ObjectTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        self.paths = {name: 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))) for name in "ABC"}
        self.points = {name: observations(path) for name, path in self.paths.items()}
        self.points["C"] = observations(self.paths["C"][300:], start=300)
        self.rows = [
            {"symbol": "A", "sector": "Energy", "company": "A Ltd", "market_cap": 3e9, "pe_ratio": 12},
            {"symbol": "B", "sector": "Energy", "company": "B Ltd", "market_cap": None},
            {"symbol": "C", "sector": "Technology", "company": "C Ltd", "market_cap": 1e9},
            {"symbol": "D", "sector": None, "market_cap": 1e9},
        ]

    def build(self):
        return sectors.build_sector_objects(self.points, SESSIONS, self.rows, market="NSE", run_date="2026-02-04")

    def test_directory_lists_every_sector_and_objects_match(self):
        directory, objects = self.build()
        self.assertEqual([entry["slug"] for entry in directory["sectors"]], ["energy", "technology"])
        self.assertEqual(set(objects), {"energy", "technology"})
        energy = objects["energy"]
        self.assertEqual([member["s"] for member in energy["members"]], ["A", "B"])
        self.assertEqual(energy["members"][0]["c"], "A Ltd")
        self.assertIsNone(energy["members"][1]["mc"])
        json.dumps(objects, allow_nan=False)

    def test_level_starts_at_100_when_the_first_member_trades(self):
        _, objects = self.build()
        energy = objects["energy"]["level"]
        values = undelta(json.loads(energy["series"])["c"])
        self.assertEqual(values[0], 10000)
        # B has no cap, so Energy moves as A alone.
        self.assertAlmostEqual(values[-1] / 100, 100 * self.paths["A"][-1] / self.paths["A"][0], delta=0.01)
        tech_days = decode_sessions(objects["technology"]["level"]["sessions"])
        self.assertEqual(tech_days[0], SESSIONS[300])
        self.assertEqual(objects["technology"]["last_session"], SESSIONS[-1].isoformat())

    def test_changes_are_measured_on_the_level(self):
        directory, _ = self.build()
        energy = directory["sectors"][0]
        a = self.paths["A"]
        self.assertAlmostEqual(energy["d1"], (a[-1] / a[-2] - 1) * 100, delta=0.01)
        self.assertIsNotNone(energy["y1"])
        self.assertIsNone(directory["sectors"][1]["y1"])


class FlatSessionTests(unittest.TestCase):
    def test_a_flat_session_is_zero_not_negative_zero(self):
        self.assertEqual(str(sectors._pct(100.0, 100.0000001)), "0.0")


class PutObjectsTests(unittest.TestCase):
    def test_directory_is_written_last_and_nothing_without_r2(self):
        from storage.dashboard_repository import DashboardRepository

        written = []

        removed, listed = [], []

        class Store:
            def put(self, path, body, content_type):
                written.append((path, json.loads(body), content_type))

            def list(self, prefix):
                listed.append(prefix)
                return [path for path, _, _ in written] + [f"{prefix}/consumer-cyclical.json"]

            def remove(self, paths):
                removed.extend(paths)
                return len(paths)

        repository = DashboardRepository.__new__(DashboardRepository)
        repository.market = "NSE"
        repository._r2 = Store()
        self.assertTrue(
            repository.put_sector_objects({"sectors": []}, {"energy": {"name": "Energy"}}, {"energy": {}}, {"ONGC": "energy"})
        )
        self.assertEqual(
            [path for path, _, _ in written],
            [
                "sectors/NSE/energy.json",
                "sectors/NSE/weights.json",
                "sectors/NSE/symbols.json",
                "sectors/NSE/directory.json",
            ],
        )
        self.assertEqual(written[2][1], {"market": "NSE", "symbols": {"ONGC": "energy"}, "industries": {}})
        self.assertEqual(removed, ["sectors/NSE/consumer-cyclical.json"])  # a sector no longer grouped
        self.assertEqual(listed, ["sectors/NSE"])  # the store adds the folder's slash itself

        repository._r2 = None
        self.assertFalse(repository.put_sector_objects({}, {"x": {}}))


class NseSectorRowsTests(unittest.TestCase):
    ROWS = [
        {"symbol": "TDPOWERSYS", "sector": "Industrials", "industry": "Electrical Equipment"},
        {"symbol": "BHEL", "sector": "Industrials", "industry": "Electrical Equipment"},
        {"symbol": "SIEMENS", "sector": "Industrials", "industry": "Electrical Equipment"},
        {"symbol": "HDFCBANK", "sector": "Financial Services", "industry": "Banks"},
        {"symbol": "POWERX.BO", "sector": "Industrials", "industry": "Electrical Equipment"},
        {"symbol": "ODDCO.BO", "sector": "Industrials", "industry": "Conglomerates"},
    ]
    CLASSIFIED = {
        "TDPOWERSYS": {"sector": "Capital Goods", "industry": "Electrical Equipment"},
        "BHEL": {"sector": "Capital Goods", "industry": "Electrical Equipment"},
        "SIEMENS": {"sector": "Capital Goods", "industry": "Electrical Equipment"},
        "HDFCBANK": {"sector": "Financial Services", "industry": "Banks"},
    }

    def test_nse_sectors_replace_yahoos_and_a_bse_name_takes_its_industrys(self):
        out = {row["symbol"]: row["sector"] for row in sectors.nse_sector_rows(self.ROWS, self.CLASSIFIED)}
        self.assertEqual(out["TDPOWERSYS"], "Capital Goods")
        self.assertEqual(out["HDFCBANK"], "Financial Services")
        self.assertEqual(out["POWERX.BO"], "Capital Goods")
        self.assertIsNone(out["ODDCO.BO"])  # no classified member of its industry: left off
        industries = {row["symbol"]: row["nse_industry"] for row in sectors.nse_sector_rows(self.ROWS, self.CLASSIFIED)}
        self.assertEqual(industries["TDPOWERSYS"], "Electrical Equipment")
        self.assertIsNone(industries["POWERX.BO"])  # its sector is inferred, its industry is not

    def test_an_industry_split_between_sectors_infers_nothing(self):
        rows = [*self.ROWS[:4], {"symbol": "ABB", "sector": "Industrials", "industry": "Electrical Equipment"}]
        power = {"sector": "Power", "industry": "Power"}
        classified = {**self.CLASSIFIED, "ABB": power, "SIEMENS": power}
        rows.append({"symbol": "X.BO", "industry": "Electrical Equipment"})
        out = {row["symbol"]: row["sector"] for row in sectors.nse_sector_rows(rows, classified)}
        self.assertIsNone(out["X.BO"])  # 2 Capital Goods against 2 Power: no majority

    def test_two_spellings_of_one_sector_are_one_sector(self):
        classified = {
            **self.CLASSIFIED,
            "BHEL": {"sector": "CAPITAL GOODS", "industry": "Electrical Equipment"},
        }
        out = {row["symbol"]: row["sector"] for row in sectors.nse_sector_rows(self.ROWS, classified)}
        self.assertEqual(out["BHEL"], "Capital Goods")  # the spelling most of its stocks carry
        self.assertEqual(out["POWERX.BO"], "Capital Goods")

    def test_a_retired_sector_name_is_not_a_sector(self):
        classified = {
            **self.CLASSIFIED,
            "OLDCO": {"sector": "AUTOMOBILE", "industry": "Auto Components"},
        }
        rows = [*self.ROWS, {"symbol": "OLDCO", "sector": "Consumer Cyclical", "industry": "Electrical Equipment"}]
        with mock.patch.object(sectors, "NSE_SECTOR_COVERAGE", 0.5):  # 4 of 5 is this sample's coverage
            out = {row["symbol"]: row["sector"] for row in sectors.nse_sector_rows(rows, classified)}
        self.assertEqual(out["OLDCO"], "Capital Goods")  # placed by its industry, as an unclassified name

    def test_rows_stay_on_yahoo_until_nse_covers_the_market(self):
        partial = {"TDPOWERSYS": self.CLASSIFIED["TDPOWERSYS"]}
        self.assertEqual(sectors.nse_sector_rows(self.ROWS, partial), self.ROWS)

    def test_members_carry_their_nse_industry(self):
        member = sectors._member({"symbol": "TDPOWERSYS", "nse_industry": "Electrical Equipment"})
        self.assertEqual(member["in"], "Electrical Equipment")
        self.assertNotIn("in", sectors._member({"symbol": "X.BO", "nse_industry": None}))
        objects = {"capital-goods": {"members": [member, {"s": "X.BO"}]}}
        self.assertEqual(sectors.member_industries(objects), {"TDPOWERSYS": "Electrical Equipment"})

    def test_member_symbols_names_each_stocks_page(self):
        objects = {"capital-goods": {"members": [{"s": "BHEL"}, {"s": "SIEMENS"}]}, "power": {"members": [{"s": "NTPC"}]}}
        self.assertEqual(
            sectors.member_symbols(objects), {"BHEL": "capital-goods", "SIEMENS": "capital-goods", "NTPC": "power"}
        )


class LiveSectorTests(unittest.TestCase):
    WEIGHTS = {
        "energy": {"last_session": "2026-11-18", "members": [["A", 300.0], ["B", 100.0], ["C", 50.0], ["D", None]]},
        "tech": {"last_session": "2026-11-19", "members": [["A", 1.0]]},
    }

    def quote(self, change, session="2026-11-19"):
        return {"session": session, "change_pct": change}

    def test_cap_weighted_and_held_members_weigh_unchanged(self):
        quotes = {"A": self.quote(2.0), "B": self.quote(-4.0), "C": self.quote(1.0, "2026-11-18"), "D": self.quote(5.0)}
        rows = sectors.live_sector_changes(self.WEIGHTS, quotes)
        self.assertEqual([row["slug"] for row in rows], ["energy"])  # tech's close already covers the session
        energy = rows[0]
        self.assertAlmostEqual(energy["d1"], round((300 * 2 - 100 * 4 + 50 * 0) / 450, 2))
        self.assertEqual((energy["advancing"], energy["declining"], energy["traded"]), (2, 1, 3))

    def test_withheld_or_missing_quotes_leave_both_sides(self):
        rows = sectors.live_sector_changes(self.WEIGHTS, {"A": self.quote(None), "B": self.quote(-1.0)})
        self.assertEqual(rows[0]["d1"], -1.0)
        self.assertEqual(rows[0]["traded"], 1)

    def test_nothing_traded_writes_nothing(self):
        self.assertEqual(sectors.live_sector_changes(self.WEIGHTS, {"A": self.quote(1.0, "2026-11-18")}), [])

    def test_weights_carry_each_members_cap(self):
        weights = sectors.member_weights({"energy": {"last_session": "2026-11-18", "members": [{"s": "A", "mc": 3.0}]}})
        self.assertEqual(weights, {"energy": {"last_session": "2026-11-18", "members": [["A", 3.0]]}})
