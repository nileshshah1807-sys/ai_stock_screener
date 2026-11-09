import { cn } from "@/lib/utils";

/**
 * The frame every Home card shares: a title, an optional note beside it (an
 * unread count, a freshness warning) and the body. Server component; the body
 * decides whether a card shows at all, so a card with nothing to say renders
 * nothing and never an empty frame.
 */
export function HomeCard({
  title,
  note,
  className,
  children,
}: {
  title: string;
  note?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("panel flex flex-col p-4 sm:p-5", className)}>
      <header className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-[-0.01em]">{title}</h2>
        {note ? <span className="tabular text-xs text-muted-foreground">{note}</span> : null}
      </header>
      {children}
    </section>
  );
}

/** The shape a card holds while it streams in, so the page does not jump. */
export function HomeCardSkeleton({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div aria-hidden className={cn("panel min-h-56 p-4 sm:p-5", className)}>
      <div className="mb-3 h-4 w-32 animate-pulse rounded bg-muted" />
      <div className="space-y-2.5">
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="h-5 animate-pulse rounded bg-muted/70" />
        ))}
      </div>
    </div>
  );
}
