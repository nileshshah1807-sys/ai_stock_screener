"use client";

import { useMarket } from "@/components/market-provider";
import { formatMoney, formatMoneyCompact } from "@/lib/format";

/**
 * A money amount in the current market's currency and magnitude words.
 *
 * For server components that cannot read the market context themselves --
 * chiefly the grid, whose cells are a module-level record of renderers with no
 * market in scope. Server components that do have the market, like the stock
 * page, call formatMoney directly instead of paying for a client boundary.
 */
export function Money({
  value,
  digits,
  compact = false,
  list = false,
}: {
  value: number | null | undefined;
  /** Explicit decimals. Overrides `list`. */
  digits?: number;
  /** Scale to Cr/L on NSE, B/M/K on US. */
  compact?: boolean;
  /** A price in a dense list: the market's list precision (see Market). */
  list?: boolean;
}) {
  const market = useMarket();
  if (compact) return formatMoneyCompact(value, market);
  return formatMoney(value, market, digits ?? (list ? market.listPriceDigits : 2));
}
