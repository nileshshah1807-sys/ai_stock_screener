import Link from "next/link";
import { ChevronRight, Mic } from "lucide-react";

import { MISSING } from "@/lib/format";
import { highlightList, outlookTone, sourceLabel, stanceLabel } from "@/lib/concalls.mjs";
import type { Concall } from "@/lib/concalls";
import { marketPath, type Market } from "@/lib/markets";
import { cn } from "@/lib/utils";

const TONES: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  muted: "text-muted-foreground",
};

/**
 * One highlight. With a quote it opens to the sentence it was read from --
 * the same disclosure the stock page's "What management said" uses, so a
 * claim about a call is always one click from management's own words.
 */
export function Highlight({ item }: { item: { text: string; tone: string; quote: string } }) {
  const dot = (
    <span
      aria-hidden
      className={cn(
        "mt-[0.45em] size-1.5 shrink-0 rounded-full",
        item.tone === "negative" ? "bg-negative" : "bg-positive",
      )}
    />
  );
  // Tone is carried by the dot's colour and, for a screen reader, in words.
  const tone = <span className="sr-only">{item.tone === "negative" ? "Negative: " : "Positive: "}</span>;

  if (!item.quote) {
    return (
      <div className="flex items-start gap-2">
        {dot}
        <span className="min-w-0 flex-1 break-words">
          {tone}
          {item.text}
        </span>
      </div>
    );
  }
  return (
    <details className="group/item">
      <summary className="flex cursor-pointer items-start gap-2 rounded marker:content-none hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        {dot}
        <span className="min-w-0 flex-1 break-words">
          {tone}
          {item.text}
        </span>
        <ChevronRight
          className="mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-transform group-open/item:rotate-90"
          aria-hidden
        />
      </summary>
      <blockquote className="mb-1 ml-3.5 mt-1.5 border-l-2 border-border pl-3 text-[13px] leading-relaxed text-muted-foreground">
        &ldquo;{item.quote}&rdquo;
      </blockquote>
    </details>
  );
}

function Measure({
  label,
  value,
  title,
  tone,
}: {
  label: string;
  value: string;
  /** Shown on hover: the sentence a judgment was read from. */
  title?: string | null;
  tone?: string | null;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd
        title={title || undefined}
        className={cn("text-sm font-semibold", tone ? TONES[tone] : "", title ? "cursor-help" : "")}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * One call: who, where its text came from, what it said, how it scored.
 *
 * A card that reflows rather than a table row. The highlights are sentences
 * and each can open to a quote, which a fixed-height row cannot hold; and on
 * a phone the three blocks stack in the order a reader wants them.
 *
 * A call with no stance or outlook shows a dash, not a neutral word: not
 * read is not the same as read-and-average.
 */
export function ConcallRow({ call, market }: { call: Concall; market: Market }) {
  const source = sourceLabel(call.source);
  const stance = stanceLabel(call.management_stance, call.management_stance_quote);
  const highlights = highlightList(call.highlights);
  const outlook = call.outlook_score;

  return (
    <div className="grid gap-x-6 gap-y-3 px-4 py-3.5 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_minmax(0,13rem)]">
      <div className="min-w-0">
        <Link
          href={marketPath(market.slug, `/stocks/${encodeURIComponent(call.symbol)}`)}
          // A season's worth of rows would otherwise prefetch that many stock pages.
          prefetch={false}
          className="group block rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="block font-mono text-xs font-semibold underline-offset-2 group-hover:underline">
            {call.symbol}
          </span>
          <span className="block truncate text-xs text-muted-foreground">
            {call.company ?? MISSING}
          </span>
        </Link>
        <span
          title={source.title}
          className={cn(
            "mt-1.5 inline-flex cursor-help items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
            source.provisional
              ? "bg-(--control) text-foreground"
              : "text-muted-foreground ring-1 ring-inset ring-border",
          )}
        >
          {source.provisional ? <Mic className="size-3" aria-hidden /> : null}
          {source.label}
        </span>
      </div>

      <div className="min-w-0 space-y-1.5 text-sm">
        {highlights.length ? (
          highlights.map((item, index) => <Highlight key={index} item={item} />)
        ) : (
          <p className="text-xs text-muted-foreground">
            {outlook === null
              ? "Not read for its outlook yet."
              : "Nothing the call stated moved its outlook."}
          </p>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 md:justify-items-end md:text-right">
        <Measure
          label="Management stance"
          value={stance?.label ?? MISSING}
          title={stance?.quote ? `\u201c${stance.quote}\u201d` : null}
          tone={stance?.tone}
        />
        <Measure
          label="Outlook"
          value={outlook === null ? MISSING : String(Math.round(outlook))}
          tone={outlookTone(outlook)}
        />
      </dl>
    </div>
  );
}
