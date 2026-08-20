"""Behavioural spec for the historical security master.

Two properties matter most, and they pull in opposite directions:

* A security that genuinely stopped trading inside the window must stay present
  for the window it traded. If it vanishes, its eventual loss vanishes from every
  historical portfolio with it.
* A security that merely had its ISIN reissued after a split must **not** look
  like it stopped trading, or the run injects a fabricated loss into a company
  that was perfectly healthy.
"""

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from backtest.security_master import (
    STATUS_ACTIVE,
    STATUS_DELISTED,
    STATUS_SUSPENDED_AT_END,
    DelistingPolicy,
    SecurityMaster,
    build_master,
    isin_core,
    link_isin_chains,
)

SESSIONS = [date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16)]


class DictStore:
    """Serves pre-built day panels in place of the bhavcopy cache."""

    def __init__(self, days):
        self.days = days

    def load_day(self, day):
        return self.days.get(day)


def panel(rows):
    return pd.DataFrame(rows, columns=["ISIN", "Symbol", "Close"])


def survivor_and_failure():
    """SURVIVOR trades throughout; FAILEDCO stops after the third session."""
    days = {}
    for index, day in enumerate(SESSIONS):
        rows = [["INE001A01036", "SURVIVOR", 100.0 + index]]
        if index < 3:
            rows.append(["INE999Z01011", "FAILEDCO", 50.0 - index * 10])
        days[day] = panel(rows)
    return DictStore(days)


class IsinCoreTests(unittest.TestCase):
    def test_core_survives_a_face_value_change(self):
        """The real BAJFINANCE pre- and post-split ISINs share a core."""
        self.assertEqual(isin_core("INE296A01024"), isin_core("INE296A01032"))

    def test_different_issuers_have_different_cores(self):
        self.assertNotEqual(isin_core("INE296A01024"), isin_core("INE237A01028"))

    def test_core_is_nine_characters(self):
        self.assertEqual(isin_core("INE296A01024"), "INE296A01")


class ChainLinkingTests(unittest.TestCase):
    def test_sequential_isins_of_one_core_link(self):
        chains = link_isin_chains(
            {"INE296A01024": (0, 40), "INE296A01032": (41, 99)}
        )
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0], ["INE296A01024", "INE296A01032"])

    def test_sustained_concurrency_stays_separate(self):
        """One issuer, two instruments trading side by side, e.g. a DVR class."""
        chains = link_isin_chains(
            {"INE155A01022": (0, 99), "INE155A01030": (0, 99)}
        )
        self.assertEqual(len(chains), 2)

    def test_ragged_handover_overlap_still_links(self):
        chains = link_isin_chains(
            {"INE296A01024": (0, 42), "INE296A01032": (40, 99)},
            max_concurrent_sessions=10,
        )
        self.assertEqual(len(chains), 1)

    def test_different_cores_never_link(self):
        chains = link_isin_chains(
            {"INE296A01024": (0, 40), "INE237A01028": (41, 99)}
        )
        self.assertEqual(len(chains), 2)


class FaceValueBridgeTests(unittest.TestCase):
    """A split must not read as a delisting followed by a new listing."""

    def setUp(self):
        days = {}
        for index, day in enumerate(SESSIONS):
            if index < 5:
                rows = [["INE296A01024", "BAJFINANCE", 7000.0]]
            else:
                rows = [["INE296A01032", "BAJFINANCE", 700.0]]
            days[day] = panel(rows)
        self.master = SecurityMaster(
            build_master(DictStore(days), SESSIONS, terminal_absence_sessions=3)
        )

    def test_split_yields_one_security_not_two(self):
        self.assertEqual(len(self.master), 1)

    def test_split_security_is_active_not_delisted(self):
        self.assertEqual(self.master.status("INE296A01024"), STATUS_ACTIVE)

    def test_no_phantom_delisting_is_reported(self):
        self.assertEqual(self.master.delisted_securities(), [])

    def test_pre_split_isin_resolves_to_the_same_security(self):
        self.assertEqual(
            self.master.security_id_for_isin("INE296A01024"),
            self.master.security_id_for_isin("INE296A01032"),
        )

    def test_isin_history_is_retained_in_order(self):
        record = self.master.record("INE296A01032")
        self.assertEqual(
            record["ISIN_History"], "INE296A01024;INE296A01032"
        )

    def test_current_isin_is_the_post_split_one(self):
        self.assertEqual(self.master.record("INE296A01024")["ISIN"], "INE296A01032")

    def test_face_value_change_is_counted(self):
        self.assertEqual(self.master.record("INE296A01024")["Face_Value_Changes"], 1)

    def test_summary_reports_face_value_changes(self):
        self.assertEqual(
            self.master.survivorship_summary()["face_value_changes"], 1
        )

    def test_session_count_spans_both_isins(self):
        self.assertEqual(
            self.master.record("INE296A01024")["Session_Count"], len(SESSIONS)
        )


