#!/usr/bin/env node
// Strict, read-only check of the live dashboard, for the weekly audit.
//
//   CREED_DASHBOARD_PASSWORD=... NEXT_PUBLIC_SUPABASE_URL=... \
//   NEXT_PUBLIC_SUPABASE_ANON_KEY=... node scripts/smoke-check.mjs [baseUrl] [--json=path]
//
// Signs in with signInWithPassword (the anon key, like the app) and hands the
// @supabase/ssr cookies to a headless Chrome (scripts/cdp.mjs). Every top-level
// page and Tools tab of /ind and /us, and a sample of stock pages with each of
// their tabs, is then loaded in the browser. A page FAILS on: a non-200 or a
// redirect, a console error, an uncaught exception (hydration errors are one),
// a 4xx/5xx or failed request (Supabase included), a load over 10 s, an empty
// table or chart, an all-blank table column, or NaN / undefined / Invalid Date
// on screen. Also failed: a header run date that is not the latest
// screener_runs date, a screener grid under 90% of row_count, and live prices
// that are not from today's session while the market is open. WARN sentences
// (a quiet day) print but do not fail. Exit 1 on any FAIL; a JSON summary is
// written for Creed. Reads only; never prints the password.
import { writeFileSync } from "node:fs";

import { createServerClient } from "@supabase/ssr";

import { launchChrome } from "./cdp.mjs";

const EMAIL = process.env.CREED_DASHBOARD_EMAIL ?? "creed.audit@example.com";
const args = process.argv.slice(2);
const JSON_PATH = args.find((a) => a.startsWith("--json="))?.slice(7) ?? "smoke-summary.json";
const BASE = (args.find((a) => !a.startsWith("--")) ?? process.env.DASHBOARD_URL ?? "https://win-now.vercel.app").replace(/\/$/, "");
const { NEXT_PUBLIC_SUPABASE_URL: URL_, NEXT_PUBLIC_SUPABASE_ANON_KEY: ANON, CREED_DASHBOARD_PASSWORD: PASSWORD } = process.env;

if (!URL_ || !ANON || !PASSWORD) {
  console.error("Set NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY and CREED_DASHBOARD_PASSWORD.");
  process.exit(2);
}

const MARKETS = {
  ind: { code: "NSE", zone: "Asia/Kolkata", open: [9 * 60 + 15, 15 * 60 + 30] },
  us: { code: "US", zone: "America/New_York", open: [9 * 60 + 30, 16 * 60] },
};
// Results analysis is NSE-only; the US shows a note, still a 200.
const PAGES = ["", "/market", "/movers", "/indices", "/watchlists", "/notifications", "/health",
  "/concalls", "/results", "/results/analysis", "/returns"];
const SAMPLE_SIZE = 10;
const SLOW_MS = 10_000;
const SETTLE_CAP_MS = 8_000; // polling or live-quote requests may never go quiet
const MIN_GRID_SHARE = 0.9;
const LIVE_MAX_AGE_MIN = 20; // the worker runs every 5 minutes
// The empty-state sentences the app prints (grep ">No " in app/ and components/).
const EMPTY = [
  "No screener run has been published", "No stocks match these filters",
  "No results to analyse", "No index is published", "Run date unavailable",
];
const WARN = ["Nothing measured in this range", "No stocks on this list today"];

const findings = [];
const pages = [];
const fail = (page, cause) => {
  if (findings.some((f) => f.page === page && f.cause === cause)) return;
  findings.push({ level: "FAIL", page, cause });
  console.log(`FAIL ${page}  ${cause}`);
};
const warn = (page, cause) => {
  if (findings.some((f) => f.page === page && f.cause === cause)) return;
  findings.push({ level: "WARN", page, cause });
  console.log(`WARN ${page}  ${cause}`);
};

// ---- sign in -----------------------------------------------------------------
const jar = new Map();
const supabase = createServerClient(URL_, ANON, {
  cookies: {
    getAll: () => [...jar].map(([name, value]) => ({ name, value })),
    setAll: (list) => list.forEach(({ name, value }) => jar.set(name, value)),
  },
});
const { error: signInError } = await supabase.auth.signInWithPassword({ email: EMAIL, password: PASSWORD });
if (signInError) {
  console.error(`Sign-in failed: ${signInError.message}`);
  process.exit(2);
}

// ---- what the data says the pages should show ---------------------------------
const formatDate = (iso) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).replace("Sept", "Sep");

