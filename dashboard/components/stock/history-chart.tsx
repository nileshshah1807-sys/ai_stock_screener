import { formatDate, formatScore } from "@/lib/format";
import type { HistoryRow } from "@/lib/types";

/**
 * Decision score over time.
 *
 * One series, so no legend: the title names it. Direct labels sit on the first
 * and last points rather than every observation, and the rating thresholds are
 * drawn as reference lines because a score's meaning here is entirely relative
 * to which band it falls in.
 */
const WIDTH = 640;
const HEIGHT = 150;
const PAD = { top: 12, right: 44, bottom: 20, left: 30 };

const BANDS = [
  { at: 70, label: "STRONG BUY" },
  { at: 60, label: "BUY" },
  { at: 50, label: "HOLD" },
  { at: 40, label: "REDUCE" },
];

export function HistoryChart({ history }: { history: HistoryRow[] }) {
  const points = history.filter((row) => row.decision_score !== null);

  if (points.length < 2) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {points.length === 1
          ? "Only one observation so far. A trend appears once this stock has been scored on at least two runs."
          : "No scored history yet for this stock."}
      </p>
    );
  }

  const scores = points.map((row) => row.decision_score as number);
  // Pad the domain so the line is never flush against the frame, and always
  // include the 40-70 band range so the reference lines stay meaningful.
  const rawMin = Math.min(...scores, 38);
  const rawMax = Math.max(...scores, 72);
  const min = Math.floor(rawMin / 5) * 5;
  const max = Math.ceil(rawMax / 5) * 5;

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  const x = (index: number) =>
    PAD.left + (index / (points.length - 1)) * plotW;
  const y = (value: number) =>
    PAD.top + plotH - ((value - min) / (max - min)) * plotH;

  const path = points
    .map((row, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(row.decision_score as number).toFixed(1)}`)
    .join(" ");

  const first = points[0];
  const last = points[points.length - 1];

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full"
        role="img"
        aria-label={`Decision score from ${formatScore(first.decision_score)} on ${formatDate(first.observed_on)} to ${formatScore(last.decision_score)} on ${formatDate(last.observed_on)}, across ${points.length} runs.`}
      >
        {BANDS.filter((band) => band.at >= min && band.at <= max).map((band) => (
          <g key={band.at}>
            <line
              x1={PAD.left}
              y1={y(band.at)}
              x2={WIDTH - PAD.right}
              y2={y(band.at)}
              stroke="var(--border)"
              strokeWidth={1}
              strokeDasharray="2 3"
            />
            <text
              x={PAD.left - 5}
              y={y(band.at) + 3}
              textAnchor="end"
              className="fill-muted-foreground"
              style={{ fontSize: 9, fontFamily: "var(--font-mono)" }}
            >
              {band.at}
            </text>
          </g>
        ))}

        <path
          d={path}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Only the endpoints get markers; a dot on every run would turn a
            180-day history into noise. */}
        <circle cx={x(0)} cy={y(first.decision_score as number)} r={3} fill="var(--primary)" />
        <circle
          cx={x(points.length - 1)}
          cy={y(last.decision_score as number)}
          r={3.5}
          fill="var(--primary)"
        />

        <text
          x={x(points.length - 1) + 7}
          y={y(last.decision_score as number) + 4}
          className="fill-foreground"
          style={{ fontSize: 11, fontFamily: "var(--font-mono)", fontWeight: 600 }}
        >
          {formatScore(last.decision_score)}
        </text>

        <text
          x={PAD.left}
          y={HEIGHT - 5}
          className="fill-muted-foreground"
          style={{ fontSize: 9 }}
        >
          {formatDate(first.observed_on)}
        </text>
        <text
          x={WIDTH - PAD.right}
          y={HEIGHT - 5}
          textAnchor="end"
          className="fill-muted-foreground"
          style={{ fontSize: 9 }}
        >
          {formatDate(last.observed_on)}
        </text>
      </svg>

      <figcaption className="sr-only">
        <table>
          <caption>Decision score by run date</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Decision score</th>
              <th scope="col">Rating</th>
            </tr>
          </thead>
          <tbody>
            {points.map((row) => (
              <tr key={row.observed_on}>
                <td>{formatDate(row.observed_on)}</td>
                <td>{formatScore(row.decision_score)}</td>
                <td>{row.rating ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </figcaption>
    </figure>
  );
}
