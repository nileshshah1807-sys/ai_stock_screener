import { Activity, ArrowLeftRight, Bell, CalendarRange, ChartCandlestick, ChartPie, FileSpreadsheet, Grid3x3, MessagesSquare, Radio, Table2, type LucideIcon } from "lucide-react";

import { PLAN_INCLUDES } from "@/lib/billing.mjs";

const ICON: Record<string, LucideIcon> = {
  screener: Table2,
  results: FileSpreadsheet,
  calls: MessagesSquare,
  charts: ChartCandlestick,
  sectors: Grid3x3,
  breadth: Activity,
  live: Radio,
  watch: Bell,
  flows: ArrowLeftRight,
  ipos: CalendarRange,
  holding: ChartPie,
};

const GROUPS = [
  { title: "India and US", items: PLAN_INCLUDES.filter((f) => f.markets.length > 1) },
  { title: "India", items: PLAN_INCLUDES.filter((f) => f.markets.length === 1) },
];

/** What every plan includes, grouped by the markets it covers. */
export function PlanIncludes() {
  return (
    <div className="mt-8 grid gap-6 border-t pt-6 sm:grid-cols-[2fr_1fr] sm:gap-10">
      {GROUPS.map(({ title, items }) => (
        <section key={title}>
          <h3 className="text-sm font-semibold">{title}</h3>
          <ul className={items.length > 4 ? "mt-3 grid gap-x-6 gap-y-2.5 text-sm sm:grid-cols-2" : "mt-3 grid gap-y-2.5 text-sm"}>
            {items.map(({ key, label }) => {
              const Icon = ICON[key];
              return (
                <li key={key} className="flex items-center gap-2.5">
                  {Icon ? <Icon aria-hidden className="size-4 shrink-0 text-brand" /> : null}
                  {label}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
