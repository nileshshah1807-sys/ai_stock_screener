"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Re-render the page from the server every few minutes while it is on
 * screen, so a result filed while the reader watches appears without a
 * reload. Results are stored every quarter of an hour; a refresh only runs
 * while the tab is visible, and once more when the reader comes back to it.
 */
export function AutoRefresh({ everySeconds = 300 }: { everySeconds?: number }) {
  const router = useRouter();

  useEffect(() => {
    let last = Date.now();
    const refresh = () => {
      last = Date.now();
      router.refresh();
    };
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, everySeconds * 1000);
    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - last >= everySeconds * 1000) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [router, everySeconds]);

  return null;
}
