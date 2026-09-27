// Builds out/report.html from the three result files; pdf.mjs renders it.
//
//   node scripts/research/report.mjs
import { readFileSync, writeFileSync } from "node:fs";

import { out } from "./paths.mjs";

const read = (name) => JSON.parse(readFileSync(out(name), "utf8"));
const f = read("facts.json");
const p7 = read("p7-design.json");
const ho = read("p7-holdout.json");
const ro = read("rolling-summary.json");
const full = f.windows.full, rated = f.windows.rated;

const LABEL = {
  all: "All (no filter)", stage2: "Stage 2", fresh_stage2: "Fresh S2", buy: "Buy+", strong_buy: "Strong Buy",
  "buy+stage2": "Buy+ · Stage 2", "buy+fresh_stage2": "Buy+ · Fresh S2", "strong_buy+stage2": "Strong Buy · Stage 2",
  "strong_buy+fresh_stage2": "Strong Buy · Fresh S2",
};
const REB = { never: "Never", "1w": "Weekly", "2w": "2 weeks", "1m": "Monthly", "3m": "Quarterly" };
const W = { hold: "Hold as bought", equal: "Reset to equal" };
const pct = (x, d = 1) => {
  if (x == null) return "—";
  const text = Math.abs(x).toFixed(d);
  return `${Number(text) === 0 ? "" : x > 0 ? "+" : "−"}${text}%`;
};
const num = (x, d = 2) => (x == null ? "—" : x.toFixed(d));
const date = (t) => new Date(t + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const setting = (r) => `${LABEL[r.pick]} · Top ${r.topN} · ${REB[r.rebalance]}${r.rebalance === "never" ? "" : ` · ${W[r.weights]}`}`;
const family = (p) => (p === "all" ? "all" : p.includes("buy") && p.includes("stage") ? "both" : p.includes("buy") ? "rating" : "stage");
const COLORS = { all: "#4338ca", stage: "#0f766e", rating: "#b45309", both: "#be185d", nifty: "#64748b" };

function scatter(points, bench) {
  const Wd = 640, H = 330, m = { l: 52, r: 16, t: 14, b: 40 };
  const xs = points.map((p) => p.dd), ys = points.map((p) => p.cagr);
  const x0 = Math.floor(Math.min(...xs, bench.dd) / 5) * 5, x1 = 0;
  const y0 = Math.min(0, Math.floor(Math.min(...ys) / 10) * 10), y1 = Math.ceil(Math.max(...ys) / 10) * 10;
  const X = (v) => m.l + ((v - x0) / (x1 - x0)) * (Wd - m.l - m.r), Y = (v) => H - m.b - ((v - y0) / (y1 - y0)) * (H - m.t - m.b);
  let g = "";
  for (let v = y0; v <= y1; v += 10) g += `<line x1="${m.l}" x2="${Wd - m.r}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/><text x="${m.l - 6}" y="${Y(v) + 3}" class="tick" text-anchor="end">${v}%</text>`;
  for (let v = x0; v <= 0; v += 5) g += `<text x="${X(v)}" y="${H - m.b + 14}" class="tick" text-anchor="middle">${v}%</text>`;
  g += `<rect x="${X(-20)}" y="${m.t}" width="${X(0) - X(-20)}" height="${H - m.t - m.b}" fill="#16a34a" opacity="0.06"/>`;
  g += `<line x1="${X(-20)}" x2="${X(-20)}" y1="${m.t}" y2="${H - m.b}" stroke="#16a34a" stroke-dasharray="4 3"/><text x="${X(-20) + 4}" y="${m.t + 10}" class="tick" fill="#15803d">−20% cap</text>`;
  for (const p of points) g += `<circle cx="${X(p.dd)}" cy="${Y(p.cagr)}" r="3.2" fill="${COLORS[family(p.pick)]}" opacity="0.72"/>`;
  g += `<path d="M${X(bench.dd) - 6},${Y(bench.cagr)} l6,-6 l6,6 l-6,6 z" fill="${COLORS.nifty}"/><text x="${X(bench.dd) + 9}" y="${Y(bench.cagr) + 4}" class="tick">Nifty 500</text>`;
  g += `<text x="${(m.l + Wd - m.r) / 2}" y="${H - 6}" class="axis" text-anchor="middle">Worst fall (max drawdown) — further right is better</text>`;
  g += `<text transform="translate(12 ${(m.t + H - m.b) / 2}) rotate(-90)" class="axis" text-anchor="middle">Return a year (CAGR)</text>`;
  return `<svg viewBox="0 0 ${Wd} ${H}" class="chart">${g}</svg>`;
}

function curves(series, { log = true } = {}) {
  const Wd = 640, H = 250, m = { l: 52, r: 90, t: 12, b: 26 };
  const all = series.flatMap((s) => s.points);
  const t0 = Date.parse(all.reduce((a, p) => (p[0] < a ? p[0] : a), "9999")), t1 = Date.parse(all.reduce((a, p) => (p[0] > a ? p[0] : a), "0"));
  const val = (v) => (log ? Math.log10(1 + v / 100) : v);
  const vs = all.map((p) => val(p[1]));
  const v0 = Math.min(...vs), v1 = Math.max(...vs);
  const X = (t) => m.l + ((Date.parse(t) - t0) / (t1 - t0)) * (Wd - m.l - m.r), Y = (v) => H - m.b - ((val(v) - v0) / (v1 - v0)) * (H - m.t - m.b);
  let g = "";
  const ticks = log ? [0, 100, 300, 900, 1900, 3900].filter((v) => val(v) <= v1 + 0.05) : [];
  for (const v of ticks) g += `<line x1="${m.l}" x2="${Wd - m.r}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/><text x="${m.l - 6}" y="${Y(v) + 3}" class="tick" text-anchor="end">${(1 + v / 100).toFixed(0)}×</text>`;
  for (let y = 2019; y <= 2025; y++) { const t = `${y}-01-01`; if (Date.parse(t) >= t0) g += `<text x="${X(t)}" y="${H - 8}" class="tick" text-anchor="middle">${y}</text>`; }
  for (const s of series) {
    g += `<path d="${s.points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("")}" fill="none" stroke="${s.color}" stroke-width="${s.width ?? 1.5}"/>`;
    const last = s.points.at(-1);
    g += `<text x="${Wd - m.r + 4}" y="${Y(last[1]) + 3}" class="tick" fill="${s.color}">${s.label}</text>`;
  }
  return `<svg viewBox="0 0 ${Wd} ${H}" class="chart">${g}</svg>`;
}

function underwater(series) {
  const Wd = 640, H = 170, m = { l: 52, r: 90, t: 10, b: 26 };
  const dd = (pts) => { let peak = 1; return pts.map(([t, v]) => { const w = 1 + v / 100; peak = Math.max(peak, w); return [t, (w / peak - 1) * 100]; }); };
  const ser = series.map((s) => ({ ...s, points: dd(s.points) }));
  const all = ser.flatMap((s) => s.points);
  const t0 = Date.parse(all[0][0]), t1 = Date.parse(all.reduce((a, p) => (p[0] > a ? p[0] : a), "0"));
  const lo = Math.floor(Math.min(...all.map((p) => p[1])) / 10) * 10;
  const X = (t) => m.l + ((Date.parse(t) - t0) / (t1 - t0)) * (Wd - m.l - m.r), Y = (v) => m.t + (v / lo) * (H - m.t - m.b);
  let g = "";
  for (let v = 0; v >= lo; v -= 10) g += `<line x1="${m.l}" x2="${Wd - m.r}" y1="${Y(v)}" y2="${Y(v)}" class="grid"/><text x="${m.l - 6}" y="${Y(v) + 3}" class="tick" text-anchor="end">${v}%</text>`;
  g += `<line x1="${m.l}" x2="${Wd - m.r}" y1="${Y(-20)}" y2="${Y(-20)}" stroke="#16a34a" stroke-dasharray="4 3"/>`;
  for (let y = 2019; y <= 2025; y++) { const t = `${y}-01-01`; if (Date.parse(t) >= t0) g += `<text x="${X(t)}" y="${H - 8}" class="tick" text-anchor="middle">${y}</text>`; }
  for (const s of ser) g += `<path d="${s.points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("")}" fill="none" stroke="${s.color}" stroke-width="1.3"/><text x="${Wd - m.r + 4}" y="${Y(s.points.at(-1)[1]) + 3}" class="tick" fill="${s.color}">${s.label}</text>`;
  return `<svg viewBox="0 0 ${Wd} ${H}" class="chart">${g}</svg>`;
}

const pickTable = (win) => `<table><thead><tr><th>Filter</th><th>Settings</th><th>Median return / yr</th><th>Median worst fall</th><th>Best worst fall</th><th>Beat Nifty</th><th>Trades won</th><th>Rounds short</th></tr></thead><tbody>
${[...win.byPick].sort((a, b) => b.medCagr - a.medCagr).map((p) => `<tr${p.pick === "all" ? ' class="hi"' : ""}><td>${LABEL[p.pick]}</td><td>${p.n}</td><td>${pct(p.medCagr)}</td><td>${pct(p.medDD)}</td><td>${pct(p.bestDD)}</td><td>${p.beatShare.toFixed(0)}%</td><td>${p.medWin == null ? "—" : p.medWin.toFixed(0) + "%"}</td><td>${p.medShortShare.toFixed(0)}%</td></tr>`).join("")}
<tr class="bench"><td>Nifty 500</td><td>—</td><td>${pct(win.bench.cagrPct)}</td><td>${pct(win.bench.maxDDPct)}</td><td>—</td><td>—</td><td>—</td><td>—</td></tr></tbody></table>`;

const effectTable = (win) => {
  const rows = [
    ...win.effects.topN.map((e) => [`Top ${e.value}`, e]),
    ...win.effects.rebalance.map((e) => [REB[e.value], e]),
    ...win.effects.weights.map((e) => [W[e.value], e]),
  ];
  return `<table><thead><tr><th>Setting</th><th>Runs</th><th>Median return / yr</th><th>Median worst fall</th><th>Median return ÷ fall</th></tr></thead><tbody>${rows.map(([l, e]) => `<tr><td>${l}</td><td>${e.n}</td><td>${pct(e.medCagr)}</td><td>${pct(e.medDD)}</td><td>${num(e.medCalmar)}</td></tr>`).join("")}</tbody></table>`;
};

const ref = f.refs[0];
const years = Object.keys(ref.byYear).filter((y) => y >= "2019");
const yearTable = `<table><thead><tr><th>Setting</th>${years.map((y) => `<th>${y}${y === "2025" ? "*" : ""}</th>`).join("")}</tr></thead><tbody>
${f.refs.map((r) => `<tr><td>${setting(r)}</td>${years.map((y) => `<td class="${r.byYear[y] < 0 ? "neg" : ""}">${pct(r.byYear[y], 0)}</td>`).join("")}</tr>`).join("")}
<tr class="bench"><td>Nifty 500</td>${years.map((y) => `<td class="${full.bench.byYear[y] < 0 ? "neg" : ""}">${pct(full.bench.byYear[y], 0)}</td>`).join("")}</tr></tbody></table>`;

const epiTable = `<table><thead><tr><th>Fall</th><th>Peak → bottom</th><th>Back to peak</th><th>Basket</th><th>Nifty 500, same dates</th><th>Basket ÷ Nifty</th></tr></thead><tbody>
${ref.episodes.map((e, i) => `<tr><td>${i + 1}</td><td>${date(e.peak)} → ${date(e.trough)}</td><td>${e.recovered ? date(e.recovered) : "not by 30 Sep 2025"}</td><td class="neg">${pct(e.dd)}</td><td>${pct(e.bench)}</td><td>${(e.dd / e.bench).toFixed(1)}×</td></tr>`).join("")}</tbody></table>`;

const listTable = (rows) => `<table><thead><tr><th>Setting</th><th>Return / yr</th><th>Worst fall</th><th>Return ÷ fall</th><th>Trades won</th><th>Rounds short</th></tr></thead><tbody>
${rows.map((r) => `<tr><td>${setting(r)}</td><td>${pct(r.cagrPct)}</td><td>${pct(r.maxDDPct)}</td><td>${num(r.calmar)}</td><td>${r.winRate == null ? "— (held)" : r.winRate.toFixed(0) + "%"}</td><td>${r.shortRounds}/${r.rounds}</td></tr>`).join("")}</tbody></table>`;

const pe = rated.pairedEqualMinusHold, pf = full.pairedEqualMinusHold;
const allR = rated.byPick.find((p) => p.pick === "all"), allF = full.byPick.find((p) => p.pick === "all");
const filtersR = rated.byPick.filter((p) => p.pick !== "all");
const stageF = full.byPick.filter((p) => p.pick !== "all");
const rng = (xs) => `${pct(Math.min(...xs))} to ${pct(Math.max(...xs))}`;


const H_LABEL = { "6m": "6 months", "1y": "1 year", "3y": "3 years" };
const FILTER_ORDER = ["all", "stage2", "fresh_stage2", "buy", "strong_buy", "buy+stage2", "buy+fresh_stage2", "strong_buy+stage2", "strong_buy+fresh_stage2"];
const share0 = (x) => (x == null ? "—" : `${Math.round(x)}%`);
const pts = (x) => (x == null ? "—" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(1)}`);

function beatBars(h) {
  const rows = FILTER_ORDER.filter((k) => k !== "all" && ro.filters[h][k]).map((k) => [LABEL[k], ro.filters[h][k].all.beatPair]);
  const Wd = 640, rowH = 20, H = rows.length * rowH + 30, l = 150, r = 40;
  const X = (v) => l + (v / 100) * (Wd - l - r);
  let g = "";
  for (const v of [0, 25, 50, 75, 100]) g += `<line x1="${X(v)}" x2="${X(v)}" y1="4" y2="${H - 22}" class="grid"/><text x="${X(v)}" y="${H - 8}" class="tick" text-anchor="middle">${v}%</text>`;
  g += `<line x1="${X(50)}" x2="${X(50)}" y1="4" y2="${H - 22}" stroke="#94a3b8" stroke-dasharray="3 3"/>`;
  rows.forEach(([label, v], i) => {
    const y = 6 + i * rowH;
    g += `<text x="${l - 8}" y="${y + 11}" class="axis" text-anchor="end">${label}</text><rect x="${X(0)}" y="${y}" width="${X(v) - X(0)}" height="${rowH - 7}" rx="3" fill="${COLORS[family(FILTER_ORDER.find((k) => LABEL[k] === label))]}" opacity="0.8"/><text x="${X(v) + 4}" y="${y + 11}" class="tick">${Math.round(v)}%</text>`;
  });
  return `<svg viewBox="0 0 ${Wd} ${H}" class="chart">${g}</svg>`;
}

const filterTable = (h) => `<table><thead><tr><th>Filter</th><th>Runs</th><th>Median return / yr</th><th>Bad case (1 in 10)</th><th>Median worst fall</th><th>Fell past −20%</th><th>Beat Nifty</th><th>Beat no filter</th></tr></thead><tbody>
${FILTER_ORDER.filter((k) => ro.filters[h][k]).map((k) => { const a = ro.filters[h][k].all; return `<tr${k === "all" ? ' class="hi"' : ""}><td>${LABEL[k]}</td><td>${a.runs}</td><td>${pct(a.medAnnual)}</td><td>${pct(a.p10Annual)}</td><td>${pct(a.medDD)}</td><td>${share0(a.ddPast20)}</td><td>${share0(a.beatNifty)}</td><td>${k === "all" ? "—" : share0(a.beatPair)}</td></tr>`; }).join("")}</tbody></table>`;

const fallingTable = (h) => `<table><thead><tr><th>Filter</th><th>Runs</th><th>Median return / yr</th><th>Median worst fall</th><th>Beat no filter</th><th>Shallower fall than no filter</th><th>Median fall vs no filter</th></tr></thead><tbody>
${FILTER_ORDER.filter((k) => ro.filters[h][k]?.byMarket.falling.runs).map((k) => { const a = ro.filters[h][k].byMarket.falling; return `<tr${k === "all" ? ' class="hi"' : ""}><td>${LABEL[k]}</td><td>${a.runs}</td><td>${pct(a.medAnnual)}</td><td>${pct(a.medDD)}</td><td>${k === "all" ? "—" : share0(a.beatPair)}</td><td>${k === "all" ? "—" : share0(a.shallowerThanPair)}</td><td>${k === "all" ? "—" : pts(a.medDDVsPair) + " pts"}</td></tr>`; }).join("")}</tbody></table>`;

const RULE_ORDER = ["none", "R1", "R2", "R3", "R1+R2", "R1+R3", "R2+R3", "R1+R2+R3"];
const ruleTable = (h) => `<table><thead><tr><th>Start</th><th>Rules</th><th>Median return / yr</th><th>Median worst fall</th><th>Fell past −20%</th><th>Return vs no rules</th><th>Fall vs no rules</th><th>Shallower than no rules</th><th>Falling markets: fall vs no rules</th></tr></thead><tbody>
${["A", "B"].flatMap((b) => RULE_ORDER.map((k) => { const x = ro.rules[h][b][k]; const a = x.all, fl = x.byMarket.falling; return `<tr${k === "R3" ? ' class="hi"' : ""}><td>${b === "A" ? "Weekly, reset" : "Monthly, hold"}</td><td>${k === "none" ? "none" : k.replaceAll("+", " + ")}</td><td>${pct(a.medAnnual)}</td><td>${pct(a.medDD)}</td><td>${share0(a.ddPast20)}</td><td>${k === "none" ? "—" : pts(a.medReturnVsPair) + " pts"}</td><td>${k === "none" ? "—" : pts(a.medDDVsPair) + " pts"}</td><td>${k === "none" ? "—" : share0(a.shallowerThanPair)}</td><td>${k === "none" || !fl.runs ? "—" : pts(fl.medDDVsPair) + " pts"}</td></tr>`; })).join("")}</tbody></table>`;

const wt = (h, scope) => ro.weights[h][scope];
const ROLLING = `
<h2 class="pb">Across many periods</h2>
<p>Everything above rests on one start date per window. To check it isn't an accident of timing, the same tests were re-run as a fresh basket started at the first ranking of every month and held for 6 months, 1 year or 3 years — ${ro.markets["1y"].falling + ro.markets["1y"].flat + ro.markets["1y"].rising} overlapping one-year windows from Jan 2019 (from Jun 2023 for rating filters), through the end of the backtest on ${date(ro.end)}. Settings: Top 10 and Top 20, weekly and monthly, both weightings. Each filter is compared with the unfiltered ranking over the same window at the same settings.</p>
<p>A window's market type was fixed before any result was seen, by the Nifty 500's yearly return over it: below 0% falling, 0–10% flat, above 10% rising. One-year windows: ${ro.markets["1y"].falling} falling, ${ro.markets["1y"].flat} flat, ${ro.markets["1y"].rising} rising. Every three-year window since 2019 was rising, so the three-year figures say nothing about bad markets.</p>
<h3>How often each filter beat no filter, one-year windows</h3>
${beatBars("1y")}
<h3>One-year windows</h3>
${filterTable("1y")}
<p class="note">Bad case: the return a year that one window in ten fell below. Fell past −20%: share of windows whose worst fall was deeper than −20%. Rating filters have only ${ro.filters["1y"].buy?.all.windows ?? "—"} one-year windows (ratings start May 2023), so their figures are the least certain.</p>
<h3 class="pb">Falling markets only</h3>
<p>If a filter earned its keep by protecting capital, it would show here. Six-month windows where the Nifty 500 fell (${ro.markets["6m"].falling} start dates):</p>
${fallingTable("6m")}
<p>One-year windows where it fell (${ro.markets["1y"].falling} start dates):</p>
${fallingTable("1y")}
<p class="note">"Fall vs no filter" is in percentage points of worst fall; positive means shallower than no filter.</p>

<h3 class="pb">Weighting, across windows</h3>
<table><thead><tr><th>Hold</th><th>Scope</th><th>Pairs</th><th>Reset returned more</th><th>Median difference / yr</th><th>Reset fell less</th><th>Median fall difference</th></tr></thead><tbody>
${["6m", "1y", "3y"].flatMap((h) => [["noFilter", "No filter"], ["every", "Every filter"]].map(([k, l]) => { const w = wt(h, k); return `<tr><td>${H_LABEL[h]}</td><td>${l}</td><td>${w.pairs}</td><td>${share0(w.resetReturnedMore)}</td><td>${pts(w.medReturnDiff)} pts</td><td>${share0(w.resetShallower)}</td><td>${pts(w.medDDDiff)} pts</td></tr>`; })).join("")}</tbody></table>
<p>Reset to equal still comes out slightly ahead, but only slightly: with no filter it returned more in ${share0(wt("1y", "noFilter").resetReturnedMore)} of one-year windows, by a median ${pts(wt("1y", "noFilter").medReturnDiff)} points a year, and fell less in ${share0(wt("1y", "noFilter").resetShallower)}. The single-window "${pe.equalBetterCagr} of ${pe.n}" overstated it.</p>

<h2 class="pb">The drawdown rules, across windows</h2>
<p>The same 16 rule combinations, each compared with its own starting point without rules over the same window. One-year windows:</p>
${ruleTable("1y")}
<p>Three-year windows:</p>
${ruleTable("3y")}
<ul>
<li><b>The market and small-cap switches (R1, R2) do not work.</b> They made the worst fall shallower in only a minority of windows, rarely by more than a point in the median, and cost ${pts(ro.rules["1y"].A.R1.all.medReturnVsPair)} to ${pts(ro.rules["1y"].B.R1.all.medReturnVsPair)} points a year (R1). Their one success in the design period was the 2020 crash.</li>
<li><b>The trailing stop (R3) is the only rule that helps with any consistency.</b> Held monthly as bought, it made the worst fall shallower in ${share0(ro.rules["1y"].B.R3.all.shallowerThanPair)} of one-year windows and ${share0(ro.rules["3y"].B.R3.all.shallowerThanPair)} of three-year windows — by a median ${pts(ro.rules["1y"].B.R3.all.medDDVsPair)} points, and ${pts(ro.rules["1y"].B.R3.byMarket.falling.medDDVsPair)} in falling markets — for ${pts(ro.rules["1y"].B.R3.all.medReturnVsPair)} points a year of return. Small, but in the right direction almost every time.</li>
<li><b>Nothing reaches −20% on its own.</b> Even with the stop, ${share0(ro.rules["1y"].B.R3.all.ddPast20)} of one-year windows fell further than −20%, and every three-year window did.</li>
</ul>

<h3>Where that leaves us</h3>
<p><b>1. Hold less than all of the money in the basket.</b> The only way to a −20% cap in a crash year: keeping part in cash or a liquid fund shrinks every fall roughly in proportion — 60% invested turns a −48% fall into about −29% — at the same proportional cost in return, with nothing fitted to history. &nbsp;<b>2. Test the trailing stop forward.</b> It is the one rule that held up across windows; being chosen after all these runs, it can only be confirmed on published rankings from here on. &nbsp;<b>3. Reset to equal as the page's default</b> is a mild improvement, not a strong one; reasonable, but not important. &nbsp;<b>4. Keep the unfiltered ranking as the main basket.</b> The filters remain on the page for reading, not as the way to pick.</p>`;

const html = `<!doctype html><html><head><meta charset="utf-8"><title>Returns filter study</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
* { box-sizing: border-box; }
body { font-family: Inter, system-ui, sans-serif; color: #0f172a; font-size: 9.6pt; line-height: 1.5; margin: 0; }
h1 { font-size: 22pt; letter-spacing: -0.02em; line-height: 1.1; margin: 0 0 4pt; }
h2 { font-size: 13pt; letter-spacing: -0.01em; margin: 20pt 0 6pt; break-after: avoid; }
h3 { font-size: 10.5pt; margin: 12pt 0 4pt; break-after: avoid; }
p { margin: 0 0 6pt; }
.sub { color: #475569; font-size: 10pt; margin-bottom: 14pt; }
.meta { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt; margin: 10pt 0 14pt; }
.meta div { border: 1px solid #e2e8f0; border-radius: 8pt; padding: 7pt 9pt; }
.meta b { display: block; font-size: 7.5pt; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.find { counter-reset: f; padding: 0; list-style: none; margin: 0; }
.find li { counter-increment: f; position: relative; padding: 6pt 0 6pt 24pt; border-top: 1px solid #e2e8f0; break-inside: avoid; }
.find li::before { content: counter(f); position: absolute; left: 0; top: 6pt; width: 16pt; height: 16pt; border-radius: 50%; background: #eef2ff; color: #4338ca; font-weight: 700; font-size: 8pt; display: grid; place-items: center; }
.find b { font-weight: 600; }
table { width: 100%; border-collapse: collapse; margin: 4pt 0 8pt; font-size: 8.4pt; font-variant-numeric: tabular-nums; break-inside: avoid; }
th { text-align: right; font-weight: 600; color: #475569; border-bottom: 1.2px solid #cbd5e1; padding: 4pt 5pt; font-size: 7.6pt; }
td { text-align: right; padding: 3.5pt 5pt; border-bottom: 1px solid #f1f5f9; }
th:first-child, td:first-child { text-align: left; }
tr.hi td { background: #eef2ff; font-weight: 600; }
tr.bench td { color: #475569; font-style: italic; border-top: 1px solid #cbd5e1; }
td.neg { color: #be123c; }
.chart { width: 100%; height: auto; display: block; margin: 4pt 0 2pt; }
.chart .grid { stroke: #e2e8f0; stroke-width: 1; }
.chart .tick { font-size: 8px; fill: #64748b; font-family: Inter, sans-serif; }
.chart .axis { font-size: 8.5px; fill: #334155; font-family: Inter, sans-serif; }
.legend { display: flex; gap: 12pt; font-size: 8pt; color: #475569; flex-wrap: wrap; }
.legend span::before { content: ""; display: inline-block; width: 8pt; height: 8pt; border-radius: 50%; margin-right: 4pt; vertical-align: -1pt; background: var(--c); }
.note { color: #64748b; font-size: 8pt; }
.box { border: 1px solid #fcd34d; background: #fffbeb; border-radius: 8pt; padding: 8pt 10pt; margin: 8pt 0; break-inside: avoid; }
.box.plan { border-color: #c7d2fe; background: #f8faff; }
.rule { border-top: 1px solid #e2e8f0; padding: 5pt 0; break-inside: avoid; }
.rule b { display: inline-block; min-width: 22pt; color: #4338ca; }
.pb { break-before: page; }
</style></head><body>

<h1>Which picks work</h1>
<p class="sub">Returns filter study · NSE · backtest design period ${date(full.start)} – ${date(f.asOf)} · prepared 27 Sep 2026</p>

<div class="meta">
<div><b>Settings tested</b>${full.n + rated.n} runs</div>
<div><b>Design period</b>${date(full.start)} – ${date(f.asOf)}</div>
<div><b>Held back (sealed)</b>1 Oct 2025 – today</div>
<div><b>Costs</b>0.3% each way</div>
</div>

<h2>What we found</h2>
<ol class="find">
<li><b>The unfiltered ranking beat every filter.</b> Across all settings, buying the top of the ranking with no filter returned a median ${pct(allF.medCagr)} a year from 2019, against ${rng(stageF.map((p) => p.medCagr))} for the stage filters. From mid-2023, when ratings exist, it returned ${pct(allR.medCagr)} against ${rng(filtersR.map((p) => p.medCagr))} for every rating, stage and combined filter.</li>
<li><b>Filters did not make the ride smoother.</b> The median worst fall with no filter was ${pct(allR.medDD)} from mid-2023; the filters ranged ${rng(filtersR.map((p) => p.medDD))}. Only ${rated.withinCap.length} of ${rated.n} settings stayed inside the −20% limit, and every one is a combined filter that was either bought once and never rebalanced, or sat mostly in cash for want of stocks.</li>
<li><b>The deep falls are market sell-offs, made worse.</b> The three worst falls of the no-filter basket line up with the three Nifty 500 sell-offs (2020, 2022, late 2024 – early 2025), and the basket fell ${(ref.episodes[0].dd / ref.episodes[0].bench).toFixed(1)}–${Math.max(...ref.episodes.slice(0, 3).map((e) => e.dd / e.bench)).toFixed(1)} times as far as the index in each. The small and mid-sized stocks the ranking favours fall harder than the market in a sell-off.</li>
<li><b>The gains come from strong years for smaller stocks.</b> The no-filter basket (Top 20, monthly) returned ${pct(ref.byYear["2020"], 0)}, ${pct(ref.byYear["2021"], 0)}, ${pct(ref.byYear["2023"], 0)} and ${pct(ref.byYear["2024"], 0)} in 2020, 2021, 2023 and 2024, but lagged the index in 2019 (${pct(ref.byYear["2019"], 0)} vs ${pct(full.bench.byYear["2019"], 0)}) and in 2025 to September (${pct(ref.byYear["2025"], 0)} vs ${pct(full.bench.byYear["2025"], 0)}).</li>
<li><b>Resetting to equal weight did better than holding as bought.</b> In ${pe.equalBetterCagr} of ${pe.n} matched settings from mid-2023 (and ${pf.equalBetterCagr} of ${pf.n} from 2019) the reset returned more — a median ${pct(pe.medDCagr)} a year — with about the same worst fall (${pct(pe.medDDD)}). Across many start dates the edge is much smaller (see "Weighting, across windows") so this is a mild preference, not a strong one.</li>
<li><b>Basket size and rebalance frequency matter much less than the filter.</b> Their medians sit within a few points of each other; see the table on page 3.</li>
<li><b>Starting on other dates does not change the answer.</b> Re-run as a fresh basket started every month and held 6 months, 1 year or 3 years, no filter beat the unfiltered ranking in more than ${Math.round(Math.max(...Object.entries(ro.filters["1y"]).filter(([k]) => k !== "all").map(([, v]) => v.all.beatPair)))}% of the one-year windows, and none protected meaningfully in falling markets (at best about a point shallower). Of the drawdown rules only the trailing stop helped with any consistency, and only a little (see "Across many periods").</li>
</ol>

<div class="box"><b>Read every figure as an upper bound.</b> The design period is a backtest over the same years the model's weights were fitted on, so these returns are in-sample and flatter what to expect. The last 12 months are sealed: nothing in this report looks at them, so they can test whatever we decide next. Prices are adjusted for splits and bonuses but not dividends, on both sides.</div>

<h2 class="pb">Return against worst fall, every setting</h2>
<p>Each dot is one setting from mid-2023 (${rated.n} runs): the filter, basket size, rebalance frequency and weighting. Up is more return, right is a shallower worst fall. The green band is the −20% limit.</p>
${scatter(rated.scatter, { cagr: rated.bench.cagrPct, dd: rated.bench.maxDDPct })}
<div class="legend"><span style="--c:${COLORS.all}">No filter</span><span style="--c:${COLORS.stage}">Stage filter</span><span style="--c:${COLORS.rating}">Rating filter</span><span style="--c:${COLORS.both}">Rating + stage</span><span style="--c:${COLORS.nifty}">Nifty 500</span></div>

<h3>By filter, ${date(rated.start)} – ${date(f.asOf)}</h3>
${pickTable(rated)}
<p class="note">Medians over every basket size, rebalance frequency and weighting for that filter. "Rounds short" is the share of rebalances where fewer stocks passed the filter than the basket holds; the rest waited in cash.</p>

<h3>By filter, ${date(full.start)} – ${date(f.asOf)} (no ratings before May 2023)</h3>
${pickTable(full)}

<h2 class="pb">Settings</h2>
<h3>${date(rated.start)} – ${date(f.asOf)}</h3>
${effectTable(rated)}
<h3>${date(full.start)} – ${date(f.asOf)}</h3>
${effectTable(full)}
<p class="note">Each row is a median across every filter, so rows mix different filters. "Hold as bought" also includes the never-rebalanced runs; the matched comparison in finding 5, same filter, size and frequency, is the fairer test of the two weightings.</p>

<h3>Highest returns, ${date(rated.start)} – ${date(f.asOf)}</h3>
${listTable(rated.top)}
<h3>Every setting inside the −20% limit</h3>
${listTable(rated.withinCap)}

<h2 class="pb">Where the falls come from</h2>
<p>Growth of ₹1 from ${date(full.start)} (log scale), and how far each sat below its last peak.</p>
${curves([
  { label: "No filter", color: COLORS.all, points: f.refs[0].curve, width: 1.8 },
  { label: "Stage 2", color: COLORS.stage, points: f.refs[2].curve },
  { label: "Nifty 500", color: COLORS.nifty, points: f.benchCurve },
])}
${underwater([
  { label: "No filter", color: COLORS.all, points: f.refs[0].curve },
  { label: "Nifty 500", color: COLORS.nifty, points: f.benchCurve },
])}
<p class="note">No filter = ${setting(f.refs[0])}. Stage 2 = ${setting(f.refs[2])}. The dashed line is −20%.</p>

<h3>The four worst falls of the no-filter basket</h3>
${epiTable}

<h3>Year by year</h3>
${yearTable}
<p class="note">* 2025 runs to 30 Sep, the end of the design period.</p>

<h2 class="pb">The drawdown study, as agreed before it was run</h2>
<p>No filter and no setting on the page keeps the worst fall inside −20% without giving up most of the return, because the falls are the market's, amplified. So the next study changes <i>how the basket is run</i> and leaves the scores alone, as agreed. To keep it honest, the rules, their numbers and the way we choose are fixed below before any of them is tested; nothing gets tuned after the results are seen.</p>

<div class="box plan">
<p><b>Starting point.</b> The no-filter ranking, Top 20, in two forms: weekly with reset to equal (the strongest settings above) and monthly held as bought (fewer trades). Same costs, same design period.</p>
<div class="rule"><b>R1</b> <b>Market switch.</b> Each week, classify the Nifty 500 with the rule the model already uses for ratings (above or below its 200-day average, the average's 20-day slope, a 2% band). When it is risk-off, sell everything and hold cash; buy back at the first weekly check that is not risk-off.</div>
<div class="rule"><b>R2</b> <b>Small-cap switch.</b> The same rule on the equal-weight index of every ranked stock, which tracks the smaller stocks the basket actually holds. In Jan – Mar 2025 the basket fell ${pct(ref.episodes.find((e) => e.peak.startsWith("2025") || e.peak.startsWith("2024-12"))?.dd ?? ref.episodes[2].dd, 0)} while the Nifty 500 fell only ${pct(ref.episodes.find((e) => e.peak.startsWith("2025") || e.peak.startsWith("2024-12"))?.bench ?? ref.episodes[2].bench, 0)}; a Nifty-based switch may never trigger on a fall like that. (This index starts Nov 2018, so the switch can first act around Sep 2019.)</div>
<div class="rule"><b>R3</b> <b>Stop per stock.</b> Sell a holding at the next close after it closes 20% below its highest close since it was bought. Its slot waits in cash until the next rebalance, when it can be refilled by the normal rules.</div>
<div class="rule"><b>R4</b> <b>R2 and R3 together.</b></div>
<p style="margin-top:6pt"><b>How we choose.</b> Of the 8 runs (4 rules × 2 starting points), the one with the highest return a year among those whose worst fall stays inside −20%. If none does, the one with the shallowest worst fall among those that still beat the Nifty 500.</p>
<p><b>How we confirm.</b> The chosen rule and its starting point without the rule are then run once on the sealed 12 months. We adopt it only if, there too, its worst fall is at least a third smaller than the starting point's and it still returns at least as much as the Nifty 500. If it fails, we don't adopt it, and the sealed period is spent.</p>
</div>

<p class="note">Approved as written, with full cash on risk-off, and extended at your request to every combination of R1, R2 and R3 (8 per starting point, 16 runs). The numbers were not tuned.</p>

<h2 class="pb">What happened</h2>
<h3>Design period, 16 runs</h3>
<table><thead><tr><th>Start</th><th>Rules</th><th>Return / yr</th><th>Worst fall</th><th>Return ÷ fall</th><th>Weeks in cash</th><th>Stops</th></tr></thead><tbody>
${p7.out.map((r) => `<tr${r.base === "A" && r.rules === "R2+R3" ? ' class="hi"' : ""}><td>${r.base === "A" ? "Weekly, reset" : "Monthly, hold"}</td><td>${r.rules === "none" ? "none" : r.rules.replaceAll("+", " + ")}</td><td>${pct(r.cagrPct)}</td><td>${pct(r.maxDDPct)}</td><td>${num(r.calmar)}</td><td>${r.offShare.toFixed(0)}%</td><td>${r.stops}</td></tr>`).join("")}
<tr class="bench"><td>Nifty 500</td><td></td><td>${pct(p7.bench.cagrPct)}</td><td>${pct(p7.bench.maxDDPct)}</td><td></td><td></td><td></td></tr></tbody></table>
<p>No run stayed inside −20%. Under the fallback rule, the shallowest worst fall that still beat the Nifty 500 was <b>weekly, reset to equal, with the small-cap switch and the stop (R2 + R3)</b>: ${pct(p7.out.find((r) => r.base === "A" && r.rules === "R2+R3").cagrPct)} a year and ${pct(p7.out.find((r) => r.base === "A" && r.rules === "R2+R3").maxDDPct)}, against ${pct(p7.out.find((r) => r.base === "A" && r.rules === "none").maxDDPct)} without rules. Almost all of that came from the 2020 crash; it barely changed the falls of 2022 and early 2025. That concern was written down before the sealed year was opened.</p>

<h3>The sealed year, run once (${date(ho.verdict.start)} – ${date(ho.verdict.asOf)})</h3>
<table><thead><tr><th></th><th>Return</th><th>Worst fall</th><th>Weeks in cash</th><th>Stops</th></tr></thead><tbody>
<tr><td>Weekly, reset, no rules</td><td>${pct(ho.none.totalPct, 2)}</td><td>${pct(ho.none.maxDDPct)}</td><td>0%</td><td>0</td></tr>
<tr class="hi"><td>Weekly, reset, R2 + R3 (chosen)</td><td>${pct(ho["R2+R3"].totalPct, 2)}</td><td>${pct(ho["R2+R3"].maxDDPct)}</td><td>${ho["R2+R3"].offShare.toFixed(0)}%</td><td>${ho["R2+R3"].stops}</td></tr>
<tr class="bench"><td>Nifty 500</td><td>${pct(ho.nifty.totalPct, 2)}</td><td>${pct(ho.nifty.maxDDPct)}</td><td></td><td></td></tr></tbody></table>
<div class="box"><b>Not adopted.</b> The rule needed a worst fall at least a third smaller than the plain basket's, and got a deeper one (${pct(ho["R2+R3"].maxDDPct)} against ${pct(ho.none.maxDDPct)}). It still beat the Nifty 500, but gave up about ${(ho.none.totalPct - ho["R2+R3"].totalPct).toFixed(0)} points to the plain basket: in cash a fifth of the weeks and stopped out of ${ho["R2+R3"].stops} holdings, it missed rebounds without avoiding the November – March fall. The sealed year is now spent; a new rule can only be confirmed on data from here on.</div>

${ROLLING}

<p class="note" style="margin-top:14pt">Method: every run uses the dashboard's own Returns engine and filter rules (dashboard/lib/returns.mjs) on the stored weekly backtest rankings, stages and ratings, with split-adjusted closes; stocks are bought at the close of the session after the ranking. Return a year is compound (CAGR) from the first purchase to 30 Sep 2025 (the rolling windows each to their own end, the last on 10 Aug 2026); worst fall is the largest peak-to-bottom drop of the daily value after costs, as if sold that day.</p>
</body></html>`;
writeFileSync(out("report.html"), html);
console.log("written", html.length);
