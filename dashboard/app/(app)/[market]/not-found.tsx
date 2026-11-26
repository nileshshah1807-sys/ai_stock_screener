"use client";

import Link from "next/link";
import { Search } from "lucide-react";

import { openSearch } from "@/components/global-search";
import { useMarketPath } from "@/components/market-provider";
import { Button, buttonVariants } from "@/components/ui/button";

/**
 * A page inside a market that does not exist: a stock no run holds, a mistyped
 * symbol, an old link. Inside the market layout, so the header is there and the
 * way on is the search it already has.
 */
export default function MarketNotFound() {
  const marketPath = useMarketPath();
  return (
    <div className="px-4 py-5 sm:px-6">
      <div className="panel mx-auto mt-6 max-w-lg px-5 py-12 text-center">
        <h1 className="text-title font-semibold">Page not found</h1>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button className="gap-1.5" onClick={openSearch}>
            <Search className="size-3.5" aria-hidden />
            Search stocks
          </Button>
          <Link href={marketPath()} className={buttonVariants({ variant: "outline" })}>
            Home
          </Link>
        </div>
      </div>
    </div>
  );
}
