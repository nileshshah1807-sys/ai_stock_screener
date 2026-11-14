"""The D1 copy of the data tables: schema, backfill and count check.

    python -m tools.d1_tables schema            # write storage/d1/<database>.sql from Supabase
    python -m tools.d1_tables apply             # create the tables in D1 (IF NOT EXISTS)
    python -m tools.d1_tables backfill TABLE... # copy rows, resumable, within the day's budget
    python -m tools.d1_tables verify [TABLE...] # row counts, Supabase against D1

The schema is generated from PostgREST's own description of each table (column
types, primary key, simple defaults), so it follows a column added in Supabase:
re-run ``schema`` and review the diff. Tables are ``WITHOUT ROWID`` on their
primary key: D1 counts every index a row touches as a row written, and a rowid
table would add one for the key. Secondary indexes are the reader's call and
are not created here.

``backfill`` reads Supabase in key order, a page at a time, and writes each page
as one upsert through ``storage.d1_backend`` -- an unchanged row writes nothing,
so a re-run costs reads, not writes. Progress and the rows written per UTC day
are kept in ``--state`` (default ``reports_advanced/d1_backfill.json``); at
``--max-rows-written`` for the day it stops with exit code 2, to resume the next
day. Supabase: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY. D1: D1_ACCOUNT_ID,
D1_API_TOKEN and the database ids D1_CORE_ID, D1_EVIDENCE_ID, D1_HISTORY_ID.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from storage.d1_backend import D1Session, WriteCeilingReached, rest_executor

#: Table -> D1 database, as docs/d1_migration_plan.md section 6 groups them.
TABLES: dict[str, str] = {
    **dict.fromkeys(
        (
            "concall_feed", "valuation_basis", "quarterly_filings", "financial_statements",
            "upcoming_events", "market_events", "new_listings", "universe_index",
            "market_breadth", "screener_runs",
        ),
        "core",
    ),
    **dict.fromkeys(
        (
            "bulk_block_deals", "shareholding_patterns", "company_documents", "transcripts",
            "transcript_documents", "transcript_sentiments", "transcript_outlooks",
            "estimate_history", "red_flag_snapshots",
        ),
        "evidence",
    ),
    "screener_history": "history",
}

#: screener_snapshot is not here yet: its 156 columns pass D1's 100 a table, so it
#: needs a layout first (the grid's filter and sort columns, the rest as one JSON
#: column), agreed with the reader.
D1_MAX_COLUMNS = 100

#: D1 keeps only what the pages read of history; the full rows are archived in R2
#: (human, 14 Nov 2026: option a).
HISTORY_COLUMNS = (
    "market", "observed_on", "symbol", "company", "current_price", "volume", "stage",
    "investment_rank", "rating", "decision_score", "final_score", "fundamental_score",
    "technical_score",
)
COLUMNS: dict[str, tuple[str, ...]] = {"screener_history": HISTORY_COLUMNS}

SCHEMA_DIR = Path("storage/d1")
PAGE = 500
DEFAULT_MAX_ROWS_WRITTEN = 75_000

_AFFINITY = {
    "integer": "INTEGER", "bigint": "INTEGER", "smallint": "INTEGER", "boolean": "INTEGER",
    "numeric": "REAL", "double precision": "REAL", "real": "REAL",
}
_NOW = "(strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"


def _supabase() -> tuple[str, dict[str, str]]:
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    return f"{url.rstrip('/')}/rest/v1", {"apikey": key, "Authorization": f"Bearer {key}"}


def describe() -> dict[str, Any]:
    """PostgREST's OpenAPI definitions: table -> {properties, required}."""
    base, headers = _supabase()
    reply = requests.get(f"{base}/", headers={**headers, "Accept": "application/openapi+json"}, timeout=60)
    reply.raise_for_status()
    return reply.json()["definitions"]


def _default(value: Any) -> str | None:
    text = str(value)
    if text in {"now()", "CURRENT_TIMESTAMP"} or text.startswith("timezone("):
        return _NOW
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return text
    if "(" in text:  # a function such as gen_random_uuid(): the writer must supply the value
        return None
    return "'" + text.replace("'", "''") + "'"


def primary_key(definition: dict[str, Any]) -> list[str]:
    return [c for c, spec in definition["properties"].items() if "<pk/>" in str(spec.get("description") or "")]


def table_ddl(table: str, definition: dict[str, Any]) -> str:
    wanted = COLUMNS.get(table)
    required = set(definition.get("required") or ())
    keys = primary_key(definition)
    if not keys:
        raise ValueError(f"{table} has no primary key in Supabase's description")
    lines = []
    for column, spec in definition["properties"].items():
        if wanted and column not in wanted:
            continue
        line = f'    "{column}" {_AFFINITY.get(str(spec.get("format")), "TEXT")}'
        if column in keys or column in required:
            line += " NOT NULL"
        if "default" in spec and (default := _default(spec["default"])) is not None:
            line += f" DEFAULT {default}"
        lines.append(line)
    if len(lines) > D1_MAX_COLUMNS:
        raise ValueError(f"{table} has {len(lines)} columns; D1 allows {D1_MAX_COLUMNS}")
    lines.append("    PRIMARY KEY (" + ", ".join(f'"{key}"' for key in keys) + ")")
    return f'CREATE TABLE IF NOT EXISTS "{table}" (\n' + ",\n".join(lines) + "\n) WITHOUT ROWID;\n"


