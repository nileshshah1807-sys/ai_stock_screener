/**
 * The part of supabase-js's query builder the dashboard's reads use, for a
 * table that lives in Cloudflare D1 or an R2 object instead of Supabase.
 *
 * `TableQuery` records the calls (`select`, `eq`, `or`, `order`, `range`,
 * `maybeSingle`...) into a plan and, when awaited, hands it to the executor it
 * was built with; the answer has supabase-js's shape (`{ data, error, count }`),
 * so a reader written against Supabase reads D1 unchanged. `compile` turns a
 * plan into SQLite for D1; `evaluate` applies it to rows already in memory (the
 * R2 live objects). Anything outside the subset throws `UnsupportedQuery`
 * rather than being guessed, as storage/d1_backend.py does on the Python side.
 *
 * `hide(column)` names the columns this viewer may not read (ratings, for a
 * non-admin). A hidden column is NULL wherever it appears -- selected, filtered
 * or sorted on -- exactly as the `*_visible` views null it, so filtering on it
 * cannot reveal it, and its value is never fetched.
 */

export class UnsupportedQuery extends Error {}

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const COMPARISONS = { eq: "=", neq: "<>", gt: ">", gte: ">=", lt: "<", lte: "<=" };
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;

function name(value) {
  if (!NAME.test(value)) throw new UnsupportedQuery(`not a plain column name: ${value}`);
  return value;
}

/**
 * A filter value as D1 holds it: a boolean as 0/1, a timestamp in UTC.
 * shortcut: a timestamp is cut to the second ("2026-11-14T09:00:00"), and the stored
 * text compares above it within that second, so gt/lte may be off by under a second.
 */
export function bound(value) {
  if (value === true || value === false) return value ? 1 : 0;
  if (typeof value === "string" && TIMESTAMP.test(value)) {
    const time = new Date(value);
    if (!Number.isNaN(time.getTime())) return time.toISOString().slice(0, 19);
  }
  return value;
}

// -- PostgREST filter strings (`or`, `filter`) --------------------------------

