"""Ownership and sector FPI flow columns the publisher stamps on NSE snapshot rows."""

import unittest
from datetime import date
from unittest import mock

from workers import ownership_flows
from workers.dashboard_publisher import stamp_ownership_flows
from workers.nse_sectors import SECTORS as NSE_SECTORS

RUN = date(2026, 11, 22)


def quarter(symbol, period_end, promoter, fii, dii, public=None):
    return {"symbol": symbol, "period_end": period_end, "promoter": promoter, "fii": fii, "dii": dii, "public": public}


def deal(symbol, side, quantity, price, client="SOME TRADER"):
    return {"symbol": symbol, "side": side, "quantity": quantity, "price": price, "client_name": client}


def fortnights(sector, nets, last_end="2026-11-15"):
    """One row per net, oldest first, the last ending on ``last_end``; the earlier dates only need to sort."""
    rows = [{"period_end": f"2026-{1 + i // 2:02d}-{15 if i % 2 == 0 else 28}", "sectors": [{"sector": sector, "net": net}]}
            for i, net in enumerate(nets[:-1])]
    rows.append({"period_end": last_end, "sectors": [{"sector": sector, "net": nets[-1]}]})
    return rows


class HoldingFieldTests(unittest.TestCase):
    def test_latest_quarter_and_its_move_from_the_one_before(self):
        fields = ownership_flows.holding_fields([
            quarter("ABC", "2026-09-30", 60.0, 12.345, 8.0),
            quarter("ABC", "2026-06-30", 61.0, 11.0, 8.0),
        ], RUN)["ABC"]
        self.assertEqual(fields["fii_pct"], 12.35)
        self.assertEqual(fields["fii_change_qoq"], 1.35)
        self.assertEqual(fields["promoter_change_qoq"], -1.0)
        self.assertEqual(fields["dii_change_qoq"], 0.0)

    def test_no_change_without_the_adjacent_quarter(self):
        fields = ownership_flows.holding_fields([
            quarter("ABC", "2026-09-30", 60, 12, 8),
            quarter("ABC", "2026-03-31", 61, 11, 8),
        ], RUN)["ABC"]
        self.assertEqual(fields["fii_pct"], 12)
        self.assertIsNone(fields["fii_change_qoq"])

    def test_an_unreported_group_is_null_not_zero(self):
        fields = ownership_flows.holding_fields([
            quarter("ABC", "2026-09-30", None, 12, 8),
            quarter("ABC", "2026-06-30", 61, 11, 8),
        ], RUN)["ABC"]
        self.assertIsNone(fields["promoter_pct"])
        self.assertIsNone(fields["promoter_change_qoq"])

    def test_retail_and_the_move_from_the_same_quarter_a_year_earlier(self):
        fields = ownership_flows.holding_fields([
            quarter("ABC", "2026-09-30", 60, 12, 8, public=20),
            quarter("ABC", "2026-06-30", 61, 11, 8),
            quarter("ABC", "2025-09-30", 65, 9, 7),
        ], RUN)["ABC"]
        self.assertEqual(fields["retail_pct"], 20)
        self.assertEqual(fields["promoter_change_1y"], -5)
        self.assertEqual(fields["fii_change_1y"], 3)
        self.assertEqual(fields["dii_change_qoq"], 0)

    def test_no_yearly_change_without_the_year_ago_quarter(self):
        fields = ownership_flows.holding_fields([
            quarter("ABC", "2026-09-30", 60, 12, 8),
            quarter("ABC", "2025-12-31", 65, 9, 7),
        ], RUN)["ABC"]
        self.assertIsNone(fields["fii_change_1y"])
        self.assertIsNone(fields["retail_pct"])

    def test_a_company_that_stopped_filing_has_no_holding(self):
        self.assertEqual(ownership_flows.holding_fields([quarter("OLD", "2026-03-31", 60, 1, 1)], RUN), {})


class DealFieldTests(unittest.TestCase):
    def test_bought_less_sold_in_crore_with_the_foreign_share_apart(self):
        fields = ownership_flows.deal_fields([
            deal("ABC", "BUY", 1_000_000, 500),  # 50 cr
            deal("ABC", "SELL", 200_000, 500, client="MORGAN STANLEY ASIA (SINGAPORE) PTE"),  # -10 cr
        ])
        self.assertEqual(fields["ABC"], {"deals_net_cr_1m": 40.0, "foreign_deals_net_cr_1m": -10.0})

    def test_no_foreign_figure_where_no_foreign_client_dealt(self):
        self.assertEqual(ownership_flows.deal_fields([deal("ABC", "SELL", 100_000, 100)]), {"ABC": {"deals_net_cr_1m": -1.0}})


