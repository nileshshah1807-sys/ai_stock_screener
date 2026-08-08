import unittest
import gzip
from datetime import date

import pandas as pd

from red_flags.enricher import RedFlagEnricher
from red_flags.shadow import RedFlagShadowSimulator
from red_flags.vigil import VigilClient, build_red_flag_snapshots


class FakeResponse:
    def __init__(self, payload=None, content=None):
        self.payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(next(self.payloads))


class FakeSnapshotRepository:
    def latest_red_flag_snapshots(self, symbols):
        return [{
            "source": "VIGIL",
            "symbol": "RISKY",
            "severity": 3,
            "flag_count": 2,
            "summary": "default; GSM stage 2",
            "source_status": "current",
            "source_as_of": "2026-08-07",
            "snapshot": {
                "flags": [],
                "issuer_severity": 3,
                "trading_severity": 2,
                "policy": "shadow-v2",
                "pledge_details": {
                    "filing_period": "2026-06-30",
                    "encumbered_promoter_pct": 55.0,
                    "encumbered_total_pct": 22.0,
                },
            },
        }]


class VigilClientTests(unittest.TestCase):
    def test_table_records_follows_validated_pagination(self):
        session = FakeSession([
            {"data": [{"symbol": "A"}], "has_more": True, "next_offset": 1},
            {"data": [{"symbol": "B"}], "has_more": False, "next_offset": None},
        ])
        client = VigilClient("https://example.test", page_size=1, session=session)

        self.assertEqual([row["symbol"] for row in client.table_records("pledge_data")], ["A", "B"])
        self.assertEqual(session.calls[1][1]["params"]["offset"], 1)

    def test_table_records_rejects_non_advancing_pagination(self):
        session = FakeSession([
            {"data": [], "has_more": True, "next_offset": 0},
        ])
        client = VigilClient("https://example.test", session=session)

        with self.assertRaisesRegex(ValueError, "invalid pagination"):
            client.table_records("credit_ratings")

    def test_bulk_download_reads_gzipped_csv(self):
        content = gzip.compress(b"nse_symbol,perc_encumbered_promoter\nTEST,25.5\n")
        session = FakeSession([])
        session.get = lambda *args, **kwargs: FakeResponse(content=content)
        client = VigilClient("https://example.test", session=session)

        rows = client.download_table_records("pledge_data")

        self.assertEqual(rows, [{"nse_symbol": "TEST", "perc_encumbered_promoter": "25.5"}])


class RedFlagSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 8, 7)
        self.freshness = {
            table: {"table_name": table, "latest_date": "2026-08-06", "row_count": 10}
            for table in (
                "credit_ratings", "pledge_data", "encumbrance_events", "surveillance_flags"
            )
        }

    def test_aggregates_conservative_flags_and_deduplicates_credit_filing(self):
        datasets = {
            "credit_ratings": [
                {
                    "nse_symbol": "RISKY",
                    "red_flag_reason": "downgrade",
                    "date_of_rating": "2026-08-01",
                    "credit_rating": "CARE BBB",
                    "rating_agency": "CARE",
                    "xbrl_url": "https://nse.test/rating.xml",
                    "record_id": "one",
                },
                {
                    "nse_symbol": "RISKY",
                    "red_flag_reason": "downgrade",
                    "date_of_rating": "2026-08-01",
                    "credit_rating": "CARE BBB",
                    "rating_agency": "CARE",
                    "xbrl_url": "https://nse.test/rating.xml",
                    "record_id": "two",
                },
                {
                    "nse_symbol": "CLEAN",
                    "red_flag_reason": "data_quality",
                    "date_of_rating": "2026-08-01",
                },
            ],
            "pledge_data": [
                {
                    "nse_symbol": "RISKY",
                    "shp_quarter": "30-Jun-2026",
                    "perc_promoter_holding": 40,
                    "perc_encumbered_promoter": 55,
                    "perc_encumbered_total": 22,
                    "sync_date": "2026-08-06",
                },
                {"nse_symbol": "CLEAN", "perc_encumbered_promoter": 0, "sync_date": "2026-08-06"},
            ],
            "encumbrance_events": [
                {
                    "symbol": "RISKY", "event_type": "Invocation", "event_pct": 2.5,
                    "event_date_to": "2026-07-01", "seq_id": "invoke-1", "filing_url": "https://nse.test/invoke",
                },
                {
                    "symbol": "CLEAN", "event_type": "Release", "event_pct": 8,
                    "event_date_to": "2026-07-01", "seq_id": "release-1",
                },
            ],
            "surveillance_flags": [
                {
                    "symbol": "RISKY", "gsm_stage": 2, "is_listing_fee_default": "true",
                    "sync_date": "2026-08-06",
                },
            ],
        }

        snapshots = build_red_flag_snapshots(datasets, self.freshness, today=self.today)
        by_symbol = {row["symbol"]: row for row in snapshots}

        self.assertEqual(by_symbol["RISKY"]["severity"], 3)
        self.assertEqual(by_symbol["RISKY"]["flag_count"], 5)
        self.assertEqual(by_symbol["RISKY"]["snapshot"]["issuer_severity"], 3)
        self.assertEqual(by_symbol["RISKY"]["snapshot"]["trading_severity"], 2)
        self.assertEqual(by_symbol["RISKY"]["snapshot"]["policy"], "shadow-v2")
        self.assertEqual(by_symbol["RISKY"]["snapshot"]["promoter_encumbered_pct"], 55.0)
        self.assertEqual(
            by_symbol["RISKY"]["snapshot"]["pledge_details"]["encumbered_total_pct"],
            22.0,
        )
        pledge_flag = next(
            flag
            for flag in by_symbol["RISKY"]["snapshot"]["flags"]
            if flag["type"] == "promoter_pledge"
        )
        self.assertEqual(pledge_flag["severity"], 2)
        self.assertIn("30-Jun-2026", pledge_flag["summary"])
        self.assertEqual(by_symbol["CLEAN"]["severity"], 0)
        self.assertEqual(by_symbol["CLEAN"]["flag_count"], 0)

    def test_esm_is_trading_risk_not_critical_issuer_distress(self):
        snapshots = build_red_flag_snapshots({
            "surveillance_flags": [
                {"symbol": "ESMONE", "esm_stage": 1, "sync_date": "2026-08-06"},
                {"symbol": "ESMTWO", "esm_stage": 2, "sync_date": "2026-08-06"},
            ],
        }, self.freshness, today=self.today)
        by_symbol = {row["symbol"]: row for row in snapshots}

        self.assertEqual(by_symbol["ESMONE"]["severity"], 1)
        self.assertEqual(by_symbol["ESMONE"]["snapshot"]["issuer_severity"], 0)
        self.assertEqual(by_symbol["ESMONE"]["snapshot"]["trading_severity"], 1)
        self.assertEqual(by_symbol["ESMTWO"]["severity"], 2)

    def test_bz_sz_records_both_listing_and_trading_risk(self):
        snapshots = build_red_flag_snapshots({
            "surveillance_flags": [
                {"symbol": "NONCOMPLY", "is_bz_sz": "true", "sync_date": "2026-08-06"},
            ],
        }, self.freshness, today=self.today)
        snapshot = snapshots[0]
        flag = snapshot["snapshot"]["flags"][0]

        self.assertEqual(snapshot["severity"], 3)
        self.assertEqual(snapshot["snapshot"]["issuer_severity"], 3)
        self.assertEqual(snapshot["snapshot"]["trading_severity"], 2)
        self.assertEqual(flag["risk_axis"], "issuer_and_trading")

    def test_latest_pledge_quarter_replaces_older_higher_encumbrance(self):
        snapshots = build_red_flag_snapshots({
            "pledge_data": [
                {
                    "nse_symbol": "DECLINING",
                    "shp_quarter": "31-Mar-2026",
                    "perc_encumbered_promoter": 80,
                    "perc_encumbered_total": 30,
                },
                {
                    "nse_symbol": "DECLINING",
                    "shp_quarter": "30-Jun-2026",
                    "perc_encumbered_promoter": 5,
                    "perc_encumbered_total": 2,
                },
            ],
        }, self.freshness, today=self.today)
        snapshot = snapshots[0]

        self.assertEqual(snapshot["severity"], 0)
        self.assertEqual(snapshot["flag_count"], 0)
        self.assertEqual(
            snapshot["snapshot"]["pledge_details"]["filing_period"], "2026-06-30"
        )
        self.assertEqual(snapshot["snapshot"]["promoter_encumbered_pct"], 5.0)

    def test_marks_snapshot_partial_when_a_required_feed_is_stale(self):
        freshness = dict(self.freshness)
        freshness["credit_ratings"] = {
            "table_name": "credit_ratings", "latest_date": "2026-07-01", "row_count": 10,
        }
        snapshots = build_red_flag_snapshots(
            {"pledge_data": [{"nse_symbol": "TEST", "perc_encumbered_promoter": 0}]},
            freshness,
            today=self.today,
        )

        self.assertEqual(snapshots[0]["source_status"], "partial_stale")
        self.assertIn("credit_ratings", snapshots[0]["snapshot"]["stale_tables"])
        self.assertEqual(snapshots[0]["source_as_of"], "2026-07-01")

    def test_future_dated_feed_fails_freshness_check(self):
        freshness = dict(self.freshness)
        freshness["credit_ratings"] = {
            "table_name": "credit_ratings", "latest_date": "2026-08-08", "row_count": 10,
        }
        snapshots = build_red_flag_snapshots(
            {"pledge_data": [{"nse_symbol": "TEST", "perc_encumbered_promoter": 0}]},
            freshness,
            today=self.today,
        )

        self.assertEqual(snapshots[0]["source_status"], "partial_stale")
        self.assertEqual(
            snapshots[0]["snapshot"]["table_freshness"]["credit_ratings"]["status"],
            "stale",
        )

    def test_old_credit_action_is_not_presented_as_current_flag(self):
        snapshots = build_red_flag_snapshots({
            "credit_ratings": [{
                "nse_symbol": "OLD",
                "red_flag_reason": "default",
                "date_of_rating": "2024-01-01",
            }],
        }, self.freshness, today=self.today, lookback_days=365)

        self.assertEqual(snapshots[0]["flag_count"], 0)


