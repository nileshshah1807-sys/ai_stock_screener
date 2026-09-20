import Link from "next/link";
import { TriangleAlert } from "lucide-react";

import { formatDate } from "@/lib/format";
import { marketPath, type Market } from "@/lib/markets";
import type { StageBreak } from "@/lib/types";

/**
 * Watched stocks that broke into Stage 3 or 4 after they were added.
 *
 * This is the one stage rule that earned a place (P5): selling a holding the
 * session after it breaks into Stage 3 or 4 raised Sharpe and made the worst
 * drawdown shallower in both halves of 2018-2026, while every attempt to use
 * stage in the *ranking* lost money (P3, P4). So the alert is phrased as what
 * the tested rule would do, with its cost stated beside its benefit -- it is
 * insurance, and it cost a few points in steady bull years.
 *
 * Renders nothing when nothing broke down. A failed read also renders nothing
 * rather than an all-clear, because the query logs and returns an empty list.
 */
export function StageBreakAlert({
  breaks,
  market,
}: {
  breaks: StageBreak[];
  market: Market;
}) {
  if (!breaks.length) return null;
  const count = breaks.length;

  return (
    <section
      className="panel animate-rise border-caution/40 px-4 py-3"
      aria-label="Stage breakdown alerts"
    >
      <div className="flex items-start gap-2">
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-caution" aria-hidden />
        <div className="min-w-0 space-y-2">
          <p className="text-sm font-medium">
            {count === 1
              ? "1 stock on this list broke into Stage 3 or 4 after you added it"
              : `${count} stocks on this list broke into Stage 3 or 4 after you added them`}
          </p>
          <ul className="space-y-1 text-sm">
            {breaks.map((item) => (
              <li key={item.symbol} className="flex flex-wrap items-baseline gap-x-2">
                <Link
                  href={marketPath(
                    market.slug,
                    `/stocks/${encodeURIComponent(item.symbol)}`,
                  )}
                  prefetch={false}
                  className="font-mono text-xs font-semibold underline-offset-2 hover:underline"
                >
                  {item.symbol}
                </Link>
                <span className="text-xs text-caution">{item.stage}</span>
                <span className="text-xs text-muted-foreground">
                  since {formatDate(item.breakdown_date)}
                  {item.breakdown_age_days !== null
                    ? ` (${item.breakdown_age_days} days)`
                    : ""}
                  {item.breakdown_from ? `, from ${item.breakdown_from}` : ""}
                  {" · "}added {formatDate(item.added_at)}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-[11px] leading-snug text-muted-foreground">
            The tested exit rule would sell these at the next close and hold
            cash until the next rebalance. From 2018 to 2026 that cut the worst
            drawdown of the model&apos;s top 20 from −43% to −30% and lifted
            its Sharpe ratio, but cost 5-7 points in steady bull years (2022,
            2024). A rule for holdings, not a rating: the score and rank are
            unchanged.
          </p>
        </div>
      </div>
    </section>
  );
}
