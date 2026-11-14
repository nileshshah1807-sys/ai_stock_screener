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
            "market_breadth", "screener_runs", "screener_snapshot",
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

D1_MAX_COLUMNS = 100

#: Each table's primary key in Postgres's own order (pg_index, 14 Nov 2026), which
#: PostgREST's description does not keep. A WITHOUT ROWID table is stored in key
#: order, so this decides which reads are a range and which a scan. ``schema``
#: refuses a table whose key columns differ from Supabase's.
KEY_ORDER: dict[str, tuple[str, ...]] = {
    "bulk_block_deals": ("market", "kind", "deal_date", "symbol", "client_name", "side", "quantity", "price"),
    "company_documents": ("market", "symbol", "kind", "url"),
    "concall_feed": ("market", "symbol", "quarter"),
    "estimate_history": ("market", "symbol", "fetched_at"),
    "financial_statements": ("market", "symbol"),
    "market_breadth": ("market", "scope", "name"),
    "market_events": ("id",),
    "new_listings": ("market", "symbol"),
    "quarterly_filings": ("market", "symbol", "period_end", "is_consolidated"),
    "red_flag_snapshots": ("source", "symbol"),
    "screener_history": ("market", "observed_on", "symbol"),
    "screener_runs": ("market", "run_date"),
    "screener_snapshot": ("market", "run_date", "symbol"),
    "shareholding_patterns": ("market", "symbol", "period_end"),
    "transcript_documents": ("id",),
    "transcript_outlooks": ("id",),
    "transcript_sentiments": ("id",),
    "transcripts": ("id",),
    "universe_index": ("market", "observed_on"),
    "upcoming_events": ("market", "symbol"),
    "valuation_basis": ("market", "symbol"),
}

#: Secondary indexes, each one more row written per row: only where a reader
#: needs a range the key cannot give. One stock's history, newest first.
INDEXES: dict[str, tuple[str, ...]] = {
    "screener_history": (
        'CREATE INDEX IF NOT EXISTS "screener_history_symbol_idx" '
        'ON "screener_history" ("market", "symbol", "observed_on");',
    ),
}

#: Laid out by hand (Dwight, 14 Nov 2026): 156 columns pass D1's 100. Its real
#: columns are the file's; every other column goes into the "extra" JSON object,
#: and "payload" (in Storage since Oct 2026) is not carried.
HAND_LAID = {"screener_snapshot": Path("storage/d1/screener_snapshot.sql")}
EXTRA_COLUMN = "extra"
SKIPPED_COLUMNS = {"screener_snapshot": {"payload"}}

#: D1 keeps only what the pages read of history; the full rows are archived in R2
#: (human, 14 Nov 2026: option a).
HISTORY_COLUMNS = (
    "market", "observed_on", "symbol", "company", "current_price", "volume", "stage",
    "investment_rank", "rating", "decision_score", "final_score", "fundamental_score",
    "technical_score", "advance_age_days", "market_cap",  # the Returns page's pick filters
)
COLUMNS: dict[str, tuple[str, ...]] = {"screener_history": HISTORY_COLUMNS}

SCHEMA_DIR = Path("storage/d1")
PAGE = 500
DEFAULT_MAX_ROWS_WRITTEN = 75_000

_AFFINITY = {
    "integer": "INTEGER", "bigint": "INTEGER", "smallint": "INTEGER", "boolean": "INTEGER",
    "numeric": "REAL", "double precision": "REAL", "real": "REAL",
}
_NOW = "(strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))"  # Supabase's own form


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


def primary_key(table: str, definition: dict[str, Any]) -> list[str]:
    described = {c for c, spec in definition["properties"].items() if "<pk/>" in str(spec.get("description") or "")}
    keys = list(KEY_ORDER.get(table, ()))
    if not described or set(keys) != described:
        raise ValueError(f"{table}: key {sorted(described)} in Supabase, {keys} in KEY_ORDER")
    return keys


def real_columns(table: str) -> list[str]:
    """A hand-laid table's real columns, read from its CREATE TABLE."""
    body = HAND_LAID[table].read_text().split("CREATE TABLE", 1)[1].split(") WITHOUT ROWID", 1)[0]
    return [line.split('"')[1] for line in body.splitlines() if line.startswith('    "')]