class RedFlagEnricherTests(unittest.TestCase):
    def test_shadow_enrichment_never_changes_score_or_rating(self):
        source = pd.DataFrame({
            "Symbol": ["RISKY", "UNKNOWN"],
            "Final_Score": [80.0, 70.0],
            "Rating": ["STRONG BUY", "BUY"],
        })

        result = RedFlagEnricher(object(), FakeSnapshotRepository()).enrich(source)

        self.assertEqual(result["Final_Score"].tolist(), [80.0, 70.0])
        self.assertEqual(result["Rating"].tolist(), ["STRONG BUY", "BUY"])
        self.assertEqual(result.loc[0, "Red_Flag_Status"], "Available")
        self.assertEqual(result.loc[0, "Red_Flag_Severity"], 3)
        self.assertEqual(result.loc[0, "Red_Flag_Issuer_Severity"], 3)
        self.assertEqual(result.loc[0, "Red_Flag_Trading_Severity"], 2)
        self.assertEqual(result.loc[0, "Red_Flag_Policy"], "shadow-v2")
        self.assertEqual(result.loc[0, "Red_Flag_Pledge_Quarter"], "2026-06-30")
        self.assertEqual(result.loc[0, "Red_Flag_Total_Capital_Encumbered_Pct"], 22.0)
        self.assertEqual(result.loc[1, "Red_Flag_Status"], "No coverage")
        self.assertTrue(result["Red_Flag_Shadow_Mode"].all())

    def test_shadow_simulator_separates_issuer_and_trading_outcomes(self):
        source = pd.DataFrame({
            "Symbol": ["ISSUER", "TRADING", "CLEAN", "STALE"],
            "Final_Score": [82.0, 76.0, 72.0, 90.0],
            "Rating": ["STRONG BUY", "STRONG BUY", "STRONG BUY", "STRONG BUY"],
            "Red_Flag_Status": ["Available", "Available", "Available", "Partial/stale"],
            "Red_Flag_Issuer_Severity": [3, 0, 0, 3],
            "Red_Flag_Trading_Severity": [0, 3, 0, 0],
        })

        result = RedFlagShadowSimulator().simulate(source)

        self.assertEqual(result.loc[0, "Shadow_Red_Flag_Score_If_Confirmed"], 59.99)
        self.assertEqual(result.loc[0, "Shadow_Red_Flag_Rating_If_Confirmed"], "HOLD")
        self.assertEqual(result.loc[1, "Shadow_Red_Flag_Score_If_Confirmed"], 76.0)
        self.assertEqual(result.loc[1, "Shadow_Red_Flag_Rating_If_Confirmed"], "HOLD")
        self.assertFalse(result.loc[2, "Shadow_Red_Flag_Review_Required"])
        self.assertFalse(result.loc[3, "Shadow_Red_Flag_Would_Change"])
        self.assertEqual(source["Final_Score"].tolist(), result["Final_Score"].tolist())
        self.assertEqual(source["Rating"].tolist(), result["Rating"].tolist())


if __name__ == "__main__":
    unittest.main()
