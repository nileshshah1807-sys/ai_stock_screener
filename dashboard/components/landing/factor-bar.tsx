import { FACTORS } from "@/lib/landing.mjs";

/**
 * What the ranking reads: the five blocks by name and plain meaning, the same
 * words the builder and the stock page use (lib/custom-score.mjs). No weights
 * and nothing sized by one: the model's mix is not published.
 */
export function FactorBar() {
  return (
    <figure>
      <ul className="grid gap-x-6 gap-y-4 sm:grid-cols-5">
        {FACTORS.map((f) => (
          <li key={f.key} className="border-t pt-3 text-sm">
            <span className="font-medium">{f.label}</span>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{f.caption}</p>
          </li>
        ))}
      </ul>
      <figcaption className="mt-5 text-xs text-muted-foreground">
        The same five in both markets. India: management tone from the latest call adjusts the ranking for companies with a call.
      </figcaption>
    </figure>
  );
}
