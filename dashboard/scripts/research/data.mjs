// Caches everything a study needs, once, into out/.
//
//   node scripts/research/data.mjs design [2025-09-30]   backtest rankings, states, prices to END
//   node scripts/research/data.mjs holdout                rankings from Sep 2025 (backtest, then published) to the latest run
import { gunzipSync } from "node:zlib";
import { writeFileSync } from "node:fs";

import { decodeRow, indexPoints } from "../../lib/market-breadth.mjs";
import { decodeCloses } from "../../lib/returns.mjs";
import { out, pages, supabase } from "./paths.mjs";

const sb = await supabase();
const object = async (path) => {
  const { data, error } = await sb.storage.from("market-data").download(path);
  if (error) return null;
  return JSON.parse(gunzipSync(Buffer.from(await data.arrayBuffer())).toString("utf8"));
};

async function closesFor(symbols, sessions) {
  const closes = {};
  for (let i = 0; i < symbols.length; i += 24) {
    await Promise.all(
      symbols.slice(i, i + 24).map(async (symbol) => {
        const row = await object(`price-series/NSE/symbols/${encodeURIComponent(symbol)}.json.gz`);
        closes[symbol] = row ? decodeCloses(row, sessions).map((p) => [p.time, p.close]) : [];
      }),
    );
  }
  return closes;
}

async function indexes(end) {
  const { data } = await sb.from("market_breadth").select("sessions, series").eq("market", "NSE").eq("scope", "index").eq("name", "Nifty 500").maybeSingle();
  const benchmark = indexPoints(decodeRow(data)).filter((p) => p.time <= end);
  // The equal-weight index of every ranked stock, compounded to levels.
  const rows = await pages(() => sb.from("universe_index").select("observed_on, ew_return_pct").eq("market", "NSE").lte("observed_on", end).order("observed_on"));
  let level = 100;
  const smallcap = rows.map((r) => ({ time: r.observed_on, value: (level *= 1 + Number(r.ew_return_pct) / 100) }));
  return { benchmark, smallcap };
}

const [mode = "design", endArg] = process.argv.slice(2);
const calendar = await object("price-series/NSE/calendar.json.gz");
const sessions = JSON.parse(calendar.sessions);

if (mode === "design") {
  const END = endArg ?? "2025-09-30";
  const rankings = await pages(() => sb.from("simulated_rankings")
    .select("observed_on, symbol, investment_rank, rating, stage, advance_age_days, rank_buy, rank_strong_buy, rank_stage2, rank_fresh_stage2")
    .eq("market", "NSE").lte("observed_on", END).order("observed_on").order("investment_rank"));
  const states = await pages(() => sb.from("simulated_states").select("observed_on, advancing, buy_plus").eq("market", "NSE").lte("observed_on", END).order("observed_on"));
  const symbols = [...new Set(rankings.map((r) => r.symbol))];
  const closes = await closesFor(symbols, sessions);
  for (const symbol of symbols) closes[symbol] = closes[symbol].filter(([t]) => t <= END);
  const { benchmark, smallcap } = await indexes(END);
  writeFileSync(out(`data-${END}.json`), JSON.stringify({ end: END, rankings, states, sessions: sessions.filter((s) => s <= END), closes, benchmark, smallcap }));
  console.log({ mode, end: END, rankings: rankings.length, states: states.length, symbols: symbols.length });
} else if (mode === "holdout") {
  const FROM = "2025-09-01";
  const { data: first } = await sb.from("screener_history").select("observed_on").eq("market", "NSE").order("observed_on").limit(1);
  const liveFrom = first[0].observed_on;
  const simulated = await pages(() => sb.from("simulated_rankings").select("observed_on, symbol, investment_rank").eq("market", "NSE").gte("observed_on", FROM).lt("observed_on", liveFrom).lte("investment_rank", 50).order("observed_on").order("investment_rank"));
  const published = await pages(() => sb.from("screener_history").select("observed_on, symbol, investment_rank").eq("market", "NSE").gte("observed_on", liveFrom).lte("investment_rank", 50).order("observed_on").order("investment_rank"));
  const rankings = [...simulated, ...published];
  const symbols = [...new Set(rankings.map((r) => r.symbol))];
  const closes = await closesFor(symbols, sessions);
  // Raw closes after the calendar's last session, as the page's tail read does.
  for (let i = 0; i < symbols.length; i += 150) {
    const tail = await pages(() => sb.from("screener_history").select("symbol, observed_on, current_price").eq("market", "NSE").in("symbol", symbols.slice(i, i + 150)).gt("observed_on", sessions.at(-1)).order("symbol").order("observed_on"));
    for (const r of tail) if (Number(r.current_price) > 0) closes[r.symbol].push([r.observed_on, Number(r.current_price)]);
  }
  const { benchmark, smallcap } = await indexes("9999-12-31");
  const allSessions = [...new Set([...sessions, ...rankings.map((r) => r.observed_on)])].sort();
  writeFileSync(out("data-holdout.json"), JSON.stringify({ end: "holdout", liveFrom, rankings, states: [], sessions: allSessions, closes, benchmark, smallcap }));
  console.log({ mode, liveFrom, rankings: rankings.length, symbols: symbols.length, lastSession: allSessions.at(-1) });
} else {
  throw new Error(`unknown mode ${mode}`);
}
