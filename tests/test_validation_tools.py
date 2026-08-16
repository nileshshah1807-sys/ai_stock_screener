import json
import re
import logging
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from screener.runtime import Config
from tools.compare_screener_outputs import main as compare_screener_outputs
from tools.replay_screener_export import replay_csv
from tools.run_isolated_validation import (
    _configure_isolated_logging,
    _reassert_isolated_config,
    _set_isolated_environment,
    _validate_isolated_config,
    _validate_output_dir,
    main as run_isolated_validation,
)

from validation.comparator import (
    compare_frames,
    validate_factor_statement_coverage,
)
from validation.replay import (
    REPLAY_LIMITATIONS,
    apply_replay_technical_price_proxy,
    replay_export_frame,
    technical_price_source_counts,
)
from validation.reproducibility import (
    DEFAULT_REPRODUCIBILITY_CONFIG_KEYS,
    build_run_manifest,
    canonical_config_hash,
    effective_non_secret_config,
    sha256_file,
    write_run_manifest,
)


class ReproducibilityManifestTests(unittest.TestCase):
    def _config(self):
        return SimpleNamespace(
            MODEL_VERSION="candidate-1",
            SCAN_ALL_NSE=False,
            CUSTOM_WATCHLIST=["TCS", "MCLOUD"],
            STRONG_BUY_MIN_ADX=20.0,
            FACTOR_MODEL_ENABLED=False,
            TRANSCRIPT_SENTIMENT_ENABLED=True,
            SUPABASE_URL="https://private-project.example",
            SUPABASE_SERVICE_ROLE_KEY="never-export-this",
            GMAIL_REFRESH_TOKEN="never-export-this-either",
        )

    def test_config_hash_is_canonical_and_secret_free(self):
        first = self._config()
        second = self._config()
        second.CUSTOM_WATCHLIST = tuple(first.CUSTOM_WATCHLIST)

        self.assertEqual(canonical_config_hash(first), canonical_config_hash(second))
        exported = effective_non_secret_config(first)
        serialized = json.dumps(exported, sort_keys=True)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", exported)
        self.assertNotIn("GMAIL_REFRESH_TOKEN", exported)
        self.assertNotIn("never-export", serialized)
        self.assertNotIn("private-project", serialized)
        self.assertTrue(exported["SUPABASE_CONFIGURED"])

    def test_hash_changes_when_allow_listed_model_setting_changes(self):
        baseline = self._config()
        candidate = self._config()
        candidate.STRONG_BUY_MIN_ADX = 25.0
        self.assertNotEqual(canonical_config_hash(baseline), canonical_config_hash(candidate))

    def test_hash_changes_when_factor_model_is_enabled(self):
        baseline = self._config()
        candidate = self._config()
        candidate.FACTOR_MODEL_ENABLED = True
        self.assertNotEqual(canonical_config_hash(baseline), canonical_config_hash(candidate))

    def test_every_model_five_setting_is_in_the_manifest_allow_list(self):
        prefixes = ("FACTOR_", "MARKET_REGIME_", "REGIME_", "STATEMENT_")
        exact_names = {
            "PRICE_HISTORY_PERIOD",
            "LEGACY_HISTORY_WINDOW_SESSIONS",
            "MIN_PRICE_SESSIONS_REQUIRED",
            "BENCHMARK_INDEX_SYMBOL",
            "BENCHMARK_INDEX_FALLBACK",
            "REQUIRE_MA200_TREND_FOR_BUY",
            "BUY_MA200_TOLERANCE",
            "BUY_MIN_MA200_SLOPE_PCT",
            "STRONG_BUY_REQUIRE_MA50_ABOVE_MA200",
            "STRONG_BUY_MIN_RS_6M",
            "STRONG_BUY_MIN_RS_12M",
            "BUY_MIN_RS_6M",
            "BREAKDOWN_CONFIRM_SESSIONS",
            "BUY_MIN_QUALITY_PCT",
            "STRONG_BUY_MIN_QUALITY_PCT",
            "STRONG_BUY_MIN_GROWTH_PCT",
            "STRONG_BUY_MIN_MOMENTUM_PCT",
            "REQUIRE_LIQUIDITY_FOR_BUY",
            "RANK_BY_ELIGIBILITY_CLASS",
        }
        model_five_keys = {
            name
            for name in vars(Config)
            if name.startswith(prefixes) or name in exact_names
        }

        self.assertTrue(model_five_keys)
        self.assertEqual(
            model_five_keys - set(DEFAULT_REPRODUCIBILITY_CONFIG_KEYS),
            set(),
        )

    def test_manifest_records_input_hash_and_writes_stable_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "snapshot.csv"
            input_path.write_text("Symbol,Score\nMCLOUD,71.28\n", encoding="utf-8")
            generated_at = datetime(2026, 8, 10, 3, 17, tzinfo=timezone.utc)
            manifest = build_run_manifest(
                self._config(),
                input_files=[input_path],
                generated_at=generated_at,
                git_sha="abc123",
                extra={"run_kind": "unit-test"},
            )
            output_path = write_run_manifest(root / "manifest.json", manifest)
            loaded = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["generated_at_utc"], "2026-08-10T03:17:00Z")
        self.assertEqual(loaded["git_sha"], "abc123")
        self.assertEqual(loaded["model_version"], "candidate-1")
        self.assertEqual(len(loaded["inputs"][0]["sha256"]), 64)
        self.assertEqual(loaded["extra"], {"run_kind": "unit-test"})
        serialized = json.dumps(loaded, sort_keys=True)
        self.assertNotIn("never-export", serialized)
        self.assertNotIn("private-project", serialized)


