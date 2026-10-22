import { ChevronDown } from "lucide-react";

import { FieldItem } from "@/components/stock/field-item";
import { PanelHeader } from "@/components/stock/panel-header";
import { cn } from "@/lib/utils";
import { MISSING } from "@/lib/format";

export type Field = {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "muted" | "positive" | "negative" | "caution";
};

const TONES: Record<NonNullable<Field["tone"]>, string> = {
  default: "text-foreground",
  muted: "text-muted-foreground",
  positive: "text-positive",
  negative: "text-negative",
  caution: "text-caution",
};

/**
 * Label/value pairs in a definition list.
 *
 * <dl> rather than a table: these are attributes of one entity, not a
 * cross-sectional comparison, and screen readers announce the pairing.
 *
 * `visible` keeps the first N fields in view and puts the rest behind a
 * native disclosure, so a panel leads with the figures a reader scans for and
 * the full set stays one tap away. Order `fields` headline-first to use it.
 */
export function FieldList({
  fields,
  columns = 2,
  visible,
}: {
  fields: Field[];
  /** 4 is for a full-width panel; anything narrower will crowd at that count. */
  columns?: 1 | 2 | 3 | 4;
  visible?: number;
}) {
  const grid = cn(
    "grid gap-x-6 gap-y-2.5",
    columns === 1 && "grid-cols-1",
    columns === 2 && "grid-cols-1 sm:grid-cols-2",
    columns === 3 && "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
    // One column on a phone: two columns of label, value and an open caution
    // hint come to ~150px each at 390px, too narrow to read.
    columns === 4 && "grid-cols-1 min-[480px]:grid-cols-2 sm:grid-cols-3 lg:grid-cols-4",
  );
  const items = (list: Field[]) =>
    list.map((field) => (
      <FieldItem
        key={field.label}
        label={field.label}
        value={field.value ?? MISSING}
        hint={field.hint}
        hintOpen={field.tone === "caution" || field.tone === "negative"}
        toneClass={TONES[field.tone ?? "default"]}
      />
    ));

  const cut = visible !== undefined && visible < fields.length ? visible : fields.length;
  const rest = fields.slice(cut);

  return (
    <>
      <dl className={grid}>{items(fields.slice(0, cut))}</dl>
      {rest.length ? (
        <details className="group mt-3">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md py-1 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            <ChevronDown
              className="size-3.5 transition-transform group-open:rotate-180"
              aria-hidden
            />
            <span className="group-open:hidden">Show {rest.length} more</span>
            <span className="hidden group-open:inline">Show fewer</span>
          </summary>
          <dl className={cn(grid, "mt-2.5")}>{items(rest)}</dl>
        </details>
      ) : null}
    </>
  );
}

/**
 * A titled content surface.
 *
 * Takes the Figma card treatment (node 1:949): 24px radius, hairline border,
 * a soft lift, and noticeably more internal padding than the old 16px. The
 * mock's own heading is 24px, which is right when a page holds three cards and
 * wrong when it holds ten -- the detail page runs ten, so the heading lands at
 * 18px, a real step up from the previous 14px without every panel shouting.
 */
export function Panel({
  title,
  description,
  info,
  tag,
  children,
  className,
}: {
  title: string;
  /** Always-visible text under the title. Prefer `info` on dense pages. */
  description?: string;
  /** Explanation behind an info toggle in the title row. */
  info?: React.ReactNode;
  /** A short label beside the title that must stay visible, e.g. "Not scored". */
  tag?: string;
  children: React.ReactNode;
  className?: string;
}) {
  if (info !== undefined || tag !== undefined) {
    return (
      <section className={cn("panel animate-rise p-5 sm:p-6", className)}>
        <PanelHeader title={title} info={info} tag={tag} />
        {children}
      </section>
    );
  }
  return (
    <section className={cn("panel animate-rise p-5 sm:p-6", className)}>
      <h2 className="text-lead font-semibold tracking-[-0.011em]">{title}</h2>
      {description ? (
        <p className="mt-1 mb-4 text-xs leading-relaxed text-muted-foreground">
          {description}
        </p>
      ) : (
        <div className="mb-4" />
      )}
      {children}
    </section>
  );
}
