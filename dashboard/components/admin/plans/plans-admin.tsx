"use client";

import { useState, useTransition } from "react";

import { changePriceAction, saveOfferAction, setPlanOpenAction, setTrialDaysAction } from "@/app/admin/plans/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { validatePriceChange, validateTrialDays } from "@/lib/admin-plans.mjs";
import { priceLabel } from "@/lib/billing.mjs";
import type { AdminPlan, PlansAdminData, Result } from "@/lib/admin-plans";

/** Admin-only plan and price management. Every control calls a server action that re-checks the admin. */
export function PlansAdmin({ data, actions }: { data: PlansAdminData; actions?: Partial<Actions> }) {
  const run = { ...REAL, ...actions };
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-title font-semibold">Plans</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Prices, the early-bird offer, and which plans are on sale. Razorpay plans cannot be edited, so a price change makes a new one; people who already subscribed keep theirs. Refunds are made in Razorpay.
        </p>
      </div>
      {data.plans.map((plan) => (
        <PlanCard key={plan.id} plan={plan} stats={data.revenue.find((r) => r.planId === plan.id)} run={run} />
      ))}
      <TrialCard days={data.trialDays} run={run} />
    </div>
  );
}

type Actions = {
  price: (id: string, rupees: string) => Promise<Result>;
  offer: (id: string, input: { name: string; rupees: string; offerId: string; endsAt: string; limit: string }) => Promise<Result>;
  open: (id: string, open: boolean) => Promise<Result>;
  trial: (days: string) => Promise<Result>;
};
const REAL: Actions = { price: changePriceAction, offer: saveOfferAction, open: setPlanOpenAction, trial: setTrialDaysAction };

function useAction() {
  const [pending, start] = useTransition();
  const [result, setResult] = useState<Result | null>(null);
  const go = (fn: () => Promise<Result>) => start(async () => setResult(await fn().catch(() => ({ ok: false as const, error: "Something went wrong. Nothing was changed." }))));
  return { pending, result, go, clear: () => setResult(null) };
}

function Message({ result }: { result: Result | null }) {
  if (!result) return null;
  return (
    <p role={result.ok ? "status" : "alert"} className={result.ok ? "text-sm text-positive" : "text-sm text-destructive"}>
      {result.ok ? result.message : result.error}
    </p>
  );
}

const dateInput = (iso: string | null) => (iso ? iso.slice(0, 10) : "");