async function expectations(slug) {
  const { code } = MARKETS[slug];
  const { data: run, error } = await supabase.from("screener_runs").select("run_date, price_bar_as_of, row_count")
    .eq("market", code).gt("row_count", 0).order("run_date", { ascending: false }).limit(1).maybeSingle();
  if (error || !run) {
    fail(`/${slug}`, `could not read the latest screener run: ${error?.message ?? "none"}`);
    return null;
  }
  const { data: sample } = await supabase.from("screener_snapshot").select("symbol")
    .eq("market", code).eq("run_date", run.run_date).order("market_cap", { ascending: false, nullsFirst: false }).range(0, 199);
  const symbols = (sample ?? []).map((r) => r.symbol);
  const bse = await supabase.from("screener_snapshot").select("symbol").eq("market", code).eq("run_date", run.run_date).like("symbol", "%.BO").limit(1);
  const recent = await supabase.from("new_listings").select("symbol").eq("market", code).limit(1);
  // Large caps first, two from further down the list, then a BSE-only name and a recent listing.
  const picks = [...symbols.slice(0, 6), symbols[60], symbols[150], bse.data?.[0]?.symbol, recent.data?.[0]?.symbol]
    .filter(Boolean);
  for (const symbol of symbols.slice(6)) {
    if (picks.length >= SAMPLE_SIZE) break;
    if (!picks.includes(symbol)) picks.push(symbol);
  }
  return { run, header: formatDate(run.price_bar_as_of ?? run.run_date), picks: [...new Set(picks)].slice(0, SAMPLE_SIZE) };
}

