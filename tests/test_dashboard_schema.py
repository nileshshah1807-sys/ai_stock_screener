"""Static checks on the dashboard schema DDL.

`storage/dashboard_schema.sql` is executed top to bottom in the Supabase SQL
Editor, against databases that may or may not already have the tables. That
makes statement ORDER part of its contract, and order is exactly the thing a
reviewer's eye skips: `create table if not exists` is a silent no-op on an
existing deployment, so any index or constraint referencing a newly added
column has to come after the ALTER that adds it, not before.

This suite parses the file and walks it in execution order.
"""

import re
import unittest
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "storage" / "dashboard_schema.sql"

CREATE_TABLE = re.compile(
    r"create table if not exists\s+(\w+)\s*\(", re.IGNORECASE
)
ALTER_ADD = re.compile(
    r"add column if not exists\s+(\w+)", re.IGNORECASE
)
ALTER_TABLE = re.compile(r"alter table\s+(\w+)", re.IGNORECASE)
CREATE_INDEX = re.compile(
    r"create index if not exists\s+\w+\s+on\s+(\w+)\s*(?:using\s+\w+\s*)?\(([^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)


def read_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def strip_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )


def columns_in_create_table(body: str) -> set[str]:
    """Column names declared in a create-table body."""
    names = set()
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if re.match(
            r"^(primary key|unique|constraint|foreign key|check)\b",
            stripped,
            re.IGNORECASE,
        ):
            continue
        match = re.match(r"^([a-z_][a-z0-9_]*)\s", stripped)
        if match:
            names.add(match.group(1))
    return names


def index_columns(column_list: str) -> set[str]:
    """Column names referenced by an index, ignoring opclasses and direction."""
    names = set()
    for part in column_list.split(","):
        token = part.strip().split()[0] if part.strip() else ""
        if token and re.match(r"^[a-z_][a-z0-9_]*$", token):
            names.add(token)
    return names


class ExecutionOrderTests(unittest.TestCase):
    def test_every_index_column_exists_by_the_time_the_index_is_created(self):
        """The failure this guards against is not hypothetical.

        The Model 5.0 columns were first appended as ALTERs at the very END of
        the file, while an index on `eligibility_class` sat in the middle. On a
        fresh database that works, because create-table declares the column. On
        an existing one the create-table is skipped, the ALTER has not run yet,
        and the index fails with `column "eligibility_class" does not exist`.
        """
        sql = read_schema()
        available: dict[str, set[str]] = {}

        # Walk statements in file order, tracking what each table has so far.
        for statement in sql.split(";"):
            create = CREATE_TABLE.search(statement)
            if create:
                table = create.group(1).lower()
                body = statement[create.end():]
                available.setdefault(table, set()).update(
                    columns_in_create_table(body)
                )
                continue

            if re.search(r"\balter table\b", statement, re.IGNORECASE):
                table_match = ALTER_TABLE.search(statement)
                if table_match:
                    table = table_match.group(1).lower()
                    added = {m.lower() for m in ALTER_ADD.findall(statement)}
                    if added:
                        available.setdefault(table, set()).update(added)
                continue

            index = CREATE_INDEX.search(statement)
            if index:
                table = index.group(1).lower()
                referenced = index_columns(index.group(2))
                known = available.get(table, set())
                missing = {c.lower() for c in referenced} - {
                    c.lower() for c in known
                }
                self.assertFalse(
                    missing,
                    f"index on {table} references {sorted(missing)} before "
                    "those columns exist. Move the ALTER that adds them above "
                    "this index.",
                )

    def test_model_five_alters_precede_the_model_five_indexes(self):
        sql = read_schema()
        alter_position = sql.index("add column if not exists eligibility_class")
        index_position = sql.index("screener_snapshot_eligibility_idx")
        self.assertLess(
            alter_position,
            index_position,
            "the eligibility ALTER must run before the index that uses it",
        )

    def test_migration_alters_are_idempotent(self):
        # The file is documented as safe to re-run. A bare `add column` would
        # fail the second time and take the rest of the script with it.
        stripped = strip_comments(read_schema())
        bare_adds = re.findall(
            r"add column (?!if not exists)", stripped, re.IGNORECASE
        )
        self.assertEqual(bare_adds, [])

    def test_tables_are_created_before_they_are_altered(self):
        sql = strip_comments(read_schema())
        for table in ("screener_snapshot", "screener_history"):
            create_at = sql.index(f"create table if not exists {table}")
            alter_at = sql.index(f"alter table {table}\n")
            self.assertLess(create_at, alter_at, f"{table} altered before creation")


class PublishedColumnTests(unittest.TestCase):
    def test_logo_domain_exists_for_fresh_and_deployed_snapshot_tables(self):
        sql = read_schema()
        create_body = sql.split(
            "create table if not exists screener_snapshot", 1
        )[1].split(";", 1)[0]
        migration = sql.split("alter table screener_snapshot", 1)[1].split(";", 1)[0]

        self.assertIn("logo_domain", columns_in_create_table(create_body))
        self.assertIn("logo_domain", {m.lower() for m in ALTER_ADD.findall(migration)})

    def test_history_columns_exist_in_the_history_table(self):
        from workers.dashboard_publisher import HISTORY_COLUMNS

        sql = read_schema()
        body = sql.split("create table if not exists screener_history", 1)[1]
        body = body.split(";", 1)[0]
        declared = columns_in_create_table(body)
        # Plus anything the migration adds to the same table.
        alter_block = sql.split("alter table screener_history", 1)[1].split(";", 1)[0]
        declared.update(m.lower() for m in ALTER_ADD.findall(alter_block))

        for db_column, _, _ in HISTORY_COLUMNS:
            self.assertIn(
                db_column,
                declared,
                f"{db_column} is published to screener_history but not declared",
            )


if __name__ == "__main__":
    unittest.main()