class ReplayProvenanceTests(unittest.TestCase):
    @staticmethod
    def _source_frame():
        return pd.DataFrame(
            [
                {
                    "Symbol": "AAA",
                    "Model_Version": "stale-model",
                    "Recommendation_Policy_Version": "stale-policy",
                    "Output_Schema_Version": "stale-schema",
                    "Model_Config_SHA256": "stale-config-hash",
                    "Run_Git_SHA": "stale-run-sha",
                    "Run_Date": "2026-08-09",
                    "Run_Workflow_ID": "must-not-propagate",
                }
            ]
        )

    def test_frame_replaces_model_metadata_and_clears_stale_run_fields(self):
        candidate = replay_export_frame(
            self._source_frame(),
            Config(),
            analysis_date=date(2026, 8, 10),
        )

        self.assertEqual(candidate.loc[0, "Model_Version"], Config.MODEL_VERSION)
        self.assertEqual(
            candidate.loc[0, "Recommendation_Policy_Version"],
            Config.RECOMMENDATION_POLICY_VERSION,
        )
        self.assertEqual(
            candidate.loc[0, "Output_Schema_Version"],
            Config.OUTPUT_SCHEMA_VERSION,
        )
        self.assertEqual(
            candidate.loc[0, "Model_Config_SHA256"],
            canonical_config_hash(Config()),
        )
        self.assertEqual(candidate.loc[0, "Run_Kind"], "frozen_export_replay")
        self.assertEqual(candidate.loc[0, "Run_Analysis_Date"], "2026-08-10")
        self.assertEqual(
            candidate.loc[0, "Run_Source_Kind"], "frozen_screener_export"
        )
        self.assertNotIn("Run_Date", candidate)
        self.assertNotIn("Run_Workflow_ID", candidate)
        self.assertNotIn("stale-run-sha", candidate.astype(str).to_numpy())

    def test_legacy_export_without_technical_price_is_proxied_and_labelled(self):
        """A legacy export must stay scoreable instead of collapsing to HOLD.

        Without the proxy every price-relative technical component is
        unobservable, technical coverage drops under the BUY floor, and the
        whole replay is capped at 59.99 -- silently useless for validation.
        """

        frame = pd.DataFrame(
            [
                {"Symbol": "AAA", "Current_Price": 100.0},
                {"Symbol": "BBB", "Current_Price": 250.0},
            ]
        )

        proxied = apply_replay_technical_price_proxy(frame)

        self.assertEqual(proxied.loc[0, "Technical_Price"], 100.0)
        self.assertEqual(proxied.loc[1, "Technical_Price"], 250.0)
        self.assertTrue(
            (proxied["Technical_Price_Source"] == "replay_proxy_raw_close").all()
        )
        self.assertEqual(
            technical_price_source_counts(proxied),
            {"replay_proxy_raw_close": 2},
        )

    def test_collected_technical_price_is_never_overwritten_by_the_proxy(self):
        frame = pd.DataFrame(
            [
                {"Symbol": "AAA", "Current_Price": 100.0, "Technical_Price": 90.0},
                {"Symbol": "BBB", "Current_Price": 250.0, "Technical_Price": None},
                {"Symbol": "CCC", "Current_Price": 0.0, "Technical_Price": None},
            ]
        )

        proxied = apply_replay_technical_price_proxy(frame)

        # An adjusted price collected in production wins over the raw close.
        self.assertEqual(proxied.loc[0, "Technical_Price"], 90.0)
        self.assertEqual(proxied.loc[0, "Technical_Price_Source"], "source_export")
        self.assertEqual(proxied.loc[1, "Technical_Price"], 250.0)
        self.assertEqual(
            proxied.loc[1, "Technical_Price_Source"], "replay_proxy_raw_close"
        )
        # A non-positive close is not a usable denominator.
        self.assertTrue(pd.isna(proxied.loc[2, "Technical_Price"]))
        self.assertEqual(proxied.loc[2, "Technical_Price_Source"], "unavailable")

    def test_writer_hashes_source_and_output_and_records_limitations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.csv"
            candidate_path = root / "candidate.csv"
            manifest_path = root / "candidate.manifest.json"
            self._source_frame().to_csv(source_path, index=False)
            source_hash = sha256_file(source_path)

            candidate, written_candidate, written_manifest = replay_csv(
                source_path,
                candidate_path,
                analysis_date=date(2026, 8, 10),
                manifest_path=manifest_path,
                config=Config(),
            )
            output_hash = sha256_file(candidate_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(written_candidate, candidate_path)
        self.assertEqual(written_manifest, manifest_path)
        self.assertEqual(manifest["replay"]["analysis_date"], "2026-08-10")
        self.assertEqual(manifest["replay"]["source_csv"]["sha256"], source_hash)
        self.assertEqual(
            manifest["replay"]["candidate_csv"]["sha256"], output_hash
        )
        self.assertEqual(manifest["replay"]["candidate_csv"]["rows"], 1)
        self.assertEqual(manifest["replay"]["limitations"], list(REPLAY_LIMITATIONS))
        self.assertEqual(
            manifest["replay"]["cleared_source_run_columns"],
            ["Run_Date", "Run_Git_SHA", "Run_Workflow_ID"],
        )
        self.assertEqual(
            manifest["replay"]["source_model_metadata"]["Model_Version"][
                "values"
            ],
            ["stale-model"],
        )
        self.assertEqual(candidate.loc[0, "Run_Source_CSV_SHA256"], source_hash)
        self.assertEqual(candidate.loc[0, "Run_Manifest_Path"], manifest_path.name)
        self.assertNotEqual(candidate.loc[0, "Run_Git_SHA"], "stale-run-sha")


class ScreenerComparatorTests(unittest.TestCase):
    @staticmethod
    def _frames():
        baseline = pd.DataFrame([
            {
                "Symbol": "AAA", "Rank": 1, "Rating": "STRONG BUY",
                "Fundamental_Score": 80.0, "Technical_Score": 70.0,
                "Dynamic_Weight_Fund": 0.7, "Dynamic_Weight_Tech": 0.3,
                "Combined_Score": 77.0, "Final_Score": 77.0,
                "Strong_Buy_Eligible": True, "Trend_Confirmed": True,
            },
            {
                "Symbol": "BBB", "Rank": 2, "Rating": "BUY",
                "Fundamental_Score": 70.0, "Technical_Score": 70.0,
                "Dynamic_Weight_Fund": 0.7, "Dynamic_Weight_Tech": 0.3,
                "Combined_Score": 70.0, "Final_Score": 70.0,
                "Strong_Buy_Eligible": False, "Trend_Confirmed": False,
            },
            {
                "Symbol": "CCC", "Rank": 3, "Rating": "BUY",
                "Fundamental_Score": 65.0, "Technical_Score": 65.0,
                "Dynamic_Weight_Fund": 0.7, "Dynamic_Weight_Tech": 0.3,
                "Combined_Score": 65.0, "Final_Score": 65.0,
                "Strong_Buy_Eligible": False, "Trend_Confirmed": False,
            },
            {
                "Symbol": "DDD", "Rank": 4, "Rating": "HOLD",
                "Fundamental_Score": 60.0, "Technical_Score": 60.0,
                "Dynamic_Weight_Fund": 0.7, "Dynamic_Weight_Tech": 0.3,
                "Combined_Score": 60.0, "Final_Score": 60.0,
                "Strong_Buy_Eligible": False, "Trend_Confirmed": False,
            },
        ])
        candidate = pd.DataFrame([
            {
                "Symbol": "BBB", "Rank": 1, "Rating": "STRONG BUY",
                "Fundamental_Score": 75.0, "Technical_Score": 70.0,
                "Dynamic_Weight_Fund": 0.7, "Dynamic_Weight_Tech": 0.3,
                "Combined_Score": 73.5, "Final_Score": 73.5,
                "Strong_Buy_Eligible": True, "Trend_Confirmed": True,
            },
            {
                "Symbol": "AAA", "Rank": 2, "Rating": "STRONG BUY",
                "Fundamental_Score": 80.0, "Technical_Score": 70.0,
                "Dynamic_Weight_Fund": 0.7, "Dynamic_Weight_Tech": 0.3,
                "Combined_Score": 77.0, "Final_Score": 77.0,
                "Strong_Buy_Eligible": True, "Trend_Confirmed": True,
            },
            {
                "Symbol": "DDD", "Rank": 3, "Rating": "BUY",
                "Fundamental_Score": 60.0, "Technical_Score": 65.0,
                "Dynamic_Weight_Fund": 0.7, "Dynamic_Weight_Tech": 0.3,
                "Combined_Score": 61.5, "Final_Score": 61.5,
                "Strong_Buy_Eligible": False, "Trend_Confirmed": False,
            },
            {
                "Symbol": "CCC", "Rank": 4, "Rating": "BUY",
                "Fundamental_Score": 65.0, "Technical_Score": 65.0,
                "Dynamic_Weight_Fund": 0.7, "Dynamic_Weight_Tech": 0.3,
                "Combined_Score": 65.0, "Final_Score": 65.0,
                "Strong_Buy_Eligible": False, "Trend_Confirmed": False,
            },
        ])
        return baseline, candidate

    def test_reports_top_churn_rank_metrics_and_rating_transitions(self):
        baseline, candidate = self._frames()
        summary, attribution = compare_frames(baseline, candidate, top_n=3)

        self.assertEqual(summary["baseline_top"], ["AAA", "BBB", "CCC"])
        self.assertEqual(summary["candidate_top"], ["BBB", "AAA", "DDD"])
        self.assertEqual(summary["entrants"], ["DDD"])
        self.assertEqual(summary["exits"], ["CCC"])
        self.assertEqual(summary["top_overlap_count"], 2)
        self.assertEqual(summary["top_jaccard"], 0.5)
        self.assertAlmostEqual(summary["spearman_common_ranks"], 0.6)
        transitions = {
            (row["baseline_rating"], row["candidate_rating"]): row["count"]
            for row in summary["rating_transitions"]
        }
        self.assertEqual(transitions[("BUY", "STRONG BUY")], 1)
        self.assertEqual(transitions[("HOLD", "BUY")], 1)
        self.assertEqual(attribution["Symbol"].tolist(), ["BBB", "AAA", "DDD", "CCC"])

    def test_score_attribution_reconciles_core_and_post_core_changes(self):
        baseline, candidate = self._frames()
        _, attribution = compare_frames(baseline, candidate, top_n=3)
        by_symbol = attribution.set_index("Symbol")

        bbb = by_symbol.loc["BBB"]
        self.assertEqual(bbb["Delta_Fundamental_Score"], 5.0)
        self.assertEqual(bbb["Weighted_Fundamental_Effect"], 3.5)
        self.assertEqual(bbb["Weighted_Technical_Effect"], 0.0)
        self.assertEqual(bbb["Core_Rounding_Or_Other_Effect"], 0.0)
        self.assertEqual(bbb["Post_Core_DCF_Transcript_Effect"], 0.0)
        self.assertIn("Strong_Buy_Eligible: False -> True", bbb["Gate_Changes"])
        self.assertIn("Rating: BUY -> STRONG BUY", bbb["Attribution"])

    def test_comparison_is_deterministic_under_input_permutation(self):
        baseline, candidate = self._frames()
        first_summary, first_attribution = compare_frames(baseline, candidate, top_n=3)
        second_summary, second_attribution = compare_frames(
            baseline.sample(frac=1, random_state=7),
            candidate.sample(frac=1, random_state=11),
            top_n=3,
        )
        self.assertEqual(first_summary, second_summary)
        assert_frame_equal(first_attribution, second_attribution)

    def test_duplicate_symbols_are_rejected(self):
        baseline, candidate = self._frames()
        duplicate = pd.concat([baseline, baseline.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "duplicate symbols"):
            compare_frames(duplicate, candidate, top_n=3)

    def test_factor_statement_coverage_guard_parses_full_run_metadata(self):
        baseline, candidate = self._frames()
        candidate["Factor_Model_Applied"] = ["true", " YES ", 1, True]
        candidate["Statement_Universe_Coverage"] = ["0.75", 0.75, "0.7500", 0.75]
        candidate["Statement_Record_Available"] = ["true", 1, True, "false"]

        summary, _ = compare_frames(
            baseline,
            candidate,
            top_n=3,
            min_statement_coverage=0.70,
        )

        self.assertEqual(summary["candidate_statement_coverage"], 0.75)
        self.assertEqual(summary["minimum_statement_coverage"], 0.70)

    def test_factor_statement_coverage_guard_rejects_partial_candidate(self):
        _, candidate = self._frames()
        candidate["Factor_Model_Applied"] = True
        candidate["Statement_Universe_Coverage"] = 0.25
        candidate["Statement_Record_Available"] = [True, False, False, False]

        with self.assertRaisesRegex(ValueError, "below the required minimum"):
            validate_factor_statement_coverage(candidate, 0.90)

    def test_factor_statement_coverage_must_be_consistent_on_every_row(self):
        _, candidate = self._frames()
        candidate["Factor_Model_Applied"] = True
        candidate["Statement_Universe_Coverage"] = [0.25, 0.25, 0.50, 0.25]
        candidate["Statement_Record_Available"] = [True, False, False, False]

        with self.assertRaisesRegex(ValueError, "inconsistent across rows"):
            validate_factor_statement_coverage(candidate, 0.20)

    def test_factor_flag_must_be_consistent_on_every_row(self):
        _, candidate = self._frames()
        candidate["Factor_Model_Applied"] = [True, "true", False, 1]

        with self.assertRaisesRegex(
            ValueError, "Factor_Model_Applied is inconsistent across rows"
        ):
            validate_factor_statement_coverage(candidate, 0.90)

    def test_reported_statement_coverage_must_match_available_rows(self):
        _, candidate = self._frames()
        candidate["Factor_Model_Applied"] = True
        candidate["Statement_Universe_Coverage"] = 1.0
        candidate["Statement_Record_Available"] = [True, False, False, False]

        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_factor_statement_coverage(candidate, 0.20)

    def test_statement_guard_does_not_apply_to_non_factor_candidate(self):
        baseline, candidate = self._frames()
        candidate["Factor_Model_Applied"] = ["false", "NO", 0, False]

        summary, _ = compare_frames(
            baseline,
            candidate,
            top_n=3,
            min_statement_coverage=0.90,
        )

        self.assertNotIn("candidate_statement_coverage", summary)

    def test_cli_guard_fails_before_creating_comparison_output(self):
        baseline, candidate = self._frames()
        candidate["Factor_Model_Applied"] = True
        candidate["Statement_Universe_Coverage"] = 0.25
        candidate["Statement_Record_Available"] = [True, False, False, False]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "baseline.csv"
            candidate_path = root / "candidate.csv"
            output_dir = root / "comparison"
            baseline.to_csv(baseline_path, index=False)
            candidate.to_csv(candidate_path, index=False)

            with patch.object(
                sys,
                "argv",
                [
                    "compare_screener_outputs.py",
                    str(baseline_path),
                    str(candidate_path),
                    "--output-dir",
                    str(output_dir),
                    "--min-statement-coverage",
                    "0.90",
                ],
            ):
                with self.assertRaisesRegex(ValueError, "below the required minimum"):
                    compare_screener_outputs()

            self.assertFalse(output_dir.exists())


class IsolatedRunnerSafetyTests(unittest.TestCase):
    @staticmethod
    def _unsafe_config():
        return SimpleNamespace(
            OUTPUT_DIR=Path("reports_advanced"),
            YFINANCE_CACHE_DIR=Path("production-cache"),
            MODEL_VERSION="config-local-version",
            EMAIL_ENABLED=True,
            WHATSAPP_ENABLED=True,
            RED_FLAG_ENRICHMENT_ENABLED=True,
            BACKTEST_LOG_ENABLED=True,
            BACKTEST_WRITES_ENABLED=True,
            RUN_MANIFEST_ENABLED=False,
            SUPABASE_URL="https://production.example",
            SUPABASE_SERVICE_ROLE_KEY="production-secret",
            TWILIO_ACCOUNT_SID="production-account",
            TWILIO_AUTH_TOKEN="production-token",
            TWILIO_WHATSAPP_NUMBER="whatsapp:+10000000000",
            WHATSAPP_RECEIVER="+919999999999",
            CALLMEBOT_API_KEY="production-callmebot-key",
            CALLMEBOT_PHONE="+919999999999",
            PYWHATKIT_PHONE="+919999999999",
            SCAN_ALL_NSE=True,
            CUSTOM_WATCHLIST=["UNSAFE"],
        )

    def test_output_guard_rejects_production_tree_descendants(self):
        repository_root = Path(__file__).resolve().parents[1]
        production_root = (repository_root / "reports_advanced").resolve()

        for unsafe_path in (
            production_root,
            production_root / "candidate",
            production_root / "nested" / "cache",
        ):
            with self.subTest(unsafe_path=unsafe_path):
                with self.assertRaisesRegex(ValueError, "production output tree"):
                    _validate_output_dir(unsafe_path)

        validation_root = (
            repository_root / ".validation-output" / "run-123"
        ).resolve()
        self.assertEqual(_validate_output_dir(validation_root), validation_root)
        with tempfile.TemporaryDirectory() as directory:
            external_root = (Path(directory) / "candidate").resolve()
            self.assertEqual(_validate_output_dir(external_root), external_root)

    def test_config_local_safety_overrides_are_reasserted_after_import(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory).resolve()
            config = self._unsafe_config()
            expected_watchlist = ["RELIANCE", "TCS"]

            _reassert_isolated_config(
                config,
                output_dir=output_dir,
                model_version="candidate-safe",
                scan_all_nse=False,
                custom_watchlist=expected_watchlist,
            )
            _validate_isolated_config(
                config,
                output_dir=output_dir,
                model_version="candidate-safe",
                scan_all_nse=False,
                custom_watchlist=expected_watchlist,
            )

        self.assertEqual(config.OUTPUT_DIR, output_dir)
        self.assertEqual(config.YFINANCE_CACHE_DIR, output_dir / "yfinance_cache")
        self.assertEqual(config.MODEL_VERSION, "candidate-safe")
        self.assertFalse(config.EMAIL_ENABLED)
        self.assertFalse(config.WHATSAPP_ENABLED)
        self.assertFalse(config.RED_FLAG_ENRICHMENT_ENABLED)
        self.assertFalse(config.BACKTEST_LOG_ENABLED)
        self.assertFalse(config.BACKTEST_WRITES_ENABLED)
        self.assertTrue(config.RUN_MANIFEST_ENABLED)
        # Supabase credentials stay so transcript sentiment loads; the
        # read-only flag is what prevents this run mutating shared state.
        self.assertTrue(config.SUPABASE_READ_ONLY)
        self.assertEqual(config.TWILIO_ACCOUNT_SID, "")
        self.assertEqual(config.TWILIO_AUTH_TOKEN, "")
        self.assertEqual(config.TWILIO_WHATSAPP_NUMBER, "")
        self.assertEqual(config.WHATSAPP_RECEIVER, "")
        self.assertEqual(config.CALLMEBOT_API_KEY, "")
        self.assertEqual(config.CALLMEBOT_PHONE, "")
        self.assertEqual(config.PYWHATKIT_PHONE, "")
        self.assertFalse(config.SCAN_ALL_NSE)
        self.assertEqual(config.CUSTOM_WATCHLIST, expected_watchlist)

    def test_safety_validation_fails_closed_after_late_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory).resolve()
            config = self._unsafe_config()
            _reassert_isolated_config(
                config,
                output_dir=output_dir,
                model_version="candidate-safe",
                scan_all_nse=True,
                custom_watchlist=[],
            )
            config.EMAIL_ENABLED = True

            with self.assertRaisesRegex(RuntimeError, "EMAIL_ENABLED"):
                _validate_isolated_config(
                    config,
                    output_dir=output_dir,
                    model_version="candidate-safe",
                    scan_all_nse=True,
                    custom_watchlist=[],
                )

    def test_environment_is_reasserted_without_notification_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory).resolve()
            with patch.dict(
                os.environ,
                {
                    "EMAIL_ENABLED": "True",
                    "WHATSAPP_ENABLED": "True",
                    "BACKTEST_WRITES_ENABLED": "True",
                    "SUPABASE_URL": "https://production.example",
                    "SUPABASE_SERVICE_ROLE_KEY": "production-secret",
                    "TWILIO_ACCOUNT_SID": "production-account",
                    "TWILIO_AUTH_TOKEN": "production-token",
                    "WHATSAPP_RECEIVER": "+919999999999",
                    "CALLMEBOT_API_KEY": "production-callmebot-key",
                    "CALLMEBOT_PHONE": "+919999999999",
                    "PYWHATKIT_PHONE": "+919999999999",
                },
            ):
                _set_isolated_environment(
                    output_dir=output_dir,
                    model_version="candidate-safe",
                    scan_all_nse=False,
                    custom_watchlist=["RELIANCE"],
                )

                self.assertEqual(os.environ["OUTPUT_DIR"], str(output_dir))
                self.assertEqual(os.environ["EMAIL_ENABLED"], "False")
                self.assertEqual(os.environ["WHATSAPP_ENABLED"], "False")
                self.assertEqual(os.environ["BACKTEST_WRITES_ENABLED"], "False")
                # Transcript reads must keep working; writes are blocked by the
                # read-only transport rather than by removing the credentials.
                self.assertEqual(
                    os.environ["SUPABASE_URL"], "https://production.example"
                )
                self.assertEqual(os.environ["SUPABASE_READ_ONLY"], "True")
                self.assertEqual(os.environ["TWILIO_ACCOUNT_SID"], "")
                self.assertEqual(os.environ["TWILIO_AUTH_TOKEN"], "")
                self.assertEqual(os.environ["WHATSAPP_RECEIVER"], "")
                self.assertEqual(os.environ["CALLMEBOT_API_KEY"], "")
                self.assertEqual(os.environ["CALLMEBOT_PHONE"], "")
                self.assertEqual(os.environ["PYWHATKIT_PHONE"], "")
                self.assertEqual(os.environ["SCAN_ALL_NSE"], "False")
                self.assertEqual(os.environ["CUSTOM_WATCHLIST"], "RELIANCE")

    def test_main_reasserts_the_config_returned_by_app_import(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory).resolve()
            config = self._unsafe_config()
            run_observations = {}

            def fake_run_daily_analysis():
                run_observations.update({
                    "output_dir": config.OUTPUT_DIR,
                    "email_enabled": config.EMAIL_ENABLED,
                    "whatsapp_enabled": config.WHATSAPP_ENABLED,
                    "whatsapp_receiver": config.WHATSAPP_RECEIVER,
                    "twilio_token": config.TWILIO_AUTH_TOKEN,
                    "backtest_writes_enabled": config.BACKTEST_WRITES_ENABLED,
                    "supabase_read_only": config.SUPABASE_READ_ONLY,
                    "scan_all_nse": config.SCAN_ALL_NSE,
                    "watchlist": list(config.CUSTOM_WATCHLIST),
                })
                (output_dir / "advanced_analysis_20260810.csv").write_text(
                    "Symbol,Rank\nRELIANCE,1\n",
                    encoding="utf-8",
                )

            fake_app = SimpleNamespace(
                Config=config,
                BacktestEngine=object,
                run_daily_analysis=fake_run_daily_analysis,
            )
            args = SimpleNamespace(
                output_dir=output_dir,
                model_version="candidate-safe",
                custom_watchlist="RELIANCE,TCS",
            )
            with (
                patch.dict(sys.modules, {"app": fake_app}),
                patch("tools.run_isolated_validation.parse_args", return_value=args),
                patch(
                    "tools.run_isolated_validation._configure_isolated_logging",
                    return_value=output_dir / "stock_screener_advanced.log",
                ),
                patch.dict(os.environ, {}, clear=False),
                patch("builtins.print"),
            ):
                result = run_isolated_validation()

            manifest = json.loads(
                (output_dir / "run_manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result, 0)
        self.assertEqual(run_observations["output_dir"], output_dir)
        self.assertFalse(run_observations["email_enabled"])
        self.assertFalse(run_observations["whatsapp_enabled"])
        self.assertEqual(run_observations["whatsapp_receiver"], "")
        self.assertEqual(run_observations["twilio_token"], "")
        self.assertFalse(run_observations["backtest_writes_enabled"])
        self.assertTrue(run_observations["supabase_read_only"])
        self.assertFalse(run_observations["scan_all_nse"])
        self.assertEqual(run_observations["watchlist"], ["RELIANCE", "TCS"])
        self.assertEqual(
            manifest["extra"]["isolated_log"],
            "stock_screener_advanced.log",
        )

    def test_isolated_logger_targets_only_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory).resolve()
            fake_root = SimpleNamespace(handlers=[])

            def capture_configuration(**kwargs):
                fake_root.handlers = kwargs["handlers"]

            with (
                patch("logging.basicConfig", side_effect=capture_configuration),
                patch("logging.getLogger", return_value=fake_root),
            ):
                log_path = _configure_isolated_logging(output_dir)

            try:
                file_handlers = [
                    handler
                    for handler in fake_root.handlers
                    if isinstance(handler, logging.FileHandler)
                ]
                self.assertEqual(log_path, output_dir / "stock_screener_advanced.log")
                self.assertEqual(len(file_handlers), 1)
                self.assertEqual(Path(file_handlers[0].baseFilename), log_path)
            finally:
                for handler in fake_root.handlers:
                    handler.close()


class IsolatedWorkflowSafetyTests(unittest.TestCase):
    def test_candidate_workflow_has_no_secrets_or_production_cache_save(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "candidate-model-validation.yml"
        ).read_text(encoding="utf-8")
        # Assert against directives only. Explanatory comments legitimately name
        # the very things being forbidden, and matching raw text made this test
        # fail on its own documentation.
        directives = "\n".join(
            line for line in workflow.splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertIn("workflow_dispatch", directives)
        self.assertIn('EMAIL_ENABLED: "False"', directives)
        self.assertIn('WHATSAPP_ENABLED: "False"', directives)
        self.assertIn('BACKTEST_WRITES_ENABLED: "False"', directives)
        self.assertIn('RED_FLAG_ENRICHMENT_ENABLED: "False"', directives)
        # Read-only Supabase is the one permitted secret: without it the
        # candidate has no transcript evidence and the baseline diff is
        # meaningless. Every notification secret stays out.
        self.assertIn('SUPABASE_READ_ONLY: "True"', directives)
        permitted_secrets = {"secrets.SUPABASE_URL", "secrets.SUPABASE_SERVICE_ROLE_KEY"}
        used_secrets = set(re.findall(r"secrets\.[A-Z0-9_]+", directives))
        self.assertEqual(used_secrets - permitted_secrets, set())
        # Production vendor data may be restored so the candidate scores the
        # same inputs as the baseline, but never written back, and the restored
        # copy must not outlive the seeding step. The sole cache/save step is
        # scoped to a stable runner-temp path and a candidate-only namespace.
        self.assertIn("uses: actions/cache/restore", directives)
        self.assertEqual(directives.count("uses: actions/cache/save"), 1)
        statement_save = self._step_block(
            directives, "Save accumulated candidate statement cache"
        )
        self.assertIn("candidate-statements-v1-", statement_save)
        self.assertIn("runner.temp", statement_save)
        self.assertNotIn("stock-screener-data-", statement_save)
        self.assertNotIn("stock-screener-statements-", statement_save)
        self.assertNotIn("reports_advanced", statement_save)
        self.assertIn("rm -rf reports_advanced", directives)
        # Backtest history is production decision state, not vendor data. It is
        # restored only so the path list matches the save step's cache version,
        # and must never be copied into the candidate workspace.
        seeded = re.search(r"for name in (.+?); do", directives, re.S)
        self.assertIsNotNone(seeded, "seeding loop not found")
        self.assertNotIn("backtest_history", seeded.group(1))
        self.assertNotIn('cp "reports_advanced/backtest_history', directives)
        self.assertNotIn("MCLOUD", directives)
        self.assertIn("default: RELIANCE,TCS,HDFCBANK,ICICIBANK,INFY", directives)

    @staticmethod
    def _cache_paths(workflow_text, action_suffix):
        """Paths listed under the given actions/cache step."""

        lines = workflow_text.splitlines()
        for index, line in enumerate(lines):
            if f"uses: actions/cache/{action_suffix}" not in line:
                continue
            paths = []
            inside = False
            for candidate in lines[index:]:
                stripped = candidate.strip()
                if stripped.startswith("path:"):
                    inside = True
                    continue
                if inside:
                    if stripped.startswith("reports_advanced/"):
                        paths.append(stripped)
                    elif stripped and not stripped.startswith("#"):
                        break
            return paths
        return []

    @staticmethod
    def _step_block(workflow_text, step_name):
        match = re.search(
            rf"(?ms)^      - name: {re.escape(step_name)}\n"
            rf".*?(?=^      - (?:name:|uses:)|\Z)",
            workflow_text,
        )
        if match is None:
            raise AssertionError(f"workflow step {step_name!r} not found")
        return match.group(0)

    @staticmethod
    def _declared_cache_paths(step_block):
        lines = step_block.splitlines()
        paths = []
        inside = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("path:"):
                inside = True
                inline = stripped.removeprefix("path:").strip()
                if inline and inline not in {"|", ">"}:
                    paths.append(inline)
                continue
            if inside:
                if stripped.startswith("reports_advanced/"):
                    paths.append(stripped)
                elif stripped and not stripped.startswith("#"):
                    break
        return paths

    def test_restore_path_list_matches_the_production_save_path_list(self):
        """GitHub derives the cache version from the path list.

        Dropping a single entry makes every key miss silently: the restore step
        still reports success, the workspace is never seeded, and the run falls
        back to a ~60 minute cold fetch that looks like normal behaviour.
        """

        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        candidate = (workflows / "candidate-model-validation.yml").read_text(
            encoding="utf-8"
        )
        daily = (workflows / "daily-stock-screener.yml").read_text(encoding="utf-8")

        expected = [
            "reports_advanced/price_cache.csv",
            "reports_advanced/fundamental_cache.csv",
            "reports_advanced/nse_liquidity_categories.csv",
            "reports_advanced/backtest_history.csv",
            "reports_advanced/yfinance_cache",
        ]
        blocks = [
            self._step_block(candidate, "Restore production market data (read-only)"),
            self._step_block(daily, "Restore market-data cache"),
            self._step_block(daily, "Save refreshed market-data cache"),
        ]
        for block in blocks:
            self.assertEqual(
                self._declared_cache_paths(block),
                expected,
                "the original production cache path contract must remain pinned; "
                "changing it silently changes GitHub's cache version",
            )

    def test_baseline_is_validated_early_and_pins_its_exact_vendor_cache(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "candidate-model-validation.yml"
        ).read_text(encoding="utf-8")

        validation = workflow.index(
            "- name: Validate and download production baseline artifact"
        )
        self.assertLess(validation, workflow.index("- uses: actions/checkout@v6"))
        self.assertLess(validation, workflow.index("uses: actions/setup-python@v6"))
        self.assertLess(
            validation,
            workflow.index(
                "- name: Run candidate screener without notifications or persistent backtest"
            ),
        )
        self.assertIn('"stock-screener-report-${BASELINE_RUN_ID}"', workflow)
        self.assertIn("Expected exactly one non-empty baseline CSV", workflow)
        self.assertIn(
            'BASELINE_CSV="${baseline_csvs[0]}" python3 - <<\'PY\'', workflow
        )
        self.assertIn("Expected_Price_Bar_As_Of session", workflow)
        self.assertIn("Baseline expected price session is not the currently expected", workflow)
        self.assertIn("BASELINE_PRICE_SESSION={baseline_session.isoformat()}", workflow)
        self.assertIn("source rows lag that session", workflow)
        recheck = self._step_block(
            workflow, "Recheck pinned baseline price session"
        )
        self.assertIn("BASELINE_PRICE_SESSION", recheck)
        self.assertIn("The expected NSE session advanced", recheck)
        self.assertLess(
            workflow.index("- name: Recheck pinned baseline price session"),
            workflow.index(
                "- name: Run candidate screener without notifications or persistent backtest"
            ),
        )
        for setting, normal_ttl in (
            ("PRICE_CACHE_MAX_AGE_HOURS", "18"),
            ("FUND_CACHE_MAX_AGE_DAYS", "7"),
            ("NSE_LIQUIDITY_CACHE_MAX_AGE_DAYS", "35"),
        ):
            self.assertIn(
                f"{setting}: ${{{{ inputs.baseline_run_id != '' && "
                f"'10000' || '{normal_ttl}' }}}}",
                workflow,
            )

        production_restore = self._step_block(
            workflow, "Restore production market data (read-only)"
        )
        self.assertIn("inputs.baseline_run_id", production_restore)
        self.assertIn(
            "stock-screener-data-v2-{0}-{1}", production_restore
        )
        self.assertIn(
            "restore-keys: ${{ inputs.baseline_run_id == ''", production_restore
        )
        self.assertIn(
            "fail-on-cache-miss: ${{ inputs.baseline_run_id != '' }}",
            production_restore,
        )

    def test_candidate_statements_accumulate_outside_production(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "candidate-model-validation.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("statement_seed_run_id:", workflow)
        self.assertIn("candidate-model-validation-${STATEMENT_SEED_RUN_ID}-", workflow)
        self.assertIn("candidate/statement_cache.csv", workflow)
        self.assertRegex(
            workflow,
            r"(?ms)^      statement_fetch_max_symbols:\n"
            r".*?^        default: 600\n"
            r".*?^        type: number$",
        )
        self.assertIn(
            "STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN: "
            "${{ inputs.statement_fetch_max_symbols }}",
            workflow,
        )

        artifact_seed = self._step_block(
            workflow, "Validate and download optional candidate statement seed"
        )
        self.assertIn("${RUNNER_TEMP}/candidate-statement-seed", artifact_seed)
        self.assertNotIn("$VALIDATION_ROOT/prior-candidate", artifact_seed)

        restore = self._step_block(
            workflow, "Restore accumulated candidate statement cache"
        )
        save = self._step_block(
            workflow, "Save accumulated candidate statement cache"
        )
        stable_path = (
            "${{ runner.temp }}/candidate-statement-cache/statement_cache.csv"
        )
        self.assertIn(stable_path, restore)
        self.assertIn(stable_path, save)
        branch_scoped_key = (
            "candidate-statements-v1-${{ runner.os }}-${{ github.ref_name }}-"
        )
        self.assertIn(branch_scoped_key, restore)
        self.assertIn(branch_scoped_key, save)
        self.assertNotIn("stock-screener-data-", restore + save)
        self.assertNotIn("stock-screener-statements-", restore + save)

        stage_position = workflow.index(
            "- name: Stage refreshed candidate statement cache"
        )
        save_position = workflow.index(
            "- name: Save accumulated candidate statement cache"
        )
        compare_position = workflow.index(
            "- name: Compare candidate with optional baseline"
        )
        self.assertLess(stage_position, save_position)
        self.assertLess(save_position, compare_position)
        self.assertIn(
            "if: always() && steps.stage-candidate-statements.outcome == 'success'",
            save,
        )

        compare = self._step_block(
            workflow, "Compare candidate with optional baseline"
        )
        self.assertIn("--min-statement-coverage 0.95", compare)

    def test_daily_statements_use_a_separate_production_namespace(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "daily-stock-screener.yml"
        ).read_text(encoding="utf-8")

        restore = self._step_block(workflow, "Restore production statement cache")
        save = self._step_block(
            workflow, "Save refreshed production statement cache"
        )
        for block in (restore, save):
            self.assertIn("reports_advanced/statement_cache.csv", block)
            self.assertNotIn("stock-screener-data-v2-", block)
        self.assertIn("stock-screener-statements-v1-", restore)
        self.assertIn("${{ github.run_attempt }}", restore)
        self.assertIn(
            "steps.production-statement-cache.outputs.cache-primary-key", save
        )

    def test_manual_daily_dispatch_is_isolated_from_production_state(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "daily-stock-screener.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(".validation-output/{0}", workflow)
        self.assertIn(
            "BACKTEST_WRITES_ENABLED: ${{ github.event_name == 'schedule' }}",
            workflow,
        )
        self.assertIn(
            "EMAIL_ENABLED: ${{ github.event_name == 'schedule' }}",
            workflow,
        )
        self.assertIn(
            "if: steps.schedule-dedupe.outputs.skip != 'true' && github.event_name == 'schedule'",
            workflow,
        )
        self.assertIn(
            "if: success() && steps.schedule-dedupe.outputs.skip != 'true' && steps.session-guard.outputs.skip != 'true' && github.event_name == 'schedule'",
            workflow,
        )
        self.assertIn(
            "if: steps.schedule-dedupe.outputs.skip != 'true' && steps.session-guard.outputs.skip != 'true'",
            workflow,
        )
        self.assertIn("default: false", workflow)


if __name__ == "__main__":
    unittest.main()
