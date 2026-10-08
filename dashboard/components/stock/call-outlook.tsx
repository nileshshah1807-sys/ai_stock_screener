import { ArrowDownRight, ArrowUpRight, Check, ChevronRight, Minus } from "lucide-react";

import { callOutlook, followThrough } from "@/lib/call-outlook.mjs";
import { formatDate, formatScore } from "@/lib/format";

const MISSING = "—";

const TONES: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  muted: "text-muted-foreground",
  default: "text-foreground",
};

function signed(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

function ChangeIcon({ change }: { change: string }) {
  if (change === "worse") return <ArrowDownRight className="size-3.5 text-negative" aria-hidden />;
  if (change === "better") return <ArrowUpRight className="size-3.5 text-positive" aria-hidden />;
  if (change === "kept") return <Check className="size-3.5 text-muted-foreground" aria-hidden />;
  return <Minus className="size-3.5 text-muted-foreground" aria-hidden />;
}

function Points({ value }: { value: number }) {
  return (
    <span
      className={`tabular shrink-0 font-mono text-xs ${value > 0 ? "text-positive" : "text-negative"}`}
    >
      {signed(value)}
    </span>
  );
}

/**
 * One scored statement. With a quote it opens to the sentence; without one it
 * is a plain row, indented to the same edge so the labels stay in one column.
 */
function ScoredItem({ item }: { item: { reason: string; points: number; quote: string } }) {
  if (!item.quote) {
    return (
      <div className="flex items-baseline gap-2 py-2 pl-[22px]">
        <span className="min-w-0 flex-1 break-words">{item.reason}</span>
        <Points value={item.points} />
      </div>
    );
  }
  return (
    <details className="group/item">
      <summary className="flex cursor-pointer items-baseline gap-2 rounded py-2 marker:content-none hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-3.5 shrink-0 translate-y-0.5 text-muted-foreground transition-transform group-open/item:rotate-90"
          aria-hidden
        />
        <span className="min-w-0 flex-1 break-words">{item.reason}</span>
        <Points value={item.points} />
      </summary>
      <blockquote className="mb-3 ml-[22px] border-l-2 border-border pl-3 text-[13px] leading-relaxed text-muted-foreground">
        &ldquo;{item.quote}&rdquo;
      </blockquote>
    </details>
  );
}

const CHANGE_LABELS: Record<string, string> = {
  worse: "Weaker",
  better: "Stronger",
  kept: "Unchanged",
  not_restated: "Not restated",
};

/**
 * What management said on the latest call, and whether it kept to the last one.
 *
 * The tone score above measures how a call sounds. This is what it said:
 * guidance, order book, capacity, demand and margins, each kept only if the
 * sentence it came from was found in the transcript. The points are the
 * breakdown of the outlook score, which shares the transcript weight with tone.
 *
 * That sentence is one click away rather than on the page. Eight quotes of two
 * lines each would bury the breakdown they support; closed, a row is a label
 * and a number, and opening it gives management's own words for that one item.
 *
 * The comparison with the previous call is display evidence: it is not in the
 * score. "Kept" means the two calls agree, not that results met the guidance.
 *
 * Renders nothing without an outlook. A company with no call, or a call nothing
 * verifiable was drawn from, has no outlook -- which is not a neutral one.
 */
export function CallOutlook({ payload }: { payload: Record<string, unknown> }) {
  const outlook = callOutlook(payload);
  if (!outlook) return null;

  const against =
    outlook.median === null ? null : Math.round((outlook.score - outlook.median) * 10) / 10;
  const kept = followThrough(outlook.previous);
  const previous = outlook.previous;

  return (
    <section className="panel p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-heading font-semibold">What management said</h2>
        <p className="text-[11px] text-muted-foreground">
          {outlook.callDate ? `Call of ${formatDate(outlook.callDate)} · ` : ""}
          {outlook.applied ? "In the score, with the tone of the call" : "Shown for context; not in the score"}
        </p>
      </div>

      <dl className="mt-4 grid grid-cols-1 gap-px overflow-hidden rounded-row bg-border sm:grid-cols-3">
        <div className="bg-muted/40 px-4 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Outlook score</dt>
          <dd className="tabular mt-0.5 text-sm font-semibold">{formatScore(outlook.score)}</dd>
          <dd className="mt-0.5 text-[11px] text-muted-foreground">
            {against === null
              ? "0–100; 50 is a call that said nothing either way"
              : `${signed(against)} against the median call (${formatScore(outlook.median)})`}
          </dd>
        </div>
        <div className="bg-muted/40 px-4 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Previous call</dt>
          <dd className="tabular mt-0.5 text-sm font-semibold">
            {previous ? formatScore(previous.score) : MISSING}
          </dd>
          <dd className="mt-0.5 text-[11px] text-muted-foreground">
            {previous
              ? `${previous.callDate ? `${formatDate(previous.callDate)} · ` : ""}${signed(previous.delta)} since`
              : "No earlier call to compare with"}
          </dd>
        </div>
        <div className="bg-muted/40 px-4 py-3">
          <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Kept to its word</dt>
          <dd className={`mt-0.5 text-sm font-semibold ${TONES[kept?.tone ?? "muted"]}`}>
            {kept ? kept.label : MISSING}
          </dd>
          <dd className="mt-0.5 text-[11px] text-muted-foreground">
            Call against call, not results against guidance
          </dd>
        </div>
      </dl>

      <div className="mt-5 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Behind the score
            </h3>
            {outlook.points.some((item) => item.quote) ? (
              <p className="text-[11px] text-muted-foreground">Open an item for management&rsquo;s words</p>
            ) : null}
          </div>
          {outlook.points.length ? (
            <ul className="mt-2 divide-y divide-border">
              {outlook.points.map((item) => (
                <li key={item.reason} className="text-sm">
                  <ScoredItem item={item} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              Nothing in the call moved the score from 50.
            </p>
          )}
        </div>

        <div>
          <h3 className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Since the previous call
          </h3>
          {previous && previous.changes.length ? (
            <ul className="mt-2 divide-y divide-border">
              {previous.changes.map((item) => (
                <li key={item.text} className="flex items-start gap-2 py-2 text-sm">
                  <span className="mt-0.5 shrink-0">
                    <ChangeIcon change={item.change} />
                  </span>
                  <span className="min-w-0 break-words">
                    <span className="sr-only">{CHANGE_LABELS[item.change]}: </span>
                    {item.text}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              {previous
                ? "The two calls stated nothing in common to compare."
                : "This is the first call on record for this company."}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