async function liveFreshness(slug) {
  const { code, zone, open } = MARKETS[slug];
  const { data } = await supabase.from("live_quotes").select("session, fetched_at").eq("market", code).eq("kind", "stock")
    .order("session", { ascending: false }).limit(1);
  const now = new Date();
  const local = new Intl.DateTimeFormat("en-CA", { timeZone: zone, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(now).reduce((acc, p) => ({ ...acc, [p.type]: p.value }), {});
  const minutes = Number(local.hour) * 60 + Number(local.minute);
  const isOpen = !["Sat", "Sun"].includes(local.weekday) && minutes >= open[0] && minutes <= open[1];
  const today = `${local.year}-${local.month}-${local.day}`;
  const row = data?.[0];
  if (!row) return fail(`/${slug}`, "live_quotes has no stock rows");
  const ageMin = Math.round((now - new Date(row.fetched_at)) / 60000);
  console.log(`     /${slug}  live quotes: session ${row.session}, fetched ${ageMin} min ago, market ${isOpen ? "open" : "closed"}`);
  // Holidays are not known here: an open-hours miss on a holiday is a false alarm to rule out by hand.
  if (isOpen && row.session !== today) fail(`/${slug}`, `market open but newest live session is ${row.session}, not ${today}`);
  else if (isOpen && ageMin > LIVE_MAX_AGE_MIN) fail(`/${slug}`, `market open but live quotes are ${ageMin} min old`);
}

// ---- the browser ---------------------------------------------------------------
// Runs inside the page (serialised with toString), so it must be self-contained.
function scanPage() {
  const visible = (el) => el.checkVisibility?.() ?? el.offsetParent !== null;
  const out = { bad: [], emptyTables: [], blankColumns: [], deadCharts: 0, dashes: 0, header: null, gridTotal: null, text: document.body.innerText };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node; (node = walker.nextNode());) {
    const el = node.parentElement;
    if (!el || el.closest("pre, code, script, style, noscript") || !visible(el)) continue;
    const text = node.textContent;
    const hit = text.match(/\b(NaN|undefined)\b|Invalid Date|\[object Object\]/);
    if (hit) out.bad.push(`${hit[0]} in "${text.trim().slice(0, 50)}"`);
    if (text.trim() === "—") out.dashes += 1;
  }
  for (const table of document.querySelectorAll("table")) {
    // A table with no header cells is layout (a chart's container), not data.
    if (!visible(table) || !table.querySelector("th")) continue;
    const rows = [...table.querySelectorAll("tbody tr")].filter(visible);
    const label = table.getAttribute("aria-label") ?? table.querySelector("caption")?.textContent?.trim() ??
      table.closest("section")?.querySelector("h2, h3")?.textContent?.trim() ?? `table ${table.outerHTML.slice(0, 90)}`;
    if (!rows.length) { out.emptyTables.push(label); continue; }
    if (rows.length < 5) continue;
    const headers = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
    for (let col = 0; col < headers.length; col += 1) {
      const cells = rows.map((row) => row.children[col]?.textContent.trim() ?? "");
      const blank = cells.filter((c) => c === "" || /^[-–—]$/.test(c)).length;
      if (blank / cells.length >= 0.95) out.blankColumns.push(`${label}: column "${headers[col] || col}"`);
    }
  }
  for (const svg of document.querySelectorAll("svg")) {
    const box = svg.getBoundingClientRect();
    if (!visible(svg) || box.width < 120 || box.height < 60) continue;
    if (svg.querySelectorAll("path, rect, line, circle, polyline, polygon, text").length < 3) out.deadCharts += 1;
  }
  out.header = document.body.innerText.match(/(\d{2} [A-Z][a-z]{2,3} \d{4})\s*·\s*v/)?.[1] ?? null;
  const grid = document.body.innerText.match(/\d[\d,]*\s*[–-]\s*\d[\d,]*\s+of\s+([\d,]+)/);
  out.gridTotal = grid ? Number(grid[1].replace(/,/g, "")) : null;
  return out;
}

const chrome = await launchChrome();
const cookieUrl = new URL(BASE);
let current = null; // per-navigation collector
chrome.on((message) => {
  if (message.method === "Fetch.requestPaused") return guard(message.params);
  if (!current) return;
  const { method, params } = message;
  if (method === "Network.requestWillBeSent" && params.type !== "WebSocket") {
    current.inflight.add(params.requestId);
    // A redirect reuses the id: keep the URL the page asked for, not where it ended.
    if (!current.requests.has(params.requestId)) current.requests.set(params.requestId, params.request.url);
    current.lastActivity = Date.now();
  } else if (method === "Network.responseReceived") {
    const url = params.response.url;
    if (params.type === "Document" && current.status === null) current.status = params.response.status;
    if (params.response.status >= 400) current.errors.push(`HTTP ${params.response.status} ${shorten(url)}`);
  } else if (method === "Page.loadEventFired") {
    current.loadedAt ??= Date.now();
  } else if (method === "Network.loadingFinished") {
    current.inflight.delete(params.requestId);
    current.lastActivity = Date.now();
  } else if (method === "Network.loadingFailed") {
    current.inflight.delete(params.requestId);
    current.lastActivity = Date.now();
    if (!params.canceled && !params.errorText.startsWith("net::ERR_BLOCKED_BY_CLIENT")) current.errors.push(`request failed (${params.errorText}) ${shorten(current.requests.get(params.requestId) ?? "")}`);
  } else if (method === "Runtime.exceptionThrown") {
    const d = params.exceptionDetails;
    current.errors.push(`uncaught exception: ${(d.exception?.description ?? d.text).split("\n")[0]}`);
  } else if (method === "Runtime.consoleAPICalled" && params.type === "error") {
    const text = params.args.map((a) => a.value ?? a.description ?? "").join(" ").split("\n")[0];
    current.errors.push(`${/hydrat|did not match/i.test(text) ? "hydration error" : "console error"}: ${text.slice(0, 160)}`);
  }
});

// The audit login must write nothing: a Next server action (the notifications
// page marks itself seen on view) is a POST carrying a Next-Action header.
function guard({ requestId, request }) {
  const action = Object.keys(request.headers).some((name) => name.toLowerCase() === "next-action");
  const done = action
    ? chrome.send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" })
    : chrome.send("Fetch.continueRequest", { requestId });
  if (action && current) current.blocked += 1;
  done.catch(() => {});
}

function shorten(url) {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname}`.slice(0, 90);
  } catch {
    return url.slice(0, 90);
  }
}

async function settle(since) {
  // Quiet = nothing in flight for 1 s; live prices and charts load after render.
  while (Date.now() - since < SETTLE_CAP_MS) {
    if (!current.inflight.size && Date.now() - current.lastActivity > 1000) return;
    await new Promise((r) => setTimeout(r, 200));
  }
}

async function evaluate(fn) {
  const { result, exceptionDetails } = await chrome.send("Runtime.evaluate", { expression: `(${fn})()`, returnByValue: true });
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
  return result.value;
}

function judge(path, scan, expected, { grid = false } = {}) {
  for (const hit of scan.bad.slice(0, 3)) fail(path, `bad value on screen: ${hit}`);
  for (const t of scan.emptyTables) fail(path, `empty table: ${t}`);
  for (const c of scan.blankColumns) fail(path, `blank column: ${c}`);
  if (scan.deadCharts) fail(path, `${scan.deadCharts} chart(s) drew nothing`);
  for (const text of EMPTY.filter((t) => scan.text.includes(t))) fail(path, `empty section: "${text}"`);
  for (const text of WARN.filter((t) => scan.text.includes(t))) warn(path, `"${text}"`);
  if (expected && scan.header !== expected.header) fail(path, `header run date ${scan.header ?? "missing"}, latest run is ${expected.header}`);
  if (grid && expected) {
    const floor = Math.ceil(expected.run.row_count * MIN_GRID_SHARE);
    if (scan.gridTotal === null) fail(path, "grid shows no row total");
    else if (scan.gridTotal < floor) fail(path, `grid has ${scan.gridTotal} rows, under ${MIN_GRID_SHARE * 100}% of row_count ${expected.run.row_count}`);
  }
}

async function visit(path, expected, { grid = false, tabs = false } = {}) {
  current = { inflight: new Set(), requests: new Map(), errors: [], status: null, blocked: 0, lastActivity: Date.now() };
  const started = Date.now();
  await chrome.send("Page.navigate", { url: BASE + path });
  await new Promise((r) => setTimeout(r, 300));
  await settle(started);
  // Load time is the page's load event; "quiet" is only waited for to catch late errors.
  const ms = (current.loadedAt ?? Date.now()) - started;
  if (current.inflight.size) {
    const open = [...current.inflight].map((id) => shorten(current.requests.get(id) ?? "")).slice(0, 3).join(", ");
    warn(path, `network not quiet after ${SETTLE_CAP_MS / 1000} s; still open: ${open}`);
  }
  const finalUrl = await evaluate(() => location.pathname);
  if (current.status !== 200) fail(path, `HTTP ${current.status}`);
  if (finalUrl !== path.split("?")[0]) fail(path, `redirected to ${finalUrl}`);
  if (ms > SLOW_MS) fail(path, `slow: ${(ms / 1000).toFixed(1)} s`);
  if (current.blocked) warn(path, `${current.blocked} server-action write(s) blocked: the check is read-only`);
  judge(path, await evaluate(scanPage), expected, { grid });

  if (tabs) {
    const labels = await evaluate(() => [...document.querySelectorAll('[role="tab"][id^="stock-tab-"]')].map((t) => [t.id, t.textContent.trim()]));
    for (const [id, label] of labels) {
      await evaluate(`() => document.getElementById(${JSON.stringify(id)}).click()`);
      current.lastActivity = Date.now();
      await new Promise((r) => setTimeout(r, 400));
      await settle(Date.now());
      judge(`${path} [${label}]`, await evaluate(scanPage), null);
    }
  }
  // Many images failing the same way (every logo) read as one finding with a count.
  const grouped = new Map();
  for (const message of new Set(current.errors)) {
    // The blocked write's fetch rejects in the page; that is this check's doing, not the app's.
    if (current.blocked && /^uncaught exception: .*Failed to fetch/.test(message)) continue;
    const key = message.replace(/^(request failed \(.+?\)) ([^/\s]+)\/.*$/, "$1 $2");
    grouped.set(key, [...(grouped.get(key) ?? []), message]);
  }
  for (const [key, messages] of grouped) fail(path, messages.length > 1 ? `${key} x${messages.length}, e.g. ${messages[0].slice(0, 160)}` : messages[0]);
  pages.push({ path, status: current.status, ms, runDate: (await evaluate(scanPage)).header });
  console.log(`${String(current.status).padEnd(4)} ${path.padEnd(34)} ${String(ms).padStart(5)} ms`);
}

// ---- run -----------------------------------------------------------------------
try {
  await chrome.send("Network.enable");
  await chrome.send("Runtime.enable");
  await chrome.send("Page.enable");
  await chrome.send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
  await chrome.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await chrome.send("Network.setCookies", {
    cookies: [...jar].map(([name, value]) => ({ name, value, url: cookieUrl.origin, path: "/", secure: cookieUrl.protocol === "https:" })),
  });
  for (const slug of Object.keys(MARKETS)) {
    const expected = await expectations(slug);
    await liveFreshness(slug);
    for (const page of PAGES) await visit(`/${slug}${page}`, expected, { grid: page === "" });
    for (const symbol of expected?.picks ?? []) {
      await visit(`/${slug}/stocks/${encodeURIComponent(symbol)}`, expected, { tabs: true });
    }
  }
} finally {
  await chrome.close();
}

const failures = findings.filter((f) => f.level === "FAIL");
writeFileSync(JSON_PATH, JSON.stringify({ ranAt: new Date().toISOString(), base: BASE, ok: !failures.length, failures, warnings: findings.filter((f) => f.level === "WARN"), pages }, null, 2));
console.log(failures.length ? `\n${failures.length} failure(s); summary in ${JSON_PATH}` : `\nall ${pages.length} pages ok; summary in ${JSON_PATH}`);
process.exit(failures.length ? 1 : 0);
