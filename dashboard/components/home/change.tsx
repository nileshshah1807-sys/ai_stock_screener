import { formatChange } from "@/lib/results.mjs";
import { MISSING } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A signed change, coloured by direction; the sign carries it too, so colour is never alone. */
export function Change({ value, unit }: { value: number | null | undefined; unit: string }) {
  const text = value == null ? null : formatChange(value, unit);
  return (
    <span className={cn("tabular", value == null ? "text-muted-foreground" : value >= 0 ? "text-positive" : "text-negative")}>
      {text ?? MISSING}
    </span>
  );
}
