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
 */
export function FieldList({
  fields,
  columns = 2,
}: {
  fields: Field[];
  /** 4 is for a full-width panel; anything narrower will crowd at that count. */
  columns?: 1 | 2 | 3 | 4;
}) {
  return (
    <dl
      className={cn(
        "grid gap-x-6 gap-y-2.5",
        columns === 1 && "grid-cols-1",
        columns === 2 && "grid-cols-1 sm:grid-cols-2",
        columns === 3 && "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
        columns === 4 && "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4",
      )}
    >
      {fields.map((field) => (
        <div key={field.label} className="min-w-0">
          <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {field.label}
          </dt>
          <dd
            className={cn(
              "tabular mt-0.5 break-words font-mono text-sm",
              TONES[field.tone ?? "default"],
            )}
          >
            {field.value ?? MISSING}
          </dd>
          {field.hint ? (
            <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
              {field.hint}
            </p>
          ) : null}
        </div>
      ))}
    </dl>
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
  children,
  className,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
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
