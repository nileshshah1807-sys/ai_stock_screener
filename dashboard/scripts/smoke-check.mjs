#!/usr/bin/env node
// Read-only smoke check of the live dashboard, for the weekly audit.
//
//   CREED_DASHBOARD_PASSWORD=... NEXT_PUBLIC_SUPABASE_URL=... \
//   NEXT_PUBLIC_SUPABASE_ANON_KEY=... node scripts/smoke-check.mjs [baseUrl]
//
// Signs in with signInWithPassword (the anon key, like the app), lets
// @supabase/ssr write the auth cookies into an in-memory jar, then GETs every
// top-level page and Tools tab for /ind and /us. Prints status, the run date
// in the header and any empty-state text per page. Exits 1 on any non-200,
// redirect or empty section. Never prints the password.
import { createServerClient } from "@supabase/ssr";

const EMAIL = process.env.CREED_DASHBOARD_EMAIL ?? "creed.audit@example.com";
const BASE = (process.argv[2] ?? process.env.DASHBOARD_URL ?? "https://win-now.vercel.app").replace(/\/$/, "");
const { NEXT_PUBLIC_SUPABASE_URL: URL_, NEXT_PUBLIC_SUPABASE_ANON_KEY: ANON, CREED_DASHBOARD_PASSWORD: PASSWORD } = process.env;

if (!URL_ || !ANON || !PASSWORD) {
  console.error("Set NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY and CREED_DASHBOARD_PASSWORD.");
  process.exit(2);
}

const MARKETS = ["ind", "us"];
// Results analysis is NSE-only; the US shows a note, still a 200.
const PAGES = ["", "/market", "/movers", "/indices", "/watchlists", "/notifications", "/health",
  "/concalls", "/results", "/results/analysis", "/returns"];
// The empty-state sentences the app prints (grep ">No " in app/ and components/).
const EMPTY = [
  "No screener run has been published", "No stocks on this list today", "No stocks match these filters",
  "No results to analyse", "Nothing measured in this range", "No index is published", "Run date unavailable",
];

const jar = new Map();
const supabase = createServerClient(URL_, ANON, {
  cookies: {
    getAll: () => [...jar].map(([name, value]) => ({ name, value })),
    setAll: (list) => list.forEach(({ name, value }) => jar.set(name, value)),
  },
});
const { error } = await supabase.auth.signInWithPassword({ email: EMAIL, password: PASSWORD });
if (error) {
  console.error(`Sign-in failed: ${error.message}`);
  process.exit(2);
}
const cookie = [...jar].map(([name, value]) => `${name}=${value}`).join("; ");

let bad = 0;
for (const market of MARKETS) {
  for (const page of PAGES) {
    const path = `/${market}${page}`;
    let line;
    try {
      const res = await fetch(BASE + path, { headers: { cookie }, redirect: "manual" });
      const html = res.status === 200 ? await res.text() : "";
      // The header prints "<run date> · v<model>" beside the wordmark.
      const date = html.match(/\d{2} [A-Z][a-z]{2} \d{4}(?= · v|<)/)?.[0] ?? "-";
      const empty = EMPTY.filter((text) => html.includes(text));
      const where = res.status >= 300 && res.status < 400 ? ` -> ${res.headers.get("location")}` : "";
      if (res.status !== 200 || empty.length) bad += 1;
      line = `${String(res.status).padEnd(4)} ${path.padEnd(24)} run ${date}${where}${empty.length ? `  EMPTY: ${empty.join("; ")}` : ""}`;
    } catch (err) {
      bad += 1;
      line = `ERR  ${path.padEnd(24)} ${err.message}`;
    }
    console.log(line);
  }
}
console.log(bad ? `\n${bad} page(s) need attention` : "\nall pages ok");
process.exit(bad ? 1 : 0);
