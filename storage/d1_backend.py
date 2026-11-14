"""Tables on Cloudflare D1 behind the repositories' PostgREST calls.

Both repositories send every call through ``self.session.request(method, url,
...)`` against PostgREST. ``table_session()`` hands them the session for
``TABLE_BACKEND``:

* ``supabase`` (also unset or ""): a plain ``requests.Session``, as before.
* ``dual``: writes go to Supabase, then to D1, where an error is logged and never
  fails the run; reads go to Supabase.
* ``d1``: D1 alone.

The D1 session turns the small part of PostgREST the repositories use into one
SQLite statement per call (`translate`) and runs it through D1's REST API. A bulk
upsert is one statement with one parameter, a JSON array read by ``json_each``,
so it stays inside D1's 100-parameter and 100 KB statement limits. An update that
changes nothing (``updated_at`` aside) is not written, which is what keeps a
re-sent run inside the Free plan's 100k rows written a day.
"""

from __future__ import annotations

import contextlib
import csv
import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import requests

logger = logging.getLogger(__name__)

BACKENDS = ("supabase", "dual", "d1")
D1_API = "https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query"
# D1 refuses a string over 2 MB; a bulk write's JSON array is split below that.
MAX_PAYLOAD_BYTES = 1_500_000
DEFAULT_MAX_ROWS_WRITTEN = 90_000
WRITE_METHODS = {"POST", "PATCH", "DELETE"}
# A column the writer stamps on every run; a row equal in all else is unchanged.
STAMP_COLUMN = "updated_at"
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_COMPARISONS = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}

Statement = tuple[str, list[Any]]
Executor = Callable[[str, str, list[Any]], tuple[list[dict[str, Any]], int]]


class UnsupportedQuery(ValueError):
    """A PostgREST feature with no D1 form yet (an embedded resource, an RPC)."""


def backend_name(env: Mapping[str, str] | None = None) -> str:
    name = str((os.environ if env is None else env).get("TABLE_BACKEND") or "supabase").strip().lower()
    if name not in BACKENDS:
        raise ValueError(f"TABLE_BACKEND must be one of {BACKENDS}, not {name!r}")
    return name


def table_session(env: Mapping[str, str] | None = None) -> requests.Session:
    """The session a repository sends its PostgREST calls through."""
    env = os.environ if env is None else env
    name = backend_name(env)
    if name == "supabase":
        return requests.Session()
    d1 = D1Session(rest_executor(env), max_rows_written=int(env.get("D1_MAX_ROWS_WRITTEN") or DEFAULT_MAX_ROWS_WRITTEN))
    return DualSession(requests.Session(), d1) if name == "dual" else d1


# -- PostgREST -> SQLite ----------------------------------------------------


def _name(value: str) -> str:
    if not _IDENTIFIER.match(value):
        raise UnsupportedQuery(f"not a plain column or table name: {value!r}")
    return f'"{value}"'


def _in_list(value: str) -> list[str]:
    inner = value.strip()
    if not (inner.startswith("(") and inner.endswith(")")):
        raise UnsupportedQuery(f"bad in-list: {value!r}")
    return next(csv.reader([inner[1:-1]], skipinitialspace=True), [])


def _condition(column: str, expression: str) -> Statement:
    negate = expression.startswith("not.")
    if negate:
        expression = expression[4:]
    op, _, value = expression.partition(".")
    target = _name(column)
    if op in _COMPARISONS:
        sql, args = f"{target} {_COMPARISONS[op]} ?", [value]
    elif op == "like":
        sql, args = f"{target} LIKE ?", [value.replace("*", "%")]
    elif op == "in":
        items = _in_list(value)
        sql, args = f"{target} IN ({', '.join('?' * len(items))})", items
        if not items:
            sql = "0"
    elif op == "is":
        literal = {"null": "NULL", "true": "1", "false": "0"}.get(value.lower())
        if literal is None:
            raise UnsupportedQuery(f"is.{value}")
        sql, args = (f"{target} IS NULL" if literal == "NULL" else f"{target} = {literal}"), []
    else:
        raise UnsupportedQuery(f"filter operator {op!r}")
    return (f"NOT ({sql})" if negate else sql), args


def _where(filters: list[tuple[str, str]]) -> Statement:
    parts, args = [], []
    for column, expression in filters:
        sql, values = _condition(column, expression)
        parts.append(sql)
        args.extend(values)
    return (" WHERE " + " AND ".join(parts) if parts else ""), args


