import assert from "node:assert/strict";
import test from "node:test";

import {
  clipFrom,
  decodeDeltas,
  decodeSeries,
  movingAverage,
  sliceRange,
} from "./price-series.mjs";

/** Mirror of workers/price_series.py encode_deltas, so both halves are tested. */
function encode(values) {
  if (!values.length) return "[]";
  const out = [values[0]];
  for (let i = 1; i < values.length; i += 1) out.push(values[i] - values[i - 1]);
  return JSON.stringify(out);
}

const SESSIONS = Array.from({ length: 10 }, (_, i) => {
  const d = new Date(Date.UTC(2024, 0, 1 + i));
  return d.toISOString().slice(0, 10);
});

function row(indices, closesPaise, volumes) {
  return {
    session_deltas: encode(indices),
    closes: encode(closesPaise),
    volumes: encode(volumes),
  };
}

test("delta decoding reverses the encoding", () => {
  const values = [12345, 12350, 12290, 99999, 1, 0, 500000];
  assert.deepEqual(decodeDeltas(encode(values)), values);
});

test("a long delta chain does not drift", () => {
  const values = Array.from({ length: 5000 }, (_, i) => 10000 + ((i * 37) % 5000));
  assert.deepEqual(decodeDeltas(encode(values)), values);
});

test("empty and missing input decode to an empty array", () => {
  assert.deepEqual(decodeDeltas("[]"), []);
  assert.deepEqual(decodeDeltas(null), []);
  assert.deepEqual(decodeDeltas(undefined), []);
});

test("a dense series decodes to the original rupee prices", () => {
  const indices = [0, 1, 2, 3];
  const encoded = row(indices, [10000, 10150, 9975, 10500], [10, 20, 30, 40]);
  const { ok, points } = decodeSeries(encoded, SESSIONS);
  assert.equal(ok, true);
  assert.deepEqual(
    points.map((p) => p.close),
    [100, 101.5, 99.75, 105],
  );
  assert.deepEqual(
    points.map((p) => p.time),
    SESSIONS.slice(0, 4),
  );
});

test("untraded sessions stay gaps instead of being filled", () => {
  const { points } = decodeSeries(row([0, 4, 9], [100, 200, 300], [1, 1, 1]), SESSIONS);
  assert.deepEqual(
    points.map((p) => p.time),
    [SESSIONS[0], SESSIONS[4], SESSIONS[9]],
  );
});

test("misaligned arrays fail closed rather than drawing wrong prices", () => {
  const bad = {
    session_deltas: encode([0, 1, 2]),
    closes: encode([100, 200]),
    volumes: encode([1, 1, 1]),
  };
  const { ok, points } = decodeSeries(bad, SESSIONS);
  assert.equal(ok, false);
  assert.deepEqual(points, []);
});

test("a point past the end of the calendar is skipped, not plotted at the epoch", () => {
  const { points } = decodeSeries(row([0, 99], [100, 200], [1, 1]), SESSIONS);
  assert.equal(points.length, 1);
  assert.equal(points[0].time, SESSIONS[0]);
});

test("a null row yields nothing instead of throwing", () => {
  assert.deepEqual(decodeSeries(null, SESSIONS), { ok: false, points: [] });
  assert.deepEqual(decodeSeries(row([0], [1], [1]), []), { ok: false, points: [] });
});

test("moving average emits nothing until its window is full", () => {
  const points = Array.from({ length: 5 }, (_, i) => ({
    time: SESSIONS[i],
    close: i + 1,
  }));
  const ma = movingAverage(points, 3);
  assert.equal(ma.length, 3);
  assert.equal(ma[0].time, SESSIONS[2]);
  assert.equal(ma[0].value, 2); // (1+2+3)/3
  assert.equal(ma[2].value, 4); // (3+4+5)/3
});

test("a window longer than the series produces no line at all", () => {
  const points = [{ time: SESSIONS[0], close: 10 }];
  assert.deepEqual(movingAverage(points, 200), []);
});

test("moving average is numerically stable over a long series", () => {
  const points = Array.from({ length: 3000 }, (_, i) => ({
    time: `2024-01-${i}`,
    close: 100 + Math.sin(i / 10) * 5,
  }));
  const ma = movingAverage(points, 200);
  const last = ma[ma.length - 1].value;
  const expected =
    points.slice(-200).reduce((sum, p) => sum + p.close, 0) / 200;
  // The rolling sum must not have accumulated error against a direct mean.
  assert.ok(Math.abs(last - expected) < 1e-9, `${last} vs ${expected}`);
});

test("range slicing takes the trailing window", () => {
  const points = SESSIONS.map((time, i) => ({ time, close: i }));
  assert.equal(sliceRange(points, 3).length, 3);
  assert.equal(sliceRange(points, 3)[0].time, SESSIONS[7]);
  assert.equal(sliceRange(points, null).length, 10);
  assert.equal(sliceRange(points, 999).length, 10);
});

test("averages are clipped to the view, not recomputed inside it", () => {
  // The point of computing on the full series: a 1M view still shows a true
  // 200-day average rather than one restarted at the window's left edge.
  const points = Array.from({ length: 400 }, (_, i) => ({
    time: `2024-${String(i).padStart(4, "0")}`,
    close: 100,
  }));
  const ma = movingAverage(points, 200);
  const visible = sliceRange(points, 30);
  const clipped = clipFrom(ma, visible[0].time);
  assert.equal(clipped.length, 30);
  assert.equal(clipped[0].value, 100);
});
