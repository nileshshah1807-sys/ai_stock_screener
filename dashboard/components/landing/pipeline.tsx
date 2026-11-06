import { ArrowRight, Bell, Cog, FileText, Table2 } from "lucide-react";

const NODES = [
  { icon: FileText, name: "Sources", lines: ["Exchange filings", "SEC EDGAR statements", "Prices", "Call recordings"] },
  { icon: Cog, name: "Nightly run", lines: ["Every stock measured", "against its own market"] },
  { icon: Table2, name: "Ranked grid", lines: ["Filter, sort,", "open a stock"] },
  { icon: Bell, name: "Bell", lines: ["Tells you when a", "company you follow reports"] },
];

/** Where the grid comes from, as four boxes and the arrows between them. */
export function Pipeline() {
  return (
    <ol data-reveal className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] md:items-stretch">
      {NODES.flatMap(({ icon: Icon, name, lines }, i) => [
        <li key={name} className="panel p-4">
          <Icon className="size-5 text-brand" aria-hidden />
          <h3 className="mt-3 text-lead font-semibold">{name}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{lines.join(" ")}</p>
        </li>,
        i < NODES.length - 1 ? (
          <li key={`${name}-arrow`} aria-hidden className="flex justify-center self-center text-muted-foreground max-md:rotate-90">
            <ArrowRight className="size-5" />
          </li>
        ) : null,
      ])}
    </ol>
  );
}
