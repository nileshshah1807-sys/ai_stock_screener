import { listing } from "@/lib/listing.mjs";

const TAG =
  "ml-1.5 rounded border border-border px-1 align-middle font-sans text-[0.625rem] font-medium tracking-normal text-muted-foreground";

/** A stock's ticker as a reader knows it, tagged BSE when it trades only there and SME when it is on an SME list. */
export function SymbolText({ symbol, sme = false }: { symbol: string; sme?: boolean | null }) {
  const { ticker, exchange, sme: isSme } = listing(symbol, sme === true);
  return (
    <>
      {ticker}
      {exchange ? <span className={TAG}>{exchange}</span> : null}
      {isSme ? <span className={TAG}>SME</span> : null}
    </>
  );
}
