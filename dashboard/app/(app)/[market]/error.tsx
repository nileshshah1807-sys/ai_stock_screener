"use client";

import { useEffect } from "react";
import Link from "next/link";

import { useMarketPath } from "@/components/market-provider";
import { Button, buttonVariants } from "@/components/ui/button";

/**
 * Any page in a market that fails to render and has no boundary of its own
 * (the Market tab keeps its own). A retry renders the segment again; Home is
 * the way on when it fails twice.
 */
export default function MarketPageError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  const marketPath = useMarketPath();
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="px-4 py-5 sm:px-6">
      <div className="panel mx-auto mt-6 max-w-lg px-5 py-12 text-center">
        <p className="text-sm text-muted-foreground">Something went wrong loading this page.</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <Button variant="outline" size="sm" onClick={retry}>
            Try again
          </Button>
          <Link href={marketPath()} className={buttonVariants({ variant: "ghost", size: "sm" })}>
            Home
          </Link>
        </div>
      </div>
    </div>
  );
}
