import { formatMoneyCompact } from "@/lib/format";
import { periodLabel } from "@/lib/financials.mjs";
import type { Market } from "@/lib/markets";
import type { HalfYear } from "@/lib/results";

const LINES = [
  ["revenue", "Revenue"],
  ["operating_profit", "Operating profit"],
  ["pbt", "Profit before tax"],
  ["net_profit", "Net profit"],
] as const;

/**
 * Six-month statements, as filed. An SME files a half year, which cannot sit
 * in the quarterly table: it would read as one quarter, and a growth rate
 * against a three-month neighbour would be wrong. So it is shown as what it is
 * and compared with nothing.
 */
export function HalfYearResults({ halfYears, market }: { halfYears: HalfYear[]; market: Market }) {
  if (!halfYears.length) return null;
  return (
    <section className="space-y-2" aria-labelledby="half-year-heading">
      <h3 id="half-year-heading" className="text-sm font-semibold">
        Half-year results
      </h3>
      <p className="text-xs text-muted-foreground">
        Filed as statements longer than a quarter, so there is no quarter or year-on-year change to show.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th scope="col" className="px-3 py-2 font-medium">Period ended</th>
              {LINES.map(([key, label]) => (
                <th key={key} scope="col" className="px-3 py-2 text-right font-medium">{label}</th>
              ))}
              <th scope="col" className="px-3 py-2 text-right font-medium">EPS</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {halfYears.map((half) => (
              <tr key={half.period_end}>
                <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-medium">
                  {periodLabel(half.period_end)}
                  <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                    {half.months} months · {half.is_consolidated ? "Consolidated" : "Standalone"}
                  </span>
                </th>
                {LINES.map(([key]) => (
                  <td key={key} className="tabular px-3 py-2 text-right">{formatMoneyCompact(half.lines[key], market)}</td>
                ))}
                <td className="tabular px-3 py-2 text-right">{half.lines.eps ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