def to_d1(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """A Supabase row as its D1 table holds it."""
    if table not in HAND_LAID:
        return row
    real = set(real_columns(table)) - {EXTRA_COLUMN}
    skipped = SKIPPED_COLUMNS.get(table, set())
    extra = {key: value for key, value in row.items() if key not in real and key not in skipped}
    return {**{key: row[key] for key in real if key in row}, EXTRA_COLUMN: json.dumps(extra, separators=(",", ":"))}


def table_ddl(table: str, definition: dict[str, Any]) -> str:
    wanted = COLUMNS.get(table)
    required = set(definition.get("required") or ())
    keys = primary_key(table, definition)
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
    indexes = "".join(f"{index}\n" for index in INDEXES.get(table, ()))
    return f'CREATE TABLE IF NOT EXISTS "{table}" (\n' + ",\n".join(lines) + "\n) WITHOUT ROWID;\n" + indexes


def write_schema(definitions: dict[str, Any]) -> list[Path]:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for database in sorted(set(TABLES.values())):
        tables = [table for table in sorted(TABLES) if TABLES[table] == database and table not in HAND_LAID]
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
        files = [SCHEMA_DIR / f"{database}.sql", *(path for table, path in HAND_LAID.items() if TABLES[table] == database)]
        for path in files:
            for statement in statements(path.read_text()):
                execute(route, statement, [])


def _page(table: str, keys: list[str], offset: int, columns: list[str] | None = None) -> list[dict[str, Any]]:
    base, headers = _supabase()
    params = {"order": ",".join(f"{key}.asc" for key in keys), "limit": str(PAGE), "offset": str(offset)}
    if columns:
        params["select"] = ",".join(columns)
    reply = requests.get(f"{base}/{table}", params=params, headers=headers, timeout=120)
    reply.raise_for_status()
    return reply.json()


class FileState:
    """Progress in a local JSON file (a run by hand)."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text()) if self.path.exists() else {"tables": {}, "days": {}}

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=1))


STATE_TABLE = "d1_backfill_state"


class D1State:
    """Progress in one row of cupel-core, so a fresh runner resumes (the workflow).

    One row written per page, a few hundred a day.
    """

    def __init__(self, execute):
        self.execute = execute
        execute("concall_feed", f'CREATE TABLE IF NOT EXISTS "{STATE_TABLE}" (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;', [])

    def load(self) -> dict[str, Any]:
        rows, _ = self.execute("concall_feed", f'SELECT value FROM "{STATE_TABLE}" WHERE key = ?', ["state"])
        return json.loads(rows[0]["value"]) if rows else {"tables": {}, "days": {}}

    def save(self, state: dict[str, Any]) -> None:
        self.execute(
            "concall_feed",
            f'INSERT INTO "{STATE_TABLE}" (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value',
            ["state", json.dumps(state, separators=(",", ":"))],
        )


#: The order the backfill copies in (docs/d1_migration_plan.md section 6), history last.
ORDER = (
    "concall_feed", "valuation_basis", "bulk_block_deals",
    "quarterly_filings", "financial_statements", "upcoming_events", "market_events",
    "new_listings", "universe_index", "market_breadth",
    "shareholding_patterns", "company_documents", "transcripts", "transcript_documents",
    "transcript_sentiments", "transcript_outlooks", "estimate_history", "red_flag_snapshots",
    "screener_runs", "screener_snapshot", "screener_history",
)
#: A table re-read from the start when D1 ends up short of Supabase (a row deleted
#: before the offset between two days of paging), at most this many times.
MAX_PASSES = 3
REPASS_MAX_WRITTEN_SHARE = 0.05  # of the rows a pass 2 or 3 sends


def _columns(table: str, definition: dict[str, Any]) -> list[str] | None:
    if table in COLUMNS:
        return list(COLUMNS[table])
    if table in SKIPPED_COLUMNS:
        return [c for c in definition["properties"] if c not in SKIPPED_COLUMNS[table]]
    return None


def write_cost(table: str) -> int:
    """Rows D1 counts as written for one new row: the row and one per index."""
    hand = HAND_LAID.get(table)
    laid = hand.read_text().upper().count("CREATE INDEX") if hand else 0
    return 1 + len(INDEXES.get(table, ())) + laid


def backfill(
    tables: list[str], session: D1Session, store, definitions: dict[str, Any], fetch=_page, counts=None
) -> int:
    """Copy each table on from where the state left it. 0 when done, 2 at the day's ceiling,
    1 when a re-read rewrote unchanged rows (the table is stopped, not the run).

    ``counts(table) -> (supabase, d1)``, when given, checks a finished table: D1
    short of Supabase means a row was skipped, so the table is read again.
    """
    state = store.load()
    day = datetime.now(UTC).date().isoformat()
    already = int(state["days"].get(day, 0))
    session.max_rows_written = max(0, session.max_rows_written - already)
    status = 0
    try:
        for table in tables:
            keys = primary_key(table, definitions[table])
            columns = _columns(table, definitions[table])
            progress = state["tables"].setdefault(table, {"offset": 0, "done": False})
            while not progress["done"]:
                rows = [to_d1(table, row) for row in fetch(table, keys, progress["offset"], columns)]
                before = session.rows_written
                if rows:
                    session.request(
                        "POST",
                        f"https://d1/rest/v1/{table}?on_conflict={','.join(keys)}",
                        json=rows,
                        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                    ).raise_for_status()
                progress["offset"] += len(rows)
                progress["sent"] = progress.get("sent", 0) + len(rows)
                progress["written"] = progress.get("written", 0) + session.rows_written - before
                progress["done"] = len(rows) < PAGE
                allowed = progress.get("missing", 0) * write_cost(table) + REPASS_MAX_WRITTEN_SHARE * progress["sent"]
                if progress.get("pass", 1) > 1 and progress["written"] > allowed:
                    # A re-read should write only the missing rows; more means a column
                    # re-serializes differently, and every reread would spend the day on it.
                    print(f"{table}: pass {progress['pass']} wrote {progress['written']} of {progress['sent']} rows "
                          "sent, so unchanged rows are being rewritten; stopped, find the column", file=sys.stderr)
                    progress.update({"done": True, "stalled": True})
                    status = 1
                if progress["done"]:
                    print(f"{table}: pass {progress.get('pass', 1)} sent {progress['sent']}, wrote {progress['written']}")
                if progress["done"] and counts is not None and not progress.get("stalled"):
                    source, copied = counts(table)
                    progress["counts"] = [source, copied]
                    if copied < source and progress.get("pass", 1) < MAX_PASSES:
                        progress.update({"offset": 0, "done": False, "pass": progress.get("pass", 1) + 1,
                                         "sent": 0, "written": 0, "missing": source - copied})
                state["days"][day] = already + session.rows_written
                store.save(state)
            print(f"{table}: {progress['offset']} rows read")
    except WriteCeilingReached as exc:
        print(f"Stopped at the day's write budget ({exc}); resume after 00:00 UTC", file=sys.stderr)
        status = status or 2  # a stalled table (1) stays red
    state["days"][day] = already + session.rows_written
    store.save(state)
    print(f"rows written today: {state['days'][day]}")
    if status == 0 and all(state["tables"].get(table, {}).get("done") for table in tables):
        print("backfill complete, nothing left")
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
    parser.add_argument(
        "--state", default="reports_advanced/d1_backfill.json", help='a JSON file, or "d1" for the state table in cupel-core'
    )
    parser.add_argument("--max-rows-written", type=int, default=DEFAULT_MAX_ROWS_WRITTEN)
    args = parser.parse_args(argv)
    unknown = sorted(set(args.tables) - set(TABLES) - {"all"})
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
        tables = list(ORDER) if args.tables == ["all"] else args.tables

        def counts(table: str) -> tuple[int, int]:
            return count_supabase(table), count_d1(execute, table)

        session = D1Session(execute, max_rows_written=args.max_rows_written)
        store = D1State(execute) if args.state == "d1" else FileState(Path(args.state))
        return backfill(tables, session, store, describe(), counts=counts)
    for table in args.tables or list(ORDER):
        source, copied = count_supabase(table), count_d1(execute, table)
        print(f"{table}: supabase {source}, d1 {copied}, remaining {max(0, source - copied)}")
    return 0


def count_d1(execute, table: str) -> int:
    rows, _ = execute(table, f'SELECT count(*) AS n FROM "{table}"', [])
    return int(rows[0]["n"])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
