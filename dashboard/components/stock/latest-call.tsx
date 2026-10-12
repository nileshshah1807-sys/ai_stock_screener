import { Highlight } from "@/components/concalls/concall-row";
import { highlightList, outlookTone, sourceLabel } from "@/lib/concalls.mjs";
import type { Concall } from "@/lib/concalls";
import { formatDate, formatScore } from "@/lib/format";

const TONES: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  muted: "text-muted-foreground",
};

/**
 * A call held since the published run, shown ahead of the run that will score it.
 *
 * Everything else on this page is one run's evidence, and "What management
 * said" below is the call that run scored. A call transcribed this evening is
 * stored and read for its outlook within the hour, but the screener next runs
 * tomorrow -- so for a day the page would describe last quarter's call while
 * the Concalls page showed this quarter's. This panel closes that gap and says
 * plainly that the call is not in the score yet.
 *
 * It disappears on its own: once a run has scored the call, the page's own
 * call date catches up and the caller passes null.
 */
export function LatestCall({ call }: { call: Concall | null }) {
  if (!call) return null;
  const source = sourceLabel(call.source);
  const highlights = highlightList(call.highlights);
  const tone = outlookTone(call.outlook_score);

  return (
    <section className="panel p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-heading font-semibold">Latest call</h2>
        <p className="text-[11px] text-muted-foreground">
          Call of {formatDate(call.call_date)} · <span title={source.title}>{source.label}</span> ·
          Not in the score yet; the next screener run reads it
        </p>
      </div>

      <div className="mt-4 grid gap-x-8 gap-y-4 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0 space-y-1.5 text-sm">
          {highlights.length ? (
            highlights.map((item, index) => <Highlight key={index} item={item} />)
          ) : (
            <p className="text-xs text-muted-foreground">
              {call.outlook_score === null
                ? "Not read for its outlook yet."
                : "Nothing the call stated moved its outlook."}
            </p>
          )}
        </div>
        <dl className="sm:text-right">
          <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Outlook score</dt>
          <dd className={`tabular mt-0.5 text-sm font-semibold ${tone ? TONES[tone] : ""}`}>
            {formatScore(call.outlook_score)}
          </dd>
          <dd className="mt-0.5 text-[11px] text-muted-foreground">50 is a call that said nothing either way</dd>
        </dl>
      </div>
    </section>
  );
}