class SectorFlowTests(unittest.TestCase):
    def test_latest_fortnight_against_the_twelve_before_it(self):
        # 14 fortnights: the first falls outside the twelve; the twelve average 100.
        flows = ownership_flows.sector_flow_vs_average(fortnights("Information Technology", [9999] + [100] * 12 + [400]), RUN)
        self.assertEqual(flows, {"information-technology": 300.0})

    def test_too_short_a_history_makes_no_average(self):
        self.assertEqual(ownership_flows.sector_flow_vs_average(fortnights("Telecommunication", [100] * 5 + [400]), RUN), {})

    def test_a_stale_report_is_not_now(self):
        stale = fortnights("Telecommunication", [100] * 12 + [400], last_end="2026-09-15")
        self.assertEqual(ownership_flows.sector_flow_vs_average(stale, RUN), {})


class SnapshotFieldTests(unittest.TestCase):
    def repository(self, classified):
        repo = mock.Mock()
        repo.shareholding_since.return_value = [quarter("TCS", "2026-09-30", 72, 12, 10)]
        repo.fpi_flows_object.return_value = {"rows": fortnights(NSE_SECTORS[0], [100] * 12 + [50])}
        repo.nse_sectors_object.return_value = {"rows": classified}
        repo.bulk_block_deals_since.return_value = [deal("TCS", "BUY", 100_000, 4000)]
        return repo

    def test_a_stock_takes_its_nse_sectors_flow(self):
        rows = [{"symbol": "TCS", "sector": "Technology", "industry": "IT Services"}]
        repo = self.repository([{"symbol": "TCS", "sector": NSE_SECTORS[0], "industry": "x"}])
        fields = ownership_flows.snapshot_fields(repo, rows, RUN.isoformat())
        self.assertEqual(fields["TCS"]["sector_fpi_vs_avg_cr"], -50.0)
        self.assertEqual(fields["TCS"]["promoter_pct"], 72)
        self.assertEqual(fields["TCS"]["deals_net_cr_1m"], 40.0)
        self.assertEqual(repo.bulk_block_deals_since.call_args.args[0], "2026-10-23")

    def test_no_sector_flow_until_nse_sectors_cover_the_market(self):
        rows = [{"symbol": "TCS", "sector": NSE_SECTORS[0], "industry": "IT"},
                {"symbol": "INFY", "sector": NSE_SECTORS[0], "industry": "IT"}]
        repo = self.repository([{"symbol": "TCS", "sector": NSE_SECTORS[0], "industry": "x"}])
        fields = ownership_flows.snapshot_fields(repo, rows, RUN.isoformat())
        self.assertNotIn("sector_fpi_vs_avg_cr", fields.get("INFY", {}))
        self.assertNotIn("sector_fpi_vs_avg_cr", fields["TCS"])

    def test_an_unreadable_source_leaves_the_columns_empty(self):
        repo = mock.Mock()
        repo.shareholding_since.side_effect = RuntimeError("table missing")
        repo.fpi_flows_object.side_effect = RuntimeError("R2 down")
        repo.bulk_block_deals_since.side_effect = RuntimeError("table missing")
        self.assertEqual(ownership_flows.snapshot_fields(repo, [{"symbol": "TCS"}], RUN.isoformat()), {})

    def test_the_publisher_writes_every_column_on_every_row(self):
        repo = mock.Mock()
        repo.shareholding_since.return_value = [quarter("TCS", "2026-09-30", 72, 12, 10)]
        repo.fpi_flows_object.return_value = None
        rows = [{"symbol": "TCS", "sector": "Technology"}, {"symbol": "XYZ", "sector": "Technology"}]
        stamp_ownership_flows(repo, rows, RUN.isoformat())
        for row in rows:
            self.assertTrue(set(ownership_flows.COLUMNS) <= set(row))
        self.assertEqual(rows[0]["fii_pct"], 12)
        self.assertIsNone(rows[1]["fii_pct"])


if __name__ == "__main__":
    unittest.main()
