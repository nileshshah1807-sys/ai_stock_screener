import re
import unittest
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "seed-production-statement-cache.yml"
)


class SeedProductionStatementCacheWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.directives = "\n".join(
            line
            for line in cls.workflow.splitlines()
            if not line.lstrip().startswith("#")
        )

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

    def test_dispatch_defaults_pin_the_successful_candidate(self):
        self.assertIn("workflow_dispatch:", self.directives)
        self.assertRegex(
            self.directives,
            r"(?ms)^      candidate_run_id:\n"
            r".*?^        default: \"31685056109\"$",
        )
        self.assertRegex(
            self.directives,
            r"(?ms)^      expected_sha:\n"
            r".*?^        default: fa9d3094129b9540717a67fda040449340d7dec1$",
        )
        self.assertIn('"$GITHUB_REF" != "refs/heads/main"', self.directives)

    def test_source_run_and_single_artifact_are_strictly_verified(self):
        step = self._step_block(
            self.directives, "Validate source and stage statement cache"
        )
        self.assertIn('=~ ^[0-9]+$', step)
        self.assertIn("'.conclusion'", step)
        self.assertIn('!= "success"', step)
        self.assertIn("'.head_branch'", step)
        self.assertIn('!= "feat/model-5-factor-architecture"', step)
        self.assertIn("'.head_sha'", step)
        self.assertIn('"$observed_sha" != "$EXPECTED_SHA"', step)
        self.assertIn(
            'artifact_prefix="candidate-model-validation-${CANDIDATE_RUN_ID}-"',
            step,
        )
        self.assertIn(".expired == false", step)
        self.assertIn('"$artifact_count" -ne 1', step)

    def test_archive_extracts_only_a_validated_statement_csv(self):
        step = self._step_block(
            self.directives, "Validate source and stage statement cache"
        )
        self.assertIn(
            'expected_member = PurePosixPath("candidate/statement_cache.csv")',
            step,
        )
        self.assertIn("if len(matches) != 1:", step)
        self.assertIn('required_columns = {"Symbol", "Statement_Schema_Version"}', step)
        self.assertIn("if len(rows) < 2186:", step)
        self.assertIn('if versions != {"1"}:', step)
        self.assertIn("if any(not symbol for symbol in symbols):", step)
        self.assertIn("if len(set(symbols)) != len(symbols):", step)
        self.assertIn('Path("reports_advanced/statement_cache.csv")', step)
        self.assertNotIn("extractall", step)
        self.assertNotRegex(step, r"(?m)^\s*unzip\s")

    def test_only_the_exact_production_cache_path_is_saved(self):
        self.assertRegex(
            self.directives,
            r"(?ms)^permissions:\n"
            r"  contents: read\n"
            r"  actions: read$",
        )
        self.assertEqual(self.directives.count("uses: actions/cache/save@v6"), 1)
        save = self._step_block(
            self.directives, "Save production statement cache seed"
        )
        self.assertIn("path: reports_advanced/statement_cache.csv", save)
        self.assertIn(
            "key: stock-screener-statements-v1-${{ runner.os }}-seed-"
            "${{ inputs.candidate_run_id }}-${{ github.run_id }}",
            save,
        )
        self.assertNotIn("secrets.", self.directives)


if __name__ == "__main__":
    unittest.main()
