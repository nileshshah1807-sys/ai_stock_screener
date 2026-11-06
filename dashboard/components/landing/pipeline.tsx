import { ArrowRight, Bell, Cog, FileText, Table2 } from "lucide-react";

const NODES = [
  { icon: FileText, name: "Sources", text: "Filings, prices, call recordings (India only)" },
  { icon: Cog, name: "Nightly run", text: "Every stock measured against its own market" },
  { icon: Table2, name: "Ranked grid", text: "Filter, sort, open a stock" },
  { icon: Bell, name: "Bell", text: "Tells you when a company you follow reports" },
];

/** Where the grid comes from, as four boxes and the arrows between them. */
export function Pipeline() {
  return (
    <ol data-reveal className="grid grid-cols-2 gap-2 md:gap-3 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] md:items-stretch">
      {NODES.flatMap(({ icon: Icon, name, text }, i) => [
        <li key={name} className="panel p-3 md:p-4">
          <h3 className="flex items-center gap-2 text-lead font-semibold"><Icon className="size-5 shrink-0 text-brand" aria-hidden />{name}</h3>
          <p className="mt-1.5 text-sm text-muted-foreground">{text}</p>
        </li>,
        i < NODES.length - 1 ? (
          <li key={`${name}-arrow`} aria-hidden className="hidden justify-center self-center text-muted-foreground md:flex">
            <ArrowRight className="size-5" />
          </li>
        ) : null,
      ])}
    </ol>
  );
}
