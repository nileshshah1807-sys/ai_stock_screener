import { listing } from "@/lib/listing.mjs";

/** A stock's ticker as a reader knows it, tagged with BSE when it trades only there. */
export function SymbolText({ symbol }: { symbol: string }) {
  const { ticker, exchange } = listing(symbol);
  if (!exchange) return <>{ticker}</>;
  return (
    <>
      {ticker}
      <span className="ml-1.5 rounded border border-border px-1 align-middle font-sans text-[0.625rem] font-medium tracking-normal text-muted-foreground">
        {exchange}
      </span>
    </>
  );
}
