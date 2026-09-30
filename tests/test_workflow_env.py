"""tools/run_tests_under_workflow_env.py, and its coverage of the workflows.

The tool exists because the scheduled workflows run the suite inside their own
job env while CI does not (see the tool's docstring). These tests pin the
expression evaluator against the real forms the workflows use, and make sure a
new workflow with a test pre-flight cannot be added without CI replaying it.
"""

import unittest
from pathlib import Path

import yaml

from tools.run_tests_under_workflow_env import (
    evaluate,
    regression_steps,
    render,
    step_environment,
)

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


class EvaluateTests(unittest.TestCase):
    def test_schedule_takes_the_first_branch_of_a_ternary(self):
        self.assertEqual(
            evaluate("github.event_name == 'schedule' && '5.1.0' || '4.0.0-candidate'"),
            "5.1.0",
        )

    def test_dispatch_only_expression_is_not_reached_on_a_schedule(self):
        # format() is unsupported, but `&&` short-circuits before it is read.
        self.assertEqual(
            evaluate(
                "github.event_name == 'workflow_dispatch' && format('x-{0}', github.run_id)"
                " || 'reports_advanced'"
            ),
            "reports_advanced",
        )

    def test_a_dispatch_only_branch_that_is_reached_is_refused(self):
        with self.assertRaises(ValueError):
            evaluate("format('x-{0}', github.run_id)")

    def test_repository_variable_falls_back_to_its_default(self):
        self.assertEqual(evaluate("vars.SOMETHING || '100000'"), "100000")

    def test_parenthesised_alternative_inside_a_conditional(self):
        self.assertEqual(
            evaluate(
                "github.event_name == 'schedule' && (vars.FLAG || 'True') || 'False'"
            ),
            "True",
        )

    def test_secrets_resolve_to_empty(self):
        self.assertEqual(evaluate("secrets.TOKEN"), "")
        self.assertEqual(
            evaluate("github.event_name == 'schedule' && secrets.TOKEN || ''"), ""
        )

    def test_dispatch_inputs_are_empty_on_a_schedule(self):
        # The screeners' production gate: a schedule event takes the production
        # branch through its first operand, and the validation-only output
        # directory is never reached.
        gate = "(github.event_name == 'schedule' || inputs.mode == 'production')"
        self.assertEqual(evaluate(f"{gate} && '5.1.0' || '4.0.0-candidate'"), "5.1.0")
        self.assertIs(evaluate("inputs.mode == 'validation'"), False)
        self.assertEqual(evaluate("inputs.mode"), "")

    def test_operators_inside_a_quoted_string_are_literal(self):
        self.assertEqual(evaluate("'a || b && (c'"), "a || b && (c")

    def test_unknown_expressions_fail_loudly(self):
        with self.assertRaises(ValueError):
            evaluate("contains(github.ref, 'main')")


class RenderTests(unittest.TestCase):
    def test_bare_comparison_renders_as_a_lowercase_boolean(self):
        self.assertEqual(render("${{ github.event_name == 'schedule' }}"), "true")

    def test_yaml_booleans_render_like_the_runner_does(self):
        self.assertEqual(render(True), "true")
        self.assertEqual(render(False), "false")

    def test_expression_embedded_in_a_longer_string(self):
        self.assertIn(
            "github.com/",
            render("agent (+https://github.com/${{ github.repository }})"),
        )

    def test_plain_values_pass_through(self):
        self.assertEqual(render("16:15"), "16:15")
        self.assertEqual(render(120), "120")


class StepEnvironmentTests(unittest.TestCase):
    def test_step_env_overrides_job_env_and_base_is_kept(self):
        env = step_environment(
            {"MARKET": "US", "KEEP": "job"},
            {"env": {"MARKET": "NSE"}},
            {"PATH": "/bin"},
        )
        self.assertEqual(env, {"PATH": "/bin", "MARKET": "NSE", "KEEP": "job"})


class WorkflowCoverageTests(unittest.TestCase):
    """Every workflow that pre-flights the suite is replayed by CI."""

    @staticmethod
    def _load(path):
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _workflows_with_a_test_step(self):
        return {
            path.stem
            for path in WORKFLOWS.glob("*.yml")
            if regression_steps(self._load(path))
        }

    def test_ci_matrix_lists_every_workflow_with_a_test_step(self):
        ci = self._load(WORKFLOWS / "ci.yml")
        job = ci["jobs"]["workflow-env-tests"]
        covered = set(job["strategy"]["matrix"]["workflow"])
        self.assertEqual(covered, self._workflows_with_a_test_step())

    def test_every_workflow_env_expression_is_understood(self):
        for path in WORKFLOWS.glob("*.yml"):
            for job_env, step in regression_steps(self._load(path)):
                with self.subTest(workflow=path.name):
                    step_environment(job_env, step, {})


if __name__ == "__main__":
    unittest.main()
