/**
 * Sample rows for the landing page's product pictures. Every company here is
 * invented and every figure is a placeholder: the pictures show the layout of
 * the screener, not market data, and say so beside them. Nothing on the page
 * reads the database for these.
 */

export const SAMPLE_MARKETS = {
  ind: {
    label: "India",
    money: (v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`,
    cap: (v) => `₹${v.toLocaleString("en-IN")} Cr`,
    rows: [
      { symbol: "AARAV", name: "Aarav Industries", price: 1842.5, day: 1.42, cap: 48210, pe: 24.6, stage: 2 },
      { symbol: "KESARI", name: "Kesari Foods", price: 612.1, day: -0.64, cap: 9320, pe: 31.2, stage: 1 },
      { symbol: "NAVDEEP", name: "Navdeep Chemicals", price: 2290.0, day: 0.88, cap: 21740, pe: 18.9, stage: 2 },
      { symbol: "SAGARIKA", name: "Sagarika Logistics", price: 340.75, day: -1.91, cap: 5110, pe: 14.3, stage: 1 },
      { symbol: "TARANG", name: "Tarang Power", price: 905.3, day: 2.1, cap: 33680, pe: 27.5, stage: 2 },
      { symbol: "VIHAAN", name: "Vihaan Pharma", price: 1288.9, day: 0.12, cap: 15450, pe: 22.1, stage: 1 },
    ],
  },
  us: {
    label: "US",
    money: (v) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
    cap: (v) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 1 })}B`,
    rows: [
      { symbol: "NORTHBAY", name: "Northbay Systems", price: 142.38, day: 0.74, cap: 61.2, pe: 28.4, stage: 2 },
      { symbol: "LUMEN", name: "Lumenfield Energy", price: 48.9, day: -1.12, cap: 8.6, pe: 12.7, stage: 1 },
      { symbol: "PINEWAY", name: "Pineway Retail", price: 87.15, day: 1.96, cap: 14.3, pe: 19.8, stage: 2 },
      { symbol: "ORCHID", name: "Orchid Biotech", price: 23.47, day: -0.3, cap: 2.1, pe: null, stage: 1 },
      { symbol: "HALCYON", name: "Halcyon Software", price: 311.02, day: 0.45, cap: 92.7, pe: 41.3, stage: 2 },
      { symbol: "BRASSLINE", name: "Brassline Industrial", price: 64.8, day: -0.78, cap: 6.9, pe: 16.5, stage: 2 },
    ],
  },
};

/** The rows a chip leaves showing; no chip leaves all of them. */
export function sampleRows(market, onlyStage2) {
  const rows = SAMPLE_MARKETS[market]?.rows ?? [];
  return onlyStage2 ? rows.filter((row) => row.stage === 2) : rows;
}

/**
 * Invented rows for the Stage and RS picture. `rs` is a 1-99 percentile within
 * the stock's own market, the same scale the screener prints.
 */
export const STAGES = [
  { stage: 1, name: "Basing", rule: "Price drifting sideways under flat averages." },
  { stage: 2, name: "Advancing", rule: "Price above the 50, 150 and 200-day averages, stacked in that order, with the 200-day rising." },
  { stage: 3, name: "Topping", rule: "Price slips under the 150-day average while the long averages still hold up." },
  { stage: 4, name: "Declining", rule: "Price under a falling 200-day average, and the 150-day below it or falling." },
];

/** The Stage 2 shape pulled back (stage.py's S2 Candidate), shown under the four stages. */
export const S2_CANDIDATE_RULE = "A Stage 2 shape without the full stack, usually a pullback under the 50-day average; price still above the 150 and 200-day.";


/** Plain words for the Stage numbers wherever the landing shows a stage. */
export const STAGE_WORD = { 1: "Basing", 2: "Advancing", 3: "Topping", 4: "Declining" };

/** Deterministic pseudo-random in [0, 1): the pictures must be the same on server and client. */
export function seeded(seed) {
  let x = seed >>> 0 || 1;
  return () => {
    x ^= x << 13; x >>>= 0;
    x ^= x >>> 17;
    x ^= x << 5; x >>>= 0;
    return x / 4294967296;
  };
}

/**
 * The sieve: one dot per stock, the gates it falls through and where each rests.
 * `fate` is the gate a dot stops at (0..gates-1) or `gates` for a dot that passes them all.
 * An illustration with no data in it: the dots stand for stocks, not for any stock.
 */
export const SIEVE_GATES = [
  ["Liquidity", "Can it be traded?"],
  ["Quality", "Are the basics sound?"],
  ["Trend", "Is price out of a downtrend?"],
];
export function sieveDots({ count = 84, survivors = 6, width = 480, top = 14, gateYs = [118, 170, 222], rowY = 276 } = {}) {
  const rand = seeded(20261106);
  const gates = gateYs.length;
  // Of what is left at each gate, roughly 38%, 33% and 30% stop there; the last fix makes the survivors exact.
  const share = [0.38, 0.33, 0.3];
  const fates = [];
  let alive = count;
  for (let g = 0; g < gates; g++) {
    const out = Math.round(alive * share[g]);
    for (let i = 0; i < out; i++) fates.push(g);
    alive -= out;
  }
  while (alive > survivors) { fates.push(gates - 1); alive--; }
  while (alive < survivors) { fates.pop(); alive++; }
  for (let i = 0; i < alive; i++) fates.push(gates);
  // Shuffle so the fates are spread across the cloud.
  for (let i = fates.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [fates[i], fates[j]] = [fates[j], fates[i]];
  }
  let rank = 0;
  const gap = (width - 120) / (survivors - 1);
  return fates.map((fate, i) => {
    const startX = 24 + rand() * (width - 48);
    const startY = top + rand() * 36;
    if (fate === gates) {
      const n = rank++;
      return { id: i, fate, startX, startY, x: 60 + n * gap, y: rowY, rank: n + 1 };
    }
    return { id: i, fate, startX, startY, x: startX, y: gateYs[fate] - 7 - rand() * 9, rank: null };
  });
}

/**
 * An invented price history with its 50, 150 and 200-day averages and the four
 * stage bands, for the Stage picture. The first 200 points only feed the long
 * average; the last `shown` are drawn.
 */
export function stageSeries({ total = 420, shown = 220 } = {}) {
  const rand = seeded(7);
  const phase = (t) => {
    const u = t - (total - shown); // 0..shown over the drawn part
    if (u < 0) return 100 + t * 0.01;
    if (u < 45) return 101;
    if (u < 125) return 101 + ((u - 45) / 80) ** 1.1 * 66;
    if (u < 160) return 167 + Math.sin((u - 125) / 4) * 3;
    return 166 - ((u - 160) / 60) ** 1.2 * 52;
  };
  const price = Array.from({ length: total }, (_, t) => phase(t) + (rand() - 0.5) * 3.2);
  const sma = (n) => price.map((_, t) => (t < n - 1 ? null : price.slice(t - n + 1, t + 1).reduce((a, b) => a + b, 0) / n));
  const cut = total - shown;
  const part = (arr) => arr.slice(cut);
  return {
    price: part(price),
    ma50: part(sma(50)),
    ma150: part(sma(150)),
    ma200: part(sma(200)),
    // Band edges as a share of the drawn width.
    bands: [
      { stage: 1, from: 0, to: 45 / shown },
      { stage: 2, from: 45 / shown, to: 125 / shown },
      { stage: 3, from: 125 / shown, to: 160 / shown },
      { stage: 4, from: 160 / shown, to: 1 },
    ],
  };
}

/** The blocks the ranking weighs and each one's current share (screener/runtime.py), the same in both markets. */
export const FACTORS = [
  { key: "momentum", label: "Momentum", weight: 30 },
  { key: "quality", label: "Quality", weight: 25 },
  { key: "growth", label: "Growth", weight: 25 },
  { key: "value", label: "Value", weight: 15 },
  { key: "risk", label: "Risk", weight: 5 },
];

/** The evening, in order. Times are an example evening, not a schedule. */
export const EVENING = [
  ["15:30", "Market closes"],
  ["18:10", "A company files results"],
  ["18:25", "Its card is on the Results page"],
  ["20:40", "The call is read, its tone scored"],
  ["21:10", "The bell tells you"],
];
/** How far (same unit) each label must move down so neighbours sit at least `gap` apart; 0 where there is room. */
export function labelShifts(positions, gap) {
  let prev = -Infinity;
  return positions.map((at) => {
    const placed = Math.max(at, prev + gap);
    prev = placed;
    return placed - at;
  });
}
/** The axis the evening is drawn on, in minutes after midnight. */
export const EVENING_AXIS = { from: 15 * 60 + 30, to: 22 * 60 };
/** Where a "HH:MM" time falls along the axis, as 0..1, to scale. */
export function eveningPosition(time) {
  const [h, m] = time.split(":").map(Number);
  return (h * 60 + m - EVENING_AXIS.from) / (EVENING_AXIS.to - EVENING_AXIS.from);
}

/** Management-tone cuts as the app reads them (sentiment.outlook.stance_from_score), and the median call. */
export const TONE = {
  min: 35,
  max: 85,
  median: 59,
  cuts: [
    [45, "Cautious"],
    [53, "Neutral"],
    [62, "Optimistic"],
    [72, "Bullish"],
  ],
  first: "Bearish",
  sample: 66,
};
