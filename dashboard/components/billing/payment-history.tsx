"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ExternalLink, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { priceLabel } from "@/lib/billing.mjs";
import { formatDate } from "@/lib/format";
import { PAYMENT_STATUS_LABEL } from "@/lib/payments.mjs";
import { cn } from "@/lib/utils";

export type PaymentRow = {
  id: string;
  date: string;
  paise: number;
  currency: string;
  method: string;
  status: "paid" | "refunded" | "failed" | "pending";
  receiptUrl: string | null;
};

export type PaymentsState = { status: "loading" } | { status: "error" } | { status: "ready"; rows: PaymentRow[] };

const amountOf = (row: PaymentRow) => (row.currency === "INR" ? priceLabel(row.paise) : `${row.currency} ${(row.paise / 100).toFixed(2)}`);

/** Reads the person's own payments from the server (which holds the Razorpay keys). */
export function PaymentHistory() {
  const [state, setState] = useState<PaymentsState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const response = await fetch("/api/billing/payments", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      const body = (await response.json()) as { payments: PaymentRow[] };
      setState({ status: "ready", rows: body.payments });
    } catch {
      setState({ status: "error" });
    }
  }, []);

  useEffect(() => {
    // The fetch is the effect: state moves only when it answers.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return <PaymentList state={state} onRetry={load} />;
}

/** The list in each of its states; the fetching above is kept out so every state can be drawn from fixtures. */
export function PaymentList({ state, onRetry }: { state: PaymentsState; onRetry?: () => void }) {
  const list = useRef<HTMLUListElement>(null);
  const ready = state.status === "ready";

  // Rows settle in once they are known; reduced motion runs nothing.
  useEffect(() => {
    if (!ready || !list.current) return;
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      gsap.from(list.current?.children ?? [], { opacity: 0, y: 8, duration: 0.4, ease: "expo.out", stagger: 0.05, clearProps: "transform,opacity" });
    });
    return () => mm.revert();
  }, [ready]);

  if (state.status === "loading") {
    return (
      <div className="mt-4 divide-y" role="status" aria-label="Loading payments">
        {[0, 1].map((index) => (
          <div key={index} className="flex items-center justify-between gap-4 py-3.5">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-4 w-16" />
          </div>
        ))}
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <p role="alert" className="flex items-start gap-2 text-destructive">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          Your payments could not be loaded.
        </p>
        {onRetry ? (
          <Button type="button" variant="outline" className="h-9" onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </div>
    );
  }

  if (state.rows.length === 0) {
    return <p className="mt-3 text-sm text-muted-foreground">No payments yet. A charge appears here, with its receipt, once it is made.</p>;
  }

  return (
    <div className="mt-4">
      <div aria-hidden className="hidden grid-cols-[6.5rem_5rem_1fr_6rem_6rem] gap-x-4 border-b pb-2 text-xs text-muted-foreground sm:grid">
        <span>Date</span>
        <span className="text-right">Amount</span>
        <span>Method</span>
        <span>Status</span>
        <span className="text-right">Receipt</span>
      </div>
      <ul ref={list} className="divide-y">
        {state.rows.map((row) => (
          <li
            key={row.id}
            className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 py-3.5 text-sm sm:grid-cols-[6.5rem_5rem_1fr_6rem_6rem]"
          >
            <span className="font-medium tabular-nums sm:font-normal">{formatDate(row.date)}</span>
            <span className="text-right font-medium tabular-nums sm:order-2">{amountOf(row)}</span>
            <span className="text-muted-foreground sm:order-3">{row.method}</span>
            <span className={cn("flex items-center justify-end gap-1.5 sm:order-4 sm:justify-start", row.status === "failed" && "text-destructive")}>
              <span
                aria-hidden
                className={cn("size-1.5 rounded-full", row.status === "paid" ? "bg-brand" : row.status === "failed" ? "bg-destructive" : "bg-muted-foreground/50")}
              />
              {PAYMENT_STATUS_LABEL[row.status]}
            </span>
            <span className="col-span-2 sm:order-5 sm:col-span-1 sm:text-right">
              {row.receiptUrl ? (
                <a
                  href={row.receiptUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Receipt for ${formatDate(row.date)} (opens in a new tab)`}
                  className="inline-flex items-center gap-1 rounded text-brand underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Receipt
                  <ExternalLink className="size-3.5" aria-hidden />
                </a>
              ) : (
                <span className="text-muted-foreground">No receipt</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
