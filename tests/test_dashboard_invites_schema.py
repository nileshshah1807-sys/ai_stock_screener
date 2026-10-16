"""Static checks on the invite trigger in storage/dashboard_invites_schema.sql.

The trigger is the one path by which an account gains access without anyone
writing to dashboard_allowlist, so its guards are the access rule itself.
"""

import re
import unittest
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "storage" / "dashboard_invites_schema.sql"


def executable_sql() -> str:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    )


class InviteTriggerTests(unittest.TestCase):
    def test_every_trigger_requires_an_invite(self):
        sql = executable_sql()
        triggers = re.findall(
            r"create trigger\s+(\w+).*?when\s*\((.*?)\)\s*execute function",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        self.assertEqual(len(triggers), 2)
        for name, condition in triggers:
            with self.subTest(trigger=name):
                self.assertIn("new.invited_at is not null", condition)
                self.assertIn("new.email_confirmed_at is not null", condition)

    def test_grant_never_overwrites_an_existing_role(self):
        sql = executable_sql()
        self.assertIn("on conflict (email) do nothing", sql)
        self.assertNotIn("do update", sql.lower())

    def test_backfill_does_not_run_when_the_file_is_reapplied(self):
        # Re-applying would re-grant anyone removed from the allowlist since.
        self.assertNotRegex(executable_sql().lower(), r"from\s+auth\.users")


if __name__ == "__main__":
    unittest.main()