def _order(value: str) -> str:
    terms = []
    for term in value.split(","):
        column, *modifiers = term.strip().split(".")
        descending = "desc" in modifiers
        # PostgREST's defaults: nulls last ascending, first descending.
        nulls = "FIRST" if "nullsfirst" in modifiers or (descending and "nullslast" not in modifiers) else "LAST"
        terms.append(f"{_name(column)} {'DESC' if descending else 'ASC'} NULLS {nulls}")
    return ", ".join(terms)


def _select(value: str | None) -> str:
    if not value or value.strip() == "*":
        return "*"
    if "(" in value or "->" in value or ":" in value:
        raise UnsupportedQuery(f"select {value!r}: embedded resources, aliases and JSON paths have no D1 form yet")
    return ", ".join(_name(column.strip()) for column in value.split(","))


def _rows_body(body: Any) -> list[dict[str, Any]]:
    rows = body if isinstance(body, list) else [body]
    if not all(isinstance(row, dict) for row in rows):
        raise UnsupportedQuery("a write body must be an object or a list of objects")
    return rows


def _insert(table: str, rows: list[dict[str, Any]], resolution: str | None, conflict: str | None) -> Statement:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    names = ", ".join(_name(column) for column in columns)
    values = ", ".join(f"json_extract(value, '$.\"{column}\"')" for column in columns)
    sql = f"INSERT INTO {_name(table)} ({names}) SELECT {values} FROM json_each(?) WHERE true"
    if resolution == "ignore-duplicates":
        sql += " ON CONFLICT DO NOTHING"
    elif resolution == "merge-duplicates":
        if not conflict:
            raise UnsupportedQuery(f"an upsert into {table} needs on_conflict")
        keys = [key.strip() for key in conflict.split(",")]
        rest = [column for column in columns if column not in keys]
        target = f"{_name(table)}."
        if rest:
            changes = " OR ".join(
                f"{target}{_name(column)} IS NOT excluded.{_name(column)}" for column in rest if column != STAMP_COLUMN
            ) or "0"
            sets = ", ".join(f"{_name(column)} = excluded.{_name(column)}" for column in rest)
            sql += f" ON CONFLICT ({', '.join(_name(key) for key in keys)}) DO UPDATE SET {sets} WHERE {changes}"
        else:
            sql += " ON CONFLICT DO NOTHING"
    return sql, [json.dumps(rows, default=str)]


def translate(method: str, url: str, params: Mapping[str, Any] | None, body: Any, prefer: str = "") -> Statement:
    """One PostgREST call as one SQLite statement and its arguments."""
    parts = urlsplit(url)
    path = parts.path.rsplit("/rest/v1/", 1)[-1].strip("/")
    if path.startswith("rpc/"):
        raise UnsupportedQuery(f"{path} has no D1 form yet")
    table = _name(path)
    query = [*parse_qsl(parts.query, keep_blank_values=True), *((params or {}).items())]
    controls = {key: str(value) for key, value in query if key in {"select", "order", "limit", "offset", "on_conflict"}}
    filters = [(key, str(value)) for key, value in query if key not in controls]
    returning = " RETURNING *" if "return=representation" in prefer else ""
    if method == "GET":
        where, args = _where(filters)
        sql = f"SELECT {_select(controls.get('select'))} FROM {table}{where}"
        if "order" in controls:
            sql += f" ORDER BY {_order(controls['order'])}"
        if "limit" in controls or "offset" in controls:
            sql += " LIMIT ? OFFSET ?"
            args += [int(controls.get("limit", -1)), int(controls.get("offset", 0))]
        return sql, args
    if method == "POST":
        resolution = next((part.split("=", 1)[1] for part in prefer.split(",") if part.strip().startswith("resolution=")), None)
        sql, args = _insert(path, _rows_body(body), resolution and resolution.strip(), controls.get("on_conflict"))
        return sql + returning, args
    if method == "PATCH":
        if not isinstance(body, dict) or not body:
            raise UnsupportedQuery("PATCH needs an object body")
        where, args = _where(filters)
        sets = ", ".join(f"{_name(column)} = ?" for column in body)
        values = [json.dumps(value) if isinstance(value, (dict, list)) else value for value in body.values()]
        return f"UPDATE {table} SET {sets}{where}{returning}", values + args
    if method == "DELETE":
        where, args = _where(filters)
        if not where:
            raise UnsupportedQuery(f"refusing an unfiltered DELETE on {path}")
        return f"DELETE FROM {table}{where}{returning}", args
    raise UnsupportedQuery(f"method {method}")