/** Split on commas outside parentheses and double quotes. */
function splitTop(text) {
  const parts = [];
  let depth = 0;
  let quoted = false;
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === '"') quoted = !quoted;
    else if (!quoted && ch === "(") depth += 1;
    else if (!quoted && ch === ")") depth -= 1;
    else if (!quoted && depth === 0 && ch === ",") {
      parts.push(text.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(text.slice(start));
  return parts.map((part) => part.trim()).filter(Boolean);
}

/** `(a,"b c")` -> ["a", "b c"]. */
function inList(text) {
  const inner = text.trim();
  if (!inner.startsWith("(") || !inner.endsWith(")")) throw new UnsupportedQuery(`bad in-list: ${text}`);
  return splitTop(inner.slice(1, -1)).map((item) => item.replace(/^"(.*)"$/, "$1"));
}

/** One PostgREST condition, `op` and its raw value, as a plan node. */
function condition(column, op, raw) {
  if (op in COMPARISONS) return { op, column: name(column), value: raw };
  if (op === "in") return { op, column: name(column), value: typeof raw === "string" ? inList(raw) : raw };
  if (op === "like" || op === "ilike") return { op: "like", column: name(column), value: String(raw).replaceAll("*", "%") };
  if (op === "is") {
    const value = raw === null ? null : { null: null, true: true, false: false }[String(raw).toLowerCase()];
    if (value === undefined) throw new UnsupportedQuery(`is.${raw}`);
    return { op, column: name(column), value };
  }
  throw new UnsupportedQuery(`filter operator ${op}`);
}

/** A PostgREST logic string, `a.eq.1,and(b.gt.2,c.is.null)`, as plan nodes. */
function parseLogic(text) {
  return splitTop(text).map((part) => {
    const group = /^(and|or)\((.*)\)$/s.exec(part);
    if (group) return { op: group[1], nodes: parseLogic(group[2]) };
    const [column, ...rest] = part.split(".");
    const negate = rest[0] === "not";
    const [op, ...value] = negate ? rest.slice(1) : rest;
    const node = condition(column, op, value.join("."));
    return negate ? { op: "not", node } : node;
  });
}

// -- select ---------------------------------------------------------------------

/** "a, b:c->d->e" -> [{ name: "a", column: "a", path: [] }, { name: "b", column: "c", path: ["d", "e"] }]. */
export function parseSelect(text) {
  if (/[()]|::/.test(text)) throw new UnsupportedQuery(`select ${text}: embedded resources and casts have no D1 form`);
  return splitTop(text).map((item) => {
    const [alias, expression] = item.includes(":") ? item.split(":", 2) : [null, item];
    const [column, ...path] = expression.split(/->>?/).map((part) => name(part.trim()));
    return { name: name((alias ?? path.at(-1) ?? column).trim()), column, path };
  });
}

// -- the builder ------------------------------------------------------------------

export class TableQuery {
  /**
   * @param {(plan: any) => Promise<{ rows: object[], count: number | null }>} execute
   */
  constructor(execute) {
    this.execute = execute;
    this.plan = { columns: "*", filters: [], orders: [], offset: 0, limit: null, count: false, head: false, single: null };
  }

  select(columns = "*", options = {}) {
    if (options.count && options.count !== "exact") throw new UnsupportedQuery(`count: ${options.count}`);
    this.plan.columns = columns;
    this.plan.count = options.count === "exact";
    this.plan.head = Boolean(options.head);
    return this;
  }

  #add(node) {
    this.plan.filters.push(node);
    return this;
  }

  eq(column, value) { return this.#add(condition(column, "eq", value)); }
  neq(column, value) { return this.#add(condition(column, "neq", value)); }
  gt(column, value) { return this.#add(condition(column, "gt", value)); }
  gte(column, value) { return this.#add(condition(column, "gte", value)); }
  lt(column, value) { return this.#add(condition(column, "lt", value)); }
  lte(column, value) { return this.#add(condition(column, "lte", value)); }
  in(column, values) { return this.#add(condition(column, "in", [...values])); }
  is(column, value) { return this.#add(condition(column, "is", value)); }
  like(column, pattern) { return this.#add(condition(column, "like", pattern)); }
  ilike(column, pattern) { return this.#add(condition(column, "ilike", pattern)); }
  not(column, op, value) { return this.#add({ op: "not", node: condition(column, op, value) }); }
  filter(column, op, value) { return this.#add(parseLogic(`${column}.${op}.${value}`)[0]); }
  or(text) { return this.#add({ op: "or", nodes: parseLogic(text) }); }
  match(values) {
    for (const [column, value] of Object.entries(values)) this.eq(column, value);
    return this;
  }

  order(column, { ascending = true, nullsFirst } = {}) {
    // PostgREST's default: nulls last ascending, first descending.
    this.plan.orders.push({ column: name(column), ascending, nullsFirst: nullsFirst ?? !ascending });
    return this;
  }

  range(from, to) {
    this.plan.offset = from;
    this.plan.limit = to - from + 1;
    return this;
  }

  limit(count) {
    this.plan.limit = count;
    return this;
  }

  maybeSingle() {
    this.plan.single = "maybe";
    return this;
  }

  single() {
    this.plan.single = "one";
    return this;
  }

  async run() {
    try {
      const { rows, count } = await this.execute(this.plan);
      if (this.plan.single) {
        if (rows.length > 1 || (this.plan.single === "one" && rows.length === 0)) {
          return { data: null, error: { message: `expected one row, got ${rows.length}`, code: "PGRST116" }, count, status: 406 };
        }
        return { data: rows[0] ?? null, error: null, count, status: 200 };
      }
      return { data: this.plan.head ? null : rows, error: null, count, status: 200 };
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      return { data: null, error: { message, code: cause instanceof UnsupportedQuery ? "UNSUPPORTED" : "D1" }, count: null, status: 500 };
    }
  }

  then(resolve, reject) {
    return this.run().then(resolve, reject);
  }
}

// -- SQL for D1 ---------------------------------------------------------------

function sqlNode(node, ref) {
  if (node.op === "and" || node.op === "or") {
    const parts = node.nodes.map((child) => sqlNode(child, ref));
    return { sql: `(${parts.map((part) => part.sql).join(` ${node.op.toUpperCase()} `)})`, args: parts.flatMap((part) => part.args) };
  }
  if (node.op === "not") {
    const inner = sqlNode(node.node, ref);
    return { sql: `NOT (${inner.sql})`, args: inner.args };
  }
  const column = ref(node.column);
  if (node.op in COMPARISONS) return { sql: `${column} ${COMPARISONS[node.op]} ?`, args: [bound(node.value)] };
  // One parameter whatever the list's length: D1 allows 100 per statement.
  if (node.op === "in") return { sql: `${column} IN (SELECT value FROM json_each(?))`, args: [JSON.stringify(node.value.map(bound))] };
  // shortcut: SQLite's LIKE ignores ASCII case, so a like is an ilike; no reader needs a case-sensitive match yet.
  if (node.op === "like") return { sql: `${column} LIKE ?`, args: [node.value] };
  if (node.op === "is") return { sql: node.value === null ? `${column} IS NULL` : `${column} = ${node.value ? 1 : 0}`, args: [] };
  throw new UnsupportedQuery(`filter operator ${node.op}`);
}

/**
 * The plan as SQLite: `data` for the rows (absent for a head request) and
 * `count` for an exact count. `from` is a quoted table name or a subquery.
 *
 * @param {object} plan
 * @param {string} from
 * @param {(column: string) => boolean} [hide]
 */
export function compile(plan, from, hide = () => false) {
  const ref = (column) => (hide(column) ? "NULL" : `"${name(column)}"`);
  const where = plan.filters.map((node) => sqlNode(node, ref));
  const whereSql = where.length ? ` WHERE ${where.map((part) => part.sql).join(" AND ")}` : "";
  const args = where.flatMap((part) => part.args);
  const out = {};
  if (!plan.head) {
    const all = plan.columns.trim() === "*";
    if (all && hide("*")) throw new UnsupportedQuery("select * of a rating-gated table: name the columns");
    const columns = all
      ? "*"
      : parseSelect(plan.columns)
          .map(({ name: as, column, path }) => {
            const value = hide(column) ? "NULL" : path.length ? `json_extract("${column}", '$.${path.join(".")}')` : `"${column}"`;
            return `${value} AS "${as}"`;
          })
          .join(", ");
    const order = plan.orders.length
      ? ` ORDER BY ${plan.orders.map((o) => `${ref(o.column)} ${o.ascending ? "ASC" : "DESC"} NULLS ${o.nullsFirst ? "FIRST" : "LAST"}`).join(", ")}`
      : "";
    const limit = plan.limit !== null ? Number(plan.limit) : plan.offset ? -1 : null;
    const page = limit !== null ? ` LIMIT ${limit} OFFSET ${Number(plan.offset)}` : "";
    out.data = { sql: `SELECT ${columns} FROM ${from}${whereSql}${order}${page}`, args };
  }
  if (plan.count) out.count = { sql: `SELECT COUNT(*) AS "n" FROM ${from}${whereSql}`, args };
  return out;
}

/**
 * A D1 row as supabase-js would have returned it: `booleans` back to true/false,
 * JSON text back to values.
 * shortcut: any text that opens with { or [ is read as JSON, since D1 holds jsonb as text
 * (as storage/d1_backend.py reads it); give the tables a column-type map if a text column ever opens so.
 */
export function decode(row, booleans) {
  const out = {};
  for (const [key, value] of Object.entries(row)) {
    if (booleans.has(key) && (value === 0 || value === 1)) out[key] = value === 1;
    else if (typeof value === "string" && (value[0] === "{" || value[0] === "[")) {
      try {
        out[key] = JSON.parse(value);
      } catch {
        out[key] = value;
      }
    } else out[key] = value;
  }
  return out;
}

// -- in memory, for the R2 objects ------------------------------------------------

const likeRegExp = (pattern) =>
  new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replaceAll("%", ".*").replaceAll("_", ".")}$`, "is");

const compare = (a, b) => (a === b ? 0 : a < b ? -1 : 1);

function matches(node, row) {
  if (node.op === "and") return node.nodes.every((child) => matches(child, row));
  if (node.op === "or") return node.nodes.some((child) => matches(child, row));
  if (node.op === "not") return !matches(node.node, row);
  const value = row[node.column] ?? null;
  if (node.op === "is") return node.value === null ? value === null : value === node.value;
  if (value === null) return false;
  if (node.op === "in") return node.value.some((item) => String(item) === String(value));
  if (node.op === "like") return likeRegExp(node.value).test(String(value));
  const order = typeof value === "number" ? compare(value, Number(node.value)) : compare(String(value), String(node.value));
  return { eq: order === 0, neq: order !== 0, gt: order > 0, gte: order >= 0, lt: order < 0, lte: order <= 0 }[node.op];
}

/** The plan applied to `rows` in memory: what `compile` would return from a table of them. */
export function evaluate(plan, rows) {
  const kept = rows.filter((row) => plan.filters.every((node) => matches(node, row)));
  kept.sort((a, b) => {
    for (const { column, ascending, nullsFirst } of plan.orders) {
      const x = a[column] ?? null;
      const y = b[column] ?? null;
      if (x === y) continue;
      if (x === null || y === null) return (x === null) === nullsFirst ? -1 : 1;
      return ascending ? compare(x, y) : compare(y, x);
    }
    return 0;
  });
  const page = kept.slice(plan.offset, plan.limit === null ? undefined : plan.offset + plan.limit);
  const columns = plan.columns.trim() === "*" ? null : parseSelect(plan.columns);
  const data = columns
    ? page.map((row) =>
        Object.fromEntries(columns.map(({ name: as, column, path }) => [as, path.reduce((at, key) => at?.[key] ?? null, row[column] ?? null)])),
      )
    : page;
  return { rows: plan.head ? [] : data, count: plan.count ? kept.length : null };
}
