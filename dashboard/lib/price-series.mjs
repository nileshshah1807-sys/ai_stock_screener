/**
 * Reader for the encoded daily price series.
 *
 * The writer is `workers/price_series.py`; this is the other half of that
 * contract and the two must agree exactly. Three delta-encoded JSON arrays per
 * symbol -- positions in the shared trading calendar, adjusted close in paise,
 * and volume -- chosen because a price series is smooth, so successive
 * differences are one or two digits where absolute values are six.
 *
 * A gap in `sessionDeltas` is a session the symbol did not trade. It is left as
 * a gap rather than forward-filled: a thin stock that traded eleven times in a
 * year should look like eleven observations, not a flat line.
 */

/** Paise per rupee. Prices are stored as integers to avoid float drift. */
const PAISE = 100;

/**
 * Undo delta encoding.
 *
 * @param {string | null | undefined} text
 * @returns {number[]}
 */
export function decodeDeltas(text) {
  if (!text) return [];
  const numbers = JSON.parse(text);
  if (!Array.isArray(numbers) || numbers.length === 0) return [];
  const out = new Array(numbers.length);
  out[0] = numbers[0];
  for (let index = 1; index < numbers.length; index += 1) {
    out[index] = out[index - 1] + numbers[index];
  }
  return out;
}

/**
 * Expand an encoded row into ascending `{ time, close, volume }` points.
 *
 * `time` is a plain `YYYY-MM-DD` string, which is what lightweight-charts wants
 * for a daily series -- passing epoch seconds would re-introduce the timezone
 * question that a daily bar does not have.
 *
 * Returns `[]` rather than throwing on a malformed row, because a broken chart
 * must not take the rest of the stock page down with it. Misalignment is
 * reported through `ok` so a caller can surface it.
 *
 * @param {{session_deltas: string, closes: string, volumes: string} | null | undefined} row
 * @param {string[]} sessions ISO dates, ascending
 * @returns {{ok: boolean, points: {time: string, close: number, volume: number}[]}}
 */
export function decodeSeries(row, sessions) {
  if (!row || !sessions?.length) return { ok: false, points: [] };

  const indices = decodeDeltas(row.session_deltas);
  const closes = decodeDeltas(row.closes);
  const volumes = decodeDeltas(row.volumes);

  if (indices.length !== closes.length || indices.length !== volumes.length) {
    return { ok: false, points: [] };
  }

  const points = [];
  for (let index = 0; index < indices.length; index += 1) {
    const day = sessions[indices[index]];
    // A position past the end of the calendar means the series was published
    // against a newer calendar than the one read. Skip rather than plotting the
    // point at `undefined`, which lightweight-charts renders at the epoch.
    if (day === undefined) continue;
    points.push({
      time: day,
      close: closes[index] / PAISE,
      volume: volumes[index],
    });
  }
  return { ok: true, points };
}

/**
 * Simple moving average over `close`, aligned to the same points.
 *
 * Emits nothing until the window is full. A 200-day average computed from 30
 * observations is not a 200-day average, and drawing it would put a confident
 * line in exactly the region where there is least information.
 *
 * @param {{time: string, close: number}[]} points
 * @param {number} window
 * @returns {{time: string, value: number}[]}
 */
export function movingAverage(points, window) {
  if (!points?.length || window < 1) return [];
  const out = [];
  let sum = 0;
  for (let index = 0; index < points.length; index += 1) {
    sum += points[index].close;
    if (index >= window) sum -= points[index - window].close;
    if (index >= window - 1) {
      out.push({ time: points[index].time, value: sum / window });
    }
  }
  return out;
}

/** Range buttons, in trading sessions. `null` means the whole series. */
export const RANGES = [
  { label: "1M", sessions: 21 },
  { label: "6M", sessions: 126 },
  { label: "1Y", sessions: 252 },
  { label: "3Y", sessions: 756 },
  { label: "5Y", sessions: 1260 },
  { label: "Max", sessions: null },
];

/**
 * The trailing slice a range button selects.
 *
 * Moving averages are computed on the *full* series and sliced afterwards, so
 * a 1M view still shows a true 200-day average rather than one restarted from
 * the left edge of the window. That is the difference between an average and a
 * line that merely looks like one.
 *
 * @template {{time: string}} T
 * @param {T[]} points
 * @param {number | null} sessions
 * @returns {T[]}
 */
export function sliceRange(points, sessions) {
  if (!points?.length) return [];
  if (!sessions || sessions >= points.length) return points;
  return points.slice(points.length - sessions);
}

/**
 * Trim a series to the visible window, keeping only what overlaps it.
 *
 * @template {{time: string}} T
 * @param {T[]} series
 * @param {string | undefined} from ISO date of the first visible point
 * @returns {T[]}
 */
export function clipFrom(series, from) {
  if (!from) return series;
  return series.filter((point) => point.time >= from);
}
