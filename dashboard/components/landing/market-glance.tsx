import { FLOW_INK } from "@/components/market/flow-format";
import { SAMPLE_IPO, SAMPLE_SECTORS, heatFill, sampleBreadth, sampleFlows } from "@/lib/landing.mjs";
import { squarify } from "@/lib/sectors.mjs";
import { cn } from "@/lib/utils";

const tiles = squarify(SAMPLE_SECTORS.map(([name, size, day]) => ({ name: String(name), size: Number(size), day: Number(day) })), 100, 100);
const breadth = sampleBreadth();
const flows = sampleFlows();
const flowMax = Math.max(...flows.flatMap((f) => [Math.abs(f.fii), Math.abs(f.dii)]));
const bookMax = Math.max(...SAMPLE_IPO.book.map(([, x]) => Number(x)));
const pct = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`;
const crore = (v: number) => `${v >= 0 ? "+" : "−"}₹${Math.abs(v).toLocaleString("en-IN")} Cr`;
const net = (key: "fii" | "dii") => flows.slice(-5).reduce((a, f) => a + f[key], 0);
const ink = (key: "fii" | "dii") => FLOW_INK[key === "fii" ? "FII" : "DII"];

/** A tile's heading, with "India" beside it where the data exists for NSE alone. */
function Head({ title, india }: { title: string; india?: boolean }) {
  return (
    <h3 className="flex items-center justify-between gap-3 text-sm font-semibold">
      {title}
      {india ? <span className="rounded bg-(--control) px-1.5 py-0.5 text-micro font-medium text-muted-foreground">India</span> : null}
    </h3>
  );
}

function Sectors() {
  return (
    <div className="panel flex flex-col p-4 lg:col-span-7 lg:row-span-2">
      <Head title="Sector heatmap" />
      <div
        role="img"
        aria-label={`Sector heatmap: ${SAMPLE_SECTORS.map(([n, , d]) => `${n} ${pct(Number(d))}`).join(", ")}`}
        className="relative mt-3 h-72 overflow-hidden lg:flex-1 rounded-md sm:h-80 lg:h-auto lg:min-h-96"
      >
        {tiles.map((t) => (
          <div
            key={t.name}
            style={{ left: `${t.x}%`, top: `${t.y}%`, width: `${t.w}%`, height: `${t.h}%`, background: heatFill(t.day) }}
            className="absolute flex flex-col items-center justify-center overflow-hidden border border-card p-1 text-center leading-tight"
          >
            {t.size >= 2 ? (
              <>
                <span className="max-w-full truncate text-xs font-medium">{t.name}</span>
                <span className="text-micro tabular-nums text-foreground/80">{pct(t.day)}</span>
              </>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function Breadth() {
  const W = 300;
  const H = 72;
  // Drawn to its own range, padded, so a 60-session line has a visible shape.
  const lo = Math.min(...breadth.above200) - 3;
  const hi = Math.max(...breadth.above200) + 3;
  const y = (v: number) => (H - ((v - lo) / (hi - lo)) * H).toFixed(1);
  const line = breadth.above200.map((v, i) => `${i ? "L" : "M"}${((i / (breadth.above200.length - 1)) * W).toFixed(1)} ${y(v)}`).join("");
  const last = Math.round(breadth.above200.at(-1) ?? 0);
  return (
    <div className="panel p-4 lg:col-span-5">
      <Head title="Market breadth" />
      <div role="img" aria-label={`${breadth.up}% of stocks up, ${breadth.down}% down`} className="mt-4 flex h-2.5 overflow-hidden rounded-full bg-(--control)">
        <span className="bg-positive" style={{ width: `${breadth.up}%` }} />
        <span className="ml-auto bg-negative" style={{ width: `${breadth.down}%` }} />
      </div>
      <p aria-hidden className="mt-1.5 flex justify-between text-xs tabular-nums">
        <span className="text-positive">{breadth.up}% up</span>
        <span className="text-negative">{breadth.down}% down</span>
      </p>
      <div className="mt-4 flex items-end justify-between gap-4">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${last}% of stocks above their 200-day average`} className="h-16 w-full">
          {lo < 50 && hi > 50 ? <line x1="0" x2={W} y1={y(50)} y2={y(50)} className="stroke-border" strokeDasharray="3 4" vectorEffect="non-scaling-stroke" /> : null}
          <path d={line} fill="none" stroke="var(--chart-line)" strokeWidth="1.75" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        <p aria-hidden className="shrink-0 text-right">
          <span className="block text-lead font-semibold tabular-nums">{last}%</span>
          <span className="block text-micro text-muted-foreground">above 200-day</span>
        </p>
      </div>
    </div>
  );
}

