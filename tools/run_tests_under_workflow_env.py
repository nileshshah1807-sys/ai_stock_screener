"""Run a scheduled workflow's regression-test step in that workflow's environment.

Every scheduled workflow runs the test suite as a pre-flight, but inside a job
whose ``env:`` block configures the production run -- the US workflow's
America/New_York timezone, its US holidays, feature flags such as
``PRICE_BAR_PROBE_ENABLED``. All of it leaks into the test step, while CI runs
the same tests in a clean environment. A test that assumes an unset variable
therefore passes on every PR and then fails the cron run that merged it: the US
run of 29 Sept 2026 was the first to notice ``PRICE_BAR_PROBE_ENABLED``.

This replays the step CI cannot see: it takes the workflow's job-level ``env:``,
resolves ``${{ }}`` expressions as they evaluate on a ``schedule`` event, layers
the step's own ``env:`` on top and runs the step's ``run:`` command verbatim.

Usage::

    python -m tools.run_tests_under_workflow_env .github/workflows/daily-us-screener.yml
    python -m tools.run_tests_under_workflow_env --print-env <workflow.yml>

Secrets and repository variables resolve to empty, as they do for a fork's pull
request. An expression this does not understand (``format()``, for one, which
only the ``workflow_dispatch`` branch uses) fails loudly rather than being
guessed at. Nothing here is imported by the screener.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

EVENT = "schedule"
REGRESSION_COMMAND = "unittest"

_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}")
_EVENT_TEST = re.compile(r"github\.event_name\s*==\s*'(\w+)'")
_LITERAL = re.compile(r"'((?:[^']|'')*)'")
_CONTEXT = re.compile(r"(vars|secrets|github)\.(\w+)")
_GITHUB = {
    "repository": lambda: os.environ.get("GITHUB_REPOSITORY", "owner/repo"),
    "run_id": lambda: "1",
    "run_attempt": lambda: "1",
    "token": lambda: "",
}


def _split(text: str, separator: str) -> list[str]:
    """Split on ``separator`` outside quotes and parentheses."""
    parts, depth, quoted, start, i = [], 0, False, 0, 0
    while i < len(text):
        char = text[i]
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        elif not quoted and depth == 0 and text.startswith(separator, i):
            parts.append(text[start:i])
            start = i + len(separator)
            i += len(separator) - 1
        i += 1
    parts.append(text[start:])
    return parts


def _wrapped(text: str) -> bool:
    """True when the opening parenthesis closes on the last character."""
    if not text.startswith("("):
        return False
    depth, quoted = 0, False
    for i, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
            if depth == 0:
                return i == len(text) - 1
    return False


def evaluate(expression: str):
    """Evaluate a workflow expression for a ``schedule`` event.

    Follows the Actions semantics that matter here: ``&&`` / ``||`` return an
    operand rather than a boolean, and the empty string is falsy.
    """
    text = expression.strip()

    alternatives = _split(text, "||")
    if len(alternatives) > 1:
        for alternative in alternatives[:-1]:
            value = evaluate(alternative)
            if value:
                return value
        return evaluate(alternatives[-1])

    conjuncts = _split(text, "&&")
    if len(conjuncts) > 1:
        value = None
        for conjunct in conjuncts:
            value = evaluate(conjunct)
            if not value:
                return value
        return value

    if _wrapped(text):
        return evaluate(text[1:-1])
    if match := _EVENT_TEST.fullmatch(text):
        return match.group(1) == EVENT
    if match := _LITERAL.fullmatch(text):
        return match.group(1).replace("''", "'")
    if match := _CONTEXT.fullmatch(text):
        scope, name = match.groups()
        if scope in ("vars", "secrets"):
            return ""
        if name in _GITHUB:
            return _GITHUB[name]()
    raise ValueError(f"unsupported workflow expression: {expression.strip()!r}")


def render(value) -> str:
    """Resolve every ``${{ }}`` in one env value to the string the runner sets."""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    whole = _EXPRESSION.fullmatch(text.strip())
    if whole:
        result = evaluate(whole.group(1))
        return render(result) if isinstance(result, bool) else str(result or "")
    return _EXPRESSION.sub(lambda m: str(evaluate(m.group(1)) or ""), text)


def regression_steps(workflow: dict) -> list[tuple[dict, dict]]:
    """(job env, step) for every step that runs the test suite."""
    found = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if REGRESSION_COMMAND in str(step.get("run", "")):
                found.append((job.get("env") or {}, step))
    return found


def step_environment(job_env: dict, step: dict, base: dict[str, str]) -> dict[str, str]:
    """``base`` with the job's and then the step's ``env:`` applied, resolved."""
    env = dict(base)
    for source in (job_env, step.get("env") or {}):
        env.update({name: render(value) for name, value in source.items()})
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workflow", type=Path)
    parser.add_argument(
        "--print-env",
        action="store_true",
        help="print the resolved variables instead of running the tests",
    )
    args = parser.parse_args(argv)

    workflow = yaml.safe_load(args.workflow.read_text(encoding="utf-8"))
    steps = regression_steps(workflow)
    if not steps:
        print(
            f"{args.workflow}: no step runs `{REGRESSION_COMMAND}`; "
            "was it renamed or removed?",
            file=sys.stderr,
        )
        return 2

    status = 0
    for job_env, step in steps:
        env = step_environment(job_env, step, dict(os.environ))
        if args.print_env:
            for name in sorted({**job_env, **(step.get("env") or {})}):
                print(f"{name}={env[name]}")
            continue
        print(f"== {args.workflow.name}: {step.get('name', 'test step')}", flush=True)
        result = subprocess.run(step["run"], shell=True, env=env, check=False)
        status = status or result.returncode
    return status


if __name__ == "__main__":
    sys.exit(main())
