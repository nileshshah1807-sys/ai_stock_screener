"""Static contract tests for the scheduled Model 5.0 production promotion."""

import re
import unittest
from pathlib import Path


class Model5ProductionPromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "daily-stock-screener.yml"
        ).read_text(encoding="utf-8")

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

    def test_only_scheduled_daily_runs_activate_versioned_model5(self):
        expected_contract = (
            "FACTOR_MODEL_ENABLED: ${{ github.event_name == 'schedule' && 'True' || 'False' }}",
            "MODEL_VERSION: ${{ github.event_name == 'schedule' && '5.1.0' || '4.0.0-candidate' }}",
            "RECOMMENDATION_POLICY_VERSION: ${{ github.event_name == 'schedule' && '5.2.0' || '4.0.0-candidate' }}",
            'OUTPUT_SCHEMA_VERSION: "4.1.0"',
            "STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN: ${{ github.event_name == 'schedule' && '2500' || '400' }}",
            'FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE: "0.95"',
        )
        for declaration in expected_contract:
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, self.workflow)

        self.assertIn(
            "point-in-time out-of-sample validation pending", self.workflow
        )

    def test_statement_cache_is_checkpointed_after_a_coverage_failure(self):
        save = self._step_block(
            self.workflow, "Save refreshed production statement cache"
        )
        self.assertIn("if: always()", save)
        self.assertIn("github.event_name == 'schedule'", save)
        self.assertIn(
            "hashFiles('reports_advanced/statement_cache.csv') != ''", save
        )
        self.assertIn(
            "steps.production-statement-cache.outputs.cache-primary-key", save
        )


if __name__ == "__main__":
    unittest.main()