function Flows() {
  const H = 64;
  const slot = 100 / flows.length;
  return (
    <div className="panel p-4 lg:col-span-5">
      <Head title="FII / DII flows" india />
      <svg viewBox={`0 0 100 ${H}`} preserveAspectRatio="none" aria-hidden className="mt-4 h-20 w-full">
        <line x1="0" x2="100" y1={H / 2} y2={H / 2} className="stroke-border" vectorEffect="non-scaling-stroke" />
        {flows.map((f, i) =>
          (["fii", "dii"] as const).map((key, k) => {
            const h = (Math.abs(f[key]) / flowMax) * (H / 2 - 2);
            return <rect key={`${i}-${key}`} x={i * slot + slot * (0.14 + k * 0.38)} width={slot * 0.34} y={f[key] >= 0 ? H / 2 - h : H / 2} height={h} fill={ink(key)} />;
          }),
        )}
      </svg>
      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs tabular-nums">
        {(["fii", "dii"] as const).map((key) => (
          <div key={key} className="flex items-center gap-2">
            <span aria-hidden className="size-2 rounded-sm" style={{ background: ink(key) }} />
            <dt className="text-muted-foreground">{key === "fii" ? "FII / FPI" : "DII"} · 5D</dt>
            <dd className="font-semibold">{crore(net(key))}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Ipo() {
  return (
    <div className="panel grid gap-4 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_auto] sm:items-center sm:gap-8 lg:col-span-12">
      <div>
        <Head title="IPOs" india />
        <p className="mt-3 font-semibold">{SAMPLE_IPO.name}</p>
        <p className="text-xs tabular-nums text-muted-foreground">{SAMPLE_IPO.board} · Closes {SAMPLE_IPO.closes} · {SAMPLE_IPO.band}</p>
      </div>
      <dl className="grid gap-1.5 text-xs tabular-nums">
        {SAMPLE_IPO.book.map(([what, times]) => (
          <div key={what} className="grid grid-cols-[3.5rem_1fr_3rem] items-center gap-3">
            <dt className={cn("text-muted-foreground", what === "Total" && "font-semibold text-foreground")}>{what}</dt>
            <span aria-hidden className="h-2 overflow-hidden rounded-full bg-(--control)">
              <span className={cn("block h-full rounded-full", what === "Total" ? "bg-brand" : "bg-brand/45")} style={{ width: `${(Number(times) / bookMax) * 100}%` }} />
            </span>
            <dd className={cn("text-right", what === "Total" && "font-semibold")}>{Number(times).toFixed(1)}×</dd>
          </div>
        ))}
      </dl>
      <p className="text-sm sm:text-right">
        <span className="block text-micro text-muted-foreground">GMP (unofficial)</span>
        <span className="font-semibold tabular-nums">{SAMPLE_IPO.gmp}</span>
      </p>
    </div>
  );
}

/** The Market and IPO pages as miniatures: invented sectors, breadth, flows and one issue; the caller captions it. */
export function MarketGlance() {
  return (
    <div data-reveal className="grid gap-3 lg:grid-cols-12">
      <Sectors />
      <Breadth />
      <Flows />
      <Ipo />
    </div>
  );
}