class DelistingDetectionTests(unittest.TestCase):
    def setUp(self):
        self.master = SecurityMaster(
            build_master(survivor_and_failure(), SESSIONS, terminal_absence_sessions=3)
        )
        self.failed = self.master.security_id_for_isin("INE999Z01011")

    def test_failed_company_is_present_in_the_master(self):
        self.assertIsNotNone(self.master.record("INE999Z01011"))

    def test_failed_company_is_marked_delisted(self):
        self.assertEqual(self.master.status("INE999Z01011"), STATUS_DELISTED)

    def test_survivor_is_marked_active(self):
        self.assertEqual(self.master.status("INE001A01036"), STATUS_ACTIVE)

    def test_delisted_security_was_listed_during_its_trading_window(self):
        self.assertTrue(self.master.was_listed("INE999Z01011", date(2026, 1, 6)))

    def test_delisted_security_was_not_listed_after_it_stopped(self):
        self.assertFalse(self.master.was_listed("INE999Z01011", date(2026, 1, 15)))

    def test_security_is_not_listed_before_its_first_session(self):
        self.assertFalse(self.master.was_listed("INE999Z01011", date(2025, 12, 1)))

    def test_final_close_is_retained_for_pricing_the_exit(self):
        self.assertAlmostEqual(
            self.master.record("INE999Z01011")["Final_Close"], 30.0
        )

    def test_delisted_securities_are_enumerable(self):
        self.assertEqual(self.master.delisted_securities(), [self.failed])

    def test_survivorship_summary_reports_the_gap(self):
        summary = self.master.survivorship_summary()
        self.assertEqual(summary["securities_total"], 2)
        self.assertEqual(summary["delisted"], 1)
        self.assertEqual(summary["active"], 1)

    def test_unknown_identifier_has_no_record(self):
        self.assertIsNone(self.master.status("INE000X00000"))


class SuspensionTests(unittest.TestCase):
    def test_short_absence_at_the_end_is_not_a_delisting(self):
        days = {
            day: panel([["INE001A01036", "HALTED", 100.0]])
            for day in SESSIONS[:-2]
        }
        days[SESSIONS[-2]] = panel([["INE002B01018", "OTHER", 10.0]])
        days[SESSIONS[-1]] = panel([["INE002B01018", "OTHER", 10.0]])
        master = SecurityMaster(
            build_master(DictStore(days), SESSIONS, terminal_absence_sessions=5)
        )
        self.assertEqual(master.status("INE001A01036"), STATUS_SUSPENDED_AT_END)

    def test_internal_gap_is_recorded_but_stays_active(self):
        days = {}
        for index, day in enumerate(SESSIONS):
            rows = [["INE002B01018", "OTHER", 10.0]]
            if index not in (4, 5):
                rows.append(["INE001A01036", "HALTED", 100.0])
            days[day] = panel(rows)
        master = SecurityMaster(build_master(DictStore(days), SESSIONS))
        record = master.record("INE001A01036")
        self.assertEqual(record["Status"], STATUS_ACTIVE)
        self.assertEqual(record["Gap_Sessions"], 2)
        self.assertEqual(record["Max_Gap_Sessions"], 2)


