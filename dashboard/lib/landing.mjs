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
      { symbol: "KESARI", name: "Kesari Foods", price: 612.1, day: -0.64, cap: 9320, pe: 31.2, stage: 3 },
      { symbol: "NAVDEEP", name: "Navdeep Chemicals", price: 2290.0, day: 0.88, cap: 21740, pe: 18.9, stage: 2 },
      { symbol: "SAGARIKA", name: "Sagarika Logistics", price: 340.75, day: -1.91, cap: 5110, pe: 14.3, stage: 4 },
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
      { symbol: "LUMEN", name: "Lumenfield Energy", price: 48.9, day: -1.12, cap: 8.6, pe: 12.7, stage: 4 },
      { symbol: "PINEWAY", name: "Pineway Retail", price: 87.15, day: 1.96, cap: 14.3, pe: 19.8, stage: 2 },
      { symbol: "ORCHID", name: "Orchid Biotech", price: 23.47, day: -0.3, cap: 2.1, pe: null, stage: 1 },
      { symbol: "HALCYON", name: "Halcyon Software", price: 311.02, day: 0.45, cap: 92.7, pe: 41.3, stage: 2 },
      { symbol: "BRASSLINE", name: "Brassline Industrial", price: 64.8, day: -0.78, cap: 6.9, pe: 16.5, stage: 3 },
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

export const STAGE_SAMPLE = [
  { symbol: "TARANG", name: "Tarang Power", stage: 2, rs: 91 },
  { symbol: "AARAV", name: "Aarav Industries", stage: 2, rs: 78 },
  { symbol: "KESARI", name: "Kesari Foods", stage: 3, rs: 52 },
  { symbol: "VIHAAN", name: "Vihaan Pharma", stage: 1, rs: 38 },
  { symbol: "SAGARIKA", name: "Sagarika Logistics", stage: 4, rs: 11 },
];
