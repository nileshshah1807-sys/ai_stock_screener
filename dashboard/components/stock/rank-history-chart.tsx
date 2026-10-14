import { formatDate, formatInteger } from "@/lib/format";
import type { HistoryRow } from "@/lib/types";

/**
 * Investment rank over time.
 *
 * Rank is what the screen is read by, and unlike the decision score it does
 * not drift when the whole universe moves together, so this is the history a
 * reader can act on. The axis is inverted -- #1 at the top -- so "up" still
 * means "better". The domain fits this stock's own range: a move from #40 to
 * #12 would be invisible on a 1-to-2,400 axis.
 */
const WIDTH = 640;
const HEIGHT = 150;
const PAD = { top: 12, right: 52, bottom: 20, left: 40 };

const STEPS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000];

/** A tick step that gives at most four gridline gaps across `span` ranks. */
function tickStep(span: number): number {
  return STEPS.find((step) => span / step <= 4) ?? STEPS[STEPS.length - 1];
}

const rankLabel = (rank: number) => `#${formatInteger(rank)}`;

export function RankHistoryChart({ history }: { history: HistoryRow[] }) {
  const points = history.filter((row) => row.investment_rank !== null);

  if (points.length < 2) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {points.length === 1
          ? "Only one observation so far. A trend appears once this stock has been ranked on at least two runs."
          : "No ranked history yet for this stock."}
      </p>
    );
  }

  const ranks = points.map((row) => row.investment_rank as number);
  const step = tickStep(Math.max(...ranks) - Math.min(...ranks));
  // Snap the domain to whole steps so the line never sits on the frame. Rank
  // cannot be better than #1, so the top edge stops there.
  const best = Math.max(1, Math.floor((Math.min(...ranks) - 1) / step) * step);
  const worst = Math.ceil((Math.max(...ranks) + 1) / step) * step;

  const ticks: number[] = [];
  for (let tick = Math.ceil(best / step) * step; tick <= worst; tick += step) {
    ticks.push(tick);
  }
  if (best === 1 && ticks[0] !== 1) ticks.unshift(1);

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  const x = (index: number) =>
    PAD.left + (index / (points.length - 1)) * plotW;
  // Inverted: the best rank in view is drawn at the top.
  const y = (rank: number) =>
    PAD.top + ((rank - best) / (worst - best)) * plotH;

  const path = points
    .map((row, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(row.investment_rank as number).toFixed(1)}`)
    .join(" ");

  const first = points[0];
  const last = points[points.length - 1];
  const firstRank = first.investment_rank as number;
  const lastRank = last.investment_rank as number;

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full"
        role="img"
        aria-label={`Rank from ${rankLabel(firstRank)} on ${formatDate(first.observed_on)} to ${rankLabel(lastRank)} on ${formatDate(last.observed_on)}, across ${points.length} runs.`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              y1={y(tick)}
              x2={WIDTH - PAD.right}
              y2={y(tick)}
              stroke="var(--border)"
              strokeWidth={1}
              strokeDasharray="2 3"
            />
            <text
              x={PAD.left - 5}
              y={y(tick) + 3}
              textAnchor="end"
              className="fill-muted-foreground"
              style={{ fontSize: 9, fontFamily: "var(--font-mono)" }}
            >
              {rankLabel(tick)}
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
        <circle cx={x(0)} cy={y(firstRank)} r={3} fill="var(--primary)" />
        <circle cx={x(points.length - 1)} cy={y(lastRank)} r={3.5} fill="var(--primary)" />

        <text
          x={x(points.length - 1) + 7}
          y={y(lastRank) + 4}
          className="fill-foreground"
          style={{ fontSize: 11, fontFamily: "var(--font-mono)", fontWeight: 600 }}
        >
          {rankLabel(lastRank)}
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
          <caption>Investment rank by run date</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Rank</th>
              <th scope="col">Rating</th>
            </tr>
          </thead>
          <tbody>
            {points.map((row) => (
              <tr key={row.observed_on}>
                <td>{formatDate(row.observed_on)}</td>
                <td>{rankLabel(row.investment_rank as number)}</td>
                <td>{row.rating ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </figcaption>
    </figure>
  );
}