class IdentityTests(unittest.TestCase):
    def renamed_master(self):
        days = {}
        for index, day in enumerate(SESSIONS):
            symbol = "OLDNAME" if index < 5 else "NEWNAME"
            days[day] = panel([["INE001A01036", symbol, 100.0]])
        return SecurityMaster(build_master(DictStore(days), SESSIONS))

    def test_rename_is_one_security_not_two(self):
        master = self.renamed_master()
        self.assertEqual(len(master), 1)
        security_id = master.security_id_for_isin("INE001A01036")
        self.assertEqual(
            master.renamed_securities()[security_id], ["OLDNAME", "NEWNAME"]
        )

    def test_symbol_resolves_to_the_company_that_held_it_then(self):
        master = self.renamed_master()
        expected = master.security_id_for_isin("INE001A01036")
        self.assertEqual(master.resolve_symbol("OLDNAME", SESSIONS[0]), expected)
        self.assertIsNone(master.resolve_symbol("NEWNAME", SESSIONS[0]))

    def reused_master(self):
        days = {}
        for index, day in enumerate(SESSIONS):
            isin = "INE111A01011" if index < 5 else "INE222B01012"
            days[day] = panel([[isin, "RECYCLED", 100.0]])
        return SecurityMaster(build_master(DictStore(days), SESSIONS))

    def test_reused_ticker_is_flagged_not_silently_merged(self):
        master = self.reused_master()
        self.assertEqual(
            master.reused_symbols()["RECYCLED"],
            sorted(
                [
                    master.security_id_for_isin("INE111A01011"),
                    master.security_id_for_isin("INE222B01012"),
                ]
            ),
        )

    def test_reused_ticker_resolves_by_date(self):
        master = self.reused_master()
        self.assertEqual(
            master.resolve_symbol("RECYCLED", SESSIONS[0]),
            master.security_id_for_isin("INE111A01011"),
        )
        self.assertEqual(
            master.resolve_symbol("RECYCLED", SESSIONS[-1]),
            master.security_id_for_isin("INE222B01012"),
        )

    def test_concurrent_instruments_of_one_issuer_get_distinct_ids(self):
        days = {
            day: panel(
                [
                    ["INE155A01022", "TATAMOTORS", 500.0],
                    ["INE155A01030", "TATAMTRDVR", 250.0],
                ]
            )
            for day in SESSIONS
        }
        master = SecurityMaster(build_master(DictStore(days), SESSIONS))
        self.assertEqual(len(master), 2)
        self.assertNotEqual(
            master.security_id_for_isin("INE155A01022"),
            master.security_id_for_isin("INE155A01030"),
        )


class PersistenceTests(unittest.TestCase):
    def test_round_trip_preserves_lookups(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "master.csv"
            SecurityMaster(
                build_master(
                    survivor_and_failure(), SESSIONS, terminal_absence_sessions=3
                )
            ).save(path)
            reloaded = SecurityMaster.load(path)
            self.assertEqual(reloaded.status("INE999Z01011"), STATUS_DELISTED)
            self.assertEqual(
                reloaded.resolve_symbol("FAILEDCO", SESSIONS[0]),
                reloaded.security_id_for_isin("INE999Z01011"),
            )

    def test_round_trip_preserves_the_isin_bridge(self):
        days = {}
        for index, day in enumerate(SESSIONS):
            isin = "INE296A01024" if index < 5 else "INE296A01032"
            days[day] = panel([[isin, "BAJFINANCE", 100.0]])
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "master.csv"
            SecurityMaster(build_master(DictStore(days), SESSIONS)).save(path)
            reloaded = SecurityMaster.load(path)
            self.assertEqual(
                reloaded.security_id_for_isin("INE296A01024"),
                reloaded.security_id_for_isin("INE296A01032"),
            )

    def test_loading_a_missing_file_yields_an_empty_master(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(len(SecurityMaster.load(Path(tmp) / "absent.csv")), 0)

    def test_empty_session_list_yields_empty_frame(self):
        self.assertTrue(build_master(survivor_and_failure(), []).empty)


class DelistingPolicyTests(unittest.TestCase):
    def test_last_close_is_the_most_generous_assumption(self):
        self.assertAlmostEqual(
            DelistingPolicy("last_close").terminal_price(30.0), 30.0
        )

    def test_haircut_applies_the_recovery_rate(self):
        self.assertAlmostEqual(
            DelistingPolicy("haircut", recovery_rate=0.4).terminal_price(30.0), 12.0
        )

    def test_zero_is_a_total_loss(self):
        self.assertAlmostEqual(DelistingPolicy("zero").terminal_price(30.0), 0.0)

    def test_missing_final_close_yields_no_price(self):
        self.assertIsNone(DelistingPolicy().terminal_price(None))

    def test_default_is_not_the_generous_assumption(self):
        """The default must not quietly carry the last quoted price forward."""
        self.assertEqual(DelistingPolicy().strategy, "haircut")

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            DelistingPolicy("carry_forward_forever")

    def test_recovery_rate_outside_the_unit_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            DelistingPolicy("haircut", recovery_rate=1.5)

    def test_describe_names_the_assumption_for_the_report(self):
        self.assertEqual(DelistingPolicy("haircut", 0.5).describe(), "haircut@0.50")


if __name__ == "__main__":
    unittest.main()
