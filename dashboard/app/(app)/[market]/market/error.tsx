"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/**
 * The Market page when it fails to render. The reads themselves never throw
 * -- a failed one is reported in place (see getMarketBreadth) -- so this is a
 * fault in drawing what came back, and a retry renders the segment again.
 */
export default function MarketError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="px-4 py-5 sm:px-6">
      <h1 className="text-title font-semibold">Market</h1>
      <div className="panel mt-6 px-5 py-12 text-center">
        <p className="text-sm text-muted-foreground">Something went wrong loading this page.</p>
        <Button variant="outline" size="sm" className="mt-4" onClick={retry}>
          Try again
        </Button>
      </div>
    </div>
  );
}
