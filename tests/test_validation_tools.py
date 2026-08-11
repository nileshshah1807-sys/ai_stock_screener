import json
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
from tools.replay_screener_export import replay_csv
from tools.run_isolated_validation import (
    _configure_isolated_logging,
    _reassert_isolated_config,
    _set_isolated_environment,
    _validate_isolated_config,
    _validate_output_dir,
    main as run_isolated_validation,
)

from validation.comparator import compare_frames
from validation.replay import (
    REPLAY_LIMITATIONS,
    apply_replay_technical_price_proxy,
    replay_export_frame,
    technical_price_source_counts,
)
from validation.reproducibility import (
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
        self.assertEqual(config.SUPABASE_URL, "")
        self.assertEqual(config.SUPABASE_SERVICE_ROLE_KEY, "")
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

    def test_environment_is_reasserted_without_secrets(self):
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
                self.assertEqual(os.environ["SUPABASE_URL"], "")
                self.assertEqual(os.environ["SUPABASE_SERVICE_ROLE_KEY"], "")
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
                    "supabase_url": config.SUPABASE_URL,
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
        self.assertEqual(run_observations["supabase_url"], "")
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
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn('EMAIL_ENABLED: "False"', workflow)
        self.assertIn('WHATSAPP_ENABLED: "False"', workflow)
        self.assertIn('BACKTEST_WRITES_ENABLED: "False"', workflow)
        self.assertIn('RED_FLAG_ENRICHMENT_ENABLED: "False"', workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("actions/cache/save", workflow)
        self.assertNotIn("reports_advanced/price_cache.csv", workflow)
        self.assertNotIn("MCLOUD", workflow)
        self.assertIn("default: RELIANCE,TCS,HDFCBANK,ICICIBANK,INFY", workflow)

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
            "if: success() && steps.schedule-dedupe.outputs.skip != 'true' && github.event_name == 'schedule'",
            workflow,
        )
        self.assertIn("default: false", workflow)


if __name__ == "__main__":
    unittest.main()
