import { FACTORS } from "@/lib/landing.mjs";

/** Fill for each block, darkest first; neutral ink at five strengths, so no block reads as the good one. */
const SHADES = ["bg-foreground/55", "bg-foreground/42", "bg-foreground/32", "bg-foreground/22", "bg-foreground/14"];

/**
 * What the ranking weighs: five blocks, one bar, widths in proportion to each
 * block's current weight. The same in both markets. The names and numbers are
 * listed under the bar, so nothing depends on a label fitting inside a segment.
 */
export function FactorBar() {
  return (
    <figure>
      <div aria-hidden className="flex h-10 overflow-hidden rounded-md border">
        {FACTORS.map((f, i) => (
          <div key={f.key} style={{ width: `${f.weight}%` }} className={`${SHADES[i]} ${i > 0 ? "border-l border-background" : ""}`} />
        ))}
      </div>
      <ul className="mt-4 grid gap-2 sm:grid-cols-5">
        {FACTORS.map((f, i) => (
          <li key={f.key} className="flex items-center gap-2 text-sm sm:block">
            <span aria-hidden className={`inline-block size-3 shrink-0 rounded-sm border sm:mb-1 sm:block ${SHADES[i]}`} />
            <span className="font-medium">{f.label}</span>
            <span className="tabular-nums text-muted-foreground sm:block"> {f.weight}%</span>
          </li>
        ))}
      </ul>
      <figcaption className="mt-4 text-xs text-muted-foreground">
        Current weight of each block in the ranking. India: management tone from the latest call adjusts the ranking for companies with a call.
      </figcaption>
    </figure>
  );
}
