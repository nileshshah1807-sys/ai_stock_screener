import { test } from "node:test";
import assert from "node:assert/strict";

import { flowSessions, netOver } from "./fii-dii.mjs";

// Shape of workers/market_flows.py's rows (synthetic values).
const ROWS = [
  { session_date: "2026-11-18", category: "DII", buy_value: 120, sell_value: 100, net_value: 20 },
  { session_date: "2026-11-17", category: "FII", buy_value: 90, sell_value: 140, net_value: -50 },
  { session_date: "2026-11-18", category: "FII", buy_value: "80.5", sell_value: 100, net_value: "-19.5" },
  { session_date: "2026-11-17", category: "PRO", buy_value: 1, sell_value: 1, net_value: 0 },
  { session_date: "bad", category: "FII", buy_value: 1, sell_value: 1, net_value: 0 },
];

test("flowSessions groups by session, oldest first, and skips other categories", () => {
  const sessions = flowSessions(ROWS);
  assert.deepEqual(sessions.map((entry) => entry.session), ["2026-11-17", "2026-11-18"]);
  assert.equal(sessions[0].DII, null);
  assert.deepEqual(sessions[1].FII, { buy: 80.5, sell: 100, net: -19.5 });
});

test("netOver sums only the sessions that reported, never treating a gap as zero", () => {
  const sessions = flowSessions(ROWS);
  assert.deepEqual(netOver(sessions, "FII", 5), { net: -69.5, sessions: 2 });
  assert.deepEqual(netOver(sessions, "DII", 5), { net: 20, sessions: 1 });
  assert.deepEqual(netOver(sessions, "DII", 1), { net: 20, sessions: 1 });
  assert.deepEqual(netOver([], "FII", 5), { net: null, sessions: 0 });
});
