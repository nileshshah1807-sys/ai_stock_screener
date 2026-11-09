import { barShare } from "@/lib/home.mjs";
import { cn } from "@/lib/utils";

/**
 * A bar sized against a card-wide scale (`barScale`), growing in from its
 * start. Decoration for a figure that is always printed beside it, so it is
 * hidden from assistive technology.
 */
export function Bar({ value, scale, tone, className }: { value: number; scale: number; tone: "positive" | "negative" | "neutral"; className?: string }) {
  return (
    <span aria-hidden className={cn("block h-1.5 overflow-hidden rounded-full bg-muted", className)}>
      <span
        className={cn(
          "block h-full origin-left animate-grow rounded-full",
          tone === "positive" ? "bg-positive" : tone === "negative" ? "bg-negative" : "bg-foreground/50",
        )}
        style={{ width: `${barShare(value, scale)}%` }}
      />
    </span>
  );
}

/** A bar either side of a centre line: rises go right, falls go left. */
export function DivBar({ value, scale, className }: { value: number | null | undefined; scale: number; className?: string }) {
  const share = value == null ? 0 : barShare(value, scale) / 2;
  const up = (value ?? 0) >= 0;
  return (
    <span aria-hidden className={cn("relative block h-1.5 rounded-full bg-muted", className)}>
      <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
      <span
        className={cn(
          "absolute inset-y-0 animate-grow rounded-full",
          up ? "left-1/2 origin-left bg-positive" : "right-1/2 origin-right bg-negative",
        )}
        style={{ width: `${share}%` }}
      />
    </span>
  );
}
