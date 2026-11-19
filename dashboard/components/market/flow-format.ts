import { formatMoneyCompact, MISSING } from "@/lib/format";
import type { Market } from "@/lib/markets";

/** One category's figures for a session, rupees crore; null where NSE did not report it. */
export type Flow = { buy: number | null; sell: number | null; net: number | null };
export type FlowSession = { session: string; FII: Flow | null; DII: Flow | null };
export type FlowCategory = "FII" | "DII";

export const FLOW_LABEL: Record<FlowCategory, string> = { FII: "FII / FPI", DII: "DII" };
export const FLOW_INK: Record<FlowCategory, string> = { FII: "var(--series-1)", DII: "var(--series-2)" };

/**
 * How a flow figure is written, shared by the server table and the client
 * chart (a plain module, so both can call it). Crore in, so a figure reads
 * "₹1,234 Cr" like every other amount in the app.
 */
export function flowFormat(market: Market) {
  const money = (crore: number | null | undefined) =>
    crore === null || crore === undefined ? MISSING : formatMoneyCompact(crore * 1e7, market);
  const signed = (crore: number | null | undefined) => (crore && crore > 0 ? `+${money(crore)}` : money(crore));
  const tone = (crore: number | null | undefined) =>
    crore === null || crore === undefined ? "text-muted-foreground" : crore >= 0 ? "text-positive" : "text-negative";
  return { money, signed, tone };
}