def write_schema(definitions: dict[str, Any]) -> list[Path]:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for database in sorted(set(TABLES.values())):
        tables = [table for table in sorted(TABLES) if TABLES[table] == database]
        body = "\n".join(table_ddl(table, definitions[table]) for table in tables)
        path = SCHEMA_DIR / f"{database}.sql"
        path.write_text(
            f"-- cupel-{database}: generated by `python -m tools.d1_tables schema`; change Supabase, not this.\n\n" + body
        )
        written.append(path)
    return written


def statements(sql: str) -> list[str]:
    return [part.strip() + ";" for part in sql.split(";\n") if "CREATE" in part]


def d1_env() -> dict[str, str]:
    ids = {db: os.environ.get(f"D1_{db.upper()}_ID", "") for db in ("core", "evidence", "history")}
    if not all(ids.values()):
        raise SystemExit("D1_CORE_ID, D1_EVIDENCE_ID and D1_HISTORY_ID are required")
    return {
        "D1_ACCOUNT_ID": os.environ.get("D1_ACCOUNT_ID", ""),
        "D1_API_TOKEN": os.environ.get("D1_API_TOKEN", ""),
        "D1_DATABASE_ID": ids["core"],
        "D1_TABLE_DATABASES": ",".join(f"{table}:{ids[db]}" for table, db in TABLES.items()),
    }


def apply_schema(execute) -> None:
    for database in sorted(set(TABLES.values())):
        route = next(table for table, db in TABLES.items() if db == database)  # any table of that database
        for statement in statements((SCHEMA_DIR / f"{database}.sql").read_text()):
            execute(route, statement, [])


def _page(table: str, keys: list[str], offset: int) -> list[dict[str, Any]]:
    base, headers = _supabase()
    params = {"order": ",".join(f"{key}.asc" for key in keys), "limit": str(PAGE), "offset": str(offset)}
    if table in COLUMNS:
        params["select"] = ",".join(COLUMNS[table])
    reply = requests.get(f"{base}/{table}", params=params, headers=headers, timeout=120)
    reply.raise_for_status()
    return reply.json()


def _save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))


def backfill(tables: list[str], session: D1Session, state_path: Path, definitions: dict[str, Any], fetch=_page) -> int:
    """Copy each table on from where the state left it. 0 when done, 2 at the day's ceiling."""
    state = json.loads(state_path.read_text()) if state_path.exists() else {"tables": {}, "days": {}}
    day = datetime.now(UTC).date().isoformat()
    already = int(state["days"].get(day, 0))
    session.max_rows_written = max(0, session.max_rows_written - already)
    status = 0
    try:
        for table in tables:
            keys = primary_key(definitions[table])
            progress = state["tables"].setdefault(table, {"offset": 0, "done": False})
            while not progress["done"]:
                rows = fetch(table, keys, progress["offset"])
                if rows:
                    session.request(
                        "POST",
                        f"https://d1/rest/v1/{table}?on_conflict={','.join(keys)}",
                        json=rows,
                        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                    ).raise_for_status()
                progress["offset"] += len(rows)
                progress["done"] = len(rows) < PAGE
                state["days"][day] = already + session.rows_written
                _save(state_path, state)
            print(f"{table}: {progress['offset']} rows read")
    except WriteCeilingReached as exc:
        print(f"Stopped at the day's write budget ({exc}); resume after 00:00 UTC", file=sys.stderr)
        status = 2
    state["days"][day] = already + session.rows_written
    _save(state_path, state)
    print(f"rows written today: {state['days'][day]}")
    return status


def count_supabase(table: str) -> int:
    base, headers = _supabase()
    reply = requests.head(f"{base}/{table}", params={"select": "*"}, headers={**headers, "Prefer": "count=exact"}, timeout=120)
    reply.raise_for_status()
    return int(reply.headers["Content-Range"].rsplit("/", 1)[-1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("schema", "apply", "backfill", "verify"))
    parser.add_argument("tables", nargs="*")
    parser.add_argument("--state", type=Path, default=Path("reports_advanced/d1_backfill.json"))
    parser.add_argument("--max-rows-written", type=int, default=DEFAULT_MAX_ROWS_WRITTEN)
    args = parser.parse_args(argv)
    unknown = sorted(set(args.tables) - set(TABLES))
    if unknown:
        raise SystemExit(f"not a D1 table: {', '.join(unknown)}")

    if args.command == "schema":
        for path in write_schema(describe()):
            print(path)
        return 0
    execute = rest_executor(d1_env(), timeout=120)
    if args.command == "apply":
        apply_schema(execute)
        return 0
    if args.command == "backfill":
        if not args.tables:
            raise SystemExit("name the tables to backfill, in order")
        return backfill(args.tables, D1Session(execute, max_rows_written=args.max_rows_written), args.state, describe())
    for table in args.tables or sorted(TABLES):
        rows, _ = execute(table, f'SELECT count(*) AS n FROM "{table}"', [])
        print(f"{table}: supabase {count_supabase(table)}, d1 {rows[0]['n']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