def _split(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Rows in groups whose JSON stays under D1's string limit."""
    groups, group, size = [], [], 0
    for row in rows:
        length = len(json.dumps(row, default=str))
        if group and size + length > MAX_PAYLOAD_BYTES:
            groups.append(group)
            group, size = [], 0
        group.append(row)
        size += length
    return [*groups, group] if group else groups


def _decoded(row: dict[str, Any]) -> dict[str, Any]:
    # shortcut: any text holding a JSON object or array is read back as JSON, since D1
    # stores jsonb as text; upgrade to the column types once storage/d1/*.sql exists.
    out = {}
    for key, value in row.items():
        if isinstance(value, str) and value[:1] in "{[":
            with contextlib.suppress(ValueError):
                value = json.loads(value)
        out[key] = value
    return out


# -- sessions ----------------------------------------------------------------


def _response(status: int, payload: Any = None, text: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = (text if text is not None else ("" if payload is None else json.dumps(payload, default=str))).encode()
    response.headers["Content-Type"] = "application/json"
    return response


class D1Session:
    """A stand-in for ``requests.Session`` that answers PostgREST calls from D1."""

    def __init__(self, execute: Executor, *, max_rows_written: int = DEFAULT_MAX_ROWS_WRITTEN):
        self.execute = execute
        self.max_rows_written = max_rows_written
        # shortcut: the ceiling counts this process's writes, not the account's day;
        # upgrade to D1's analytics API if two writers ever share a day's budget.
        self.rows_written = 0

    def request(self, method: str, url: str, *, params=None, json=None, headers=None, **_: Any) -> requests.Response:
        method = method.upper()
        prefer = (headers or {}).get("Prefer", "")
        table = urlsplit(url).path.rsplit("/", 1)[-1]
        try:
            if method in WRITE_METHODS and self.rows_written >= self.max_rows_written:
                raise RuntimeError(
                    f"D1 write ceiling reached: {self.rows_written} rows written by this run "
                    f"(D1_MAX_ROWS_WRITTEN={self.max_rows_written})"
                )
            bodies = _split(_rows_body(json)) if method == "POST" else [json]
            found: list[dict[str, Any]] = []
            for body in bodies:
                sql, args = translate(method, url, params, body, prefer)
                rows, written = self.execute(table, sql, args)
                self.rows_written += written
                found.extend(_decoded(row) for row in rows)
        except UnsupportedQuery as exc:
            return _response(400, text=f"D1 backend: {exc}")
        if method == "GET" or "return=representation" in prefer:
            return _response(200, found)
        return _response(201 if method == "POST" else 204)


class DualSession:
    """Supabase stays the system of record; D1 receives a copy of every write."""

    def __init__(self, primary: requests.Session, mirror: D1Session):
        self.primary = primary
        self.mirror = mirror

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        response = self.primary.request(method, url, **kwargs)
        if method.upper() in WRITE_METHODS and response.ok:
            try:
                copy = self.mirror.request(method, url, **kwargs)
                if not copy.ok:
                    logger.warning("D1 copy of %s %s refused: %s", method, urlsplit(url).path, copy.text[:300])
            except Exception as exc:  # noqa: BLE001 - the copy never fails the run
                logger.warning("D1 copy of %s %s failed: %s", method, urlsplit(url).path, exc)
        return response


def rest_executor(env: Mapping[str, str]) -> Executor:
    """Run one statement through D1's REST API, in the table's database."""
    account, token = env.get("D1_ACCOUNT_ID", ""), env.get("D1_API_TOKEN", "")
    default = env.get("D1_DATABASE_ID", "")
    if not (account and token and default):
        raise ValueError("TABLE_BACKEND=d1|dual needs D1_ACCOUNT_ID, D1_API_TOKEN and D1_DATABASE_ID")
    # "table:id,table:id" for a table kept in another database (history, evidence).
    per_table = dict(
        item.split(":", 1) for item in str(env.get("D1_TABLE_DATABASES") or "").split(",") if ":" in item
    )
    http = requests.Session()
    http.headers.update({"Authorization": f"Bearer {token}"})
    timeout = int(env.get("D1_TIMEOUT_SECONDS") or 60)

    def execute(table: str, sql: str, args: list[Any]) -> tuple[list[dict[str, Any]], int]:
        url = D1_API.format(account=account, database=per_table.get(table, default))
        reply = http.post(url, json={"sql": sql, "params": args}, timeout=timeout)
        payload = reply.json() if reply.content else {}
        if not reply.ok or not payload.get("success"):
            raise RuntimeError(f"D1 {reply.status_code}: {payload.get('errors') or reply.text[:300]}")
        result = (payload.get("result") or [{}])[0]
        return result.get("results") or [], int((result.get("meta") or {}).get("rows_written") or 0)

    return execute