function PlanCard({ plan, stats, run }: { plan: AdminPlan; stats?: { subscribers: number; monthlyPaise: number }; run: Actions }) {
  const price = useAction();
  const offer = useAction();
  const open = useAction();
  const [rupees, setRupees] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [o, setO] = useState({
    name: plan.offer_name ?? "",
    rupees: plan.offer_amount_paise != null ? String(plan.offer_amount_paise / 100) : "",
    offerId: plan.razorpay_offer_id ?? "",
    endsAt: dateInput(plan.offer_ends_at),
    limit: plan.offer_limit != null ? String(plan.offer_limit) : "",
  });
  const check = rupees ? validatePriceChange(plan, rupees) : null;

  return (
    <section className="panel space-y-5 p-5" aria-labelledby={`plan-${plan.id}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`plan-${plan.id}`} className="text-heading font-semibold">
          {plan.period === "yearly" ? "Yearly" : "Monthly"} plan <span className="text-sm font-normal text-muted-foreground">({plan.id})</span>
        </h2>
        <span className={plan.active ? "text-sm text-positive" : "text-sm text-muted-foreground"}>{plan.active ? "On sale" : "Closed"}</span>
      </header>

      <dl className="grid grid-cols-3 gap-4 text-sm">
        <div><dt className="text-muted-foreground">Price</dt><dd className="tabular-nums">{priceLabel(plan.amount_paise)} / {plan.period === "yearly" ? "year" : "month"}</dd></div>
        <div><dt className="text-muted-foreground">Active subscribers</dt><dd className="tabular-nums">{stats?.subscribers ?? 0}</dd></div>
        <div><dt className="text-muted-foreground">Monthly revenue</dt><dd className="tabular-nums">{priceLabel(stats?.monthlyPaise ?? 0)}</dd></div>
      </dl>
      <p className="text-xs text-muted-foreground">Razorpay plan {plan.razorpay_plan_id ?? "not set"}. Revenue counts active subscribers at the price each took; a yearly price counts as a twelfth a month.</p>

      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (check?.ok) setConfirming(true);
        }}
      >
        <Label htmlFor={`price-${plan.id}`}>New price in rupees</Label>
        <div className="flex gap-2">
          <Input id={`price-${plan.id}`} inputMode="decimal" value={rupees} onChange={(e) => { setRupees(e.target.value); setConfirming(false); price.clear(); }} className="max-w-40" />
          <Button type="submit" variant="outline" disabled={!check?.ok}>Review change</Button>
        </div>
        {check && !check.ok ? <p className="text-sm text-muted-foreground">{check.error}</p> : null}
        {confirming && check?.ok ? (
          <div className="rounded-md border p-3 text-sm space-y-2" role="alertdialog" aria-label="Confirm price change">
            <p><strong>{priceLabel(check.oldPaise)} → {priceLabel(check.newPaise)}</strong> per {plan.period === "yearly" ? "year" : "month"}.</p>
            <p className="text-muted-foreground">Creates a new Razorpay plan. New subscribers pay this; existing ones keep their price. The early-bird offer on this plan is cleared and must be added again.</p>
            <div className="flex gap-2">
              <Button type="button" disabled={price.pending} onClick={() => price.go(() => run.price(plan.id, rupees))}>{price.pending ? "Changing…" : "Confirm change"}</Button>
              <Button type="button" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
            </div>
          </div>
        ) : null}
        <Message result={price.result} />
      </form>

      <form
        className="space-y-3 border-t pt-4"
        onSubmit={(e) => { e.preventDefault(); offer.go(() => run.offer(plan.id, o)); }}
      >
        <h3 className="text-sm font-semibold">Early-bird offer</h3>
        <p className="text-xs text-muted-foreground">Make the offer in the Razorpay dashboard and paste its id. Leave every field empty to turn the offer off.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id={`on-${plan.id}`} label="Name" value={o.name} onChange={(v) => setO({ ...o, name: v })} />
          <Field id={`or-${plan.id}`} label="Offer price (₹)" value={o.rupees} onChange={(v) => setO({ ...o, rupees: v })} inputMode="decimal" />
          <Field id={`oi-${plan.id}`} label="Razorpay offer id" value={o.offerId} onChange={(v) => setO({ ...o, offerId: v })} />
          <Field id={`oe-${plan.id}`} label="Ends on" type="date" value={o.endsAt} onChange={(v) => setO({ ...o, endsAt: v })} />
          <Field id={`ol-${plan.id}`} label="Subscriber limit" value={o.limit} onChange={(v) => setO({ ...o, limit: v })} inputMode="numeric" />
        </div>
        <Button type="submit" variant="outline" disabled={offer.pending}>{offer.pending ? "Saving…" : "Save offer"}</Button>
        <Message result={offer.result} />
      </form>

      <div className="space-y-2 border-t pt-4">
        <Button type="button" variant="outline" disabled={open.pending} onClick={() => open.go(() => run.open(plan.id, !plan.active))}>
          {plan.active ? "Close for sale" : "Open for sale"}
        </Button>
        <Message result={open.result} />
      </div>
    </section>
  );
}

function Field({ id, label, value, onChange, type, inputMode }: { id: string; label: string; value: string; onChange: (v: string) => void; type?: string; inputMode?: "decimal" | "numeric" }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type={type} inputMode={inputMode} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function TrialCard({ days, run }: { days: number; run: Actions }) {
  const act = useAction();
  const [value, setValue] = useState(String(days));
  const check = validateTrialDays(value);
  return (
    <section className="panel space-y-3 p-5" aria-labelledby="trial-length">
      <h2 id="trial-length" className="text-heading font-semibold">Free trial</h2>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (check.ok) act.go(() => run.trial(value)); }}>
        <Label htmlFor="trial-days">Days for new sign-ups</Label>
        <div className="flex gap-2">
          <Input id="trial-days" inputMode="numeric" value={value} onChange={(e) => { setValue(e.target.value); act.clear(); }} className="max-w-24" />
          <Button type="submit" variant="outline" disabled={!check.ok || act.pending}>Save</Button>
        </div>
        {!check.ok ? <p className="text-sm text-muted-foreground">{check.error}</p> : <p className="text-xs text-muted-foreground">Applies to new accounts only; trials already running keep their end date. The public pages say 7 days: update them if you change this.</p>}
        <Message result={act.result} />
      </form>
    </section>
  );
}
