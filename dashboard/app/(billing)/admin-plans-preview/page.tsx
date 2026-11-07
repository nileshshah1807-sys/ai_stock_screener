"use client";

import { notFound } from "next/navigation";

import { PlansAdmin } from "@/components/admin/plans/plans-admin";

/** Development only: /admin/plans from made-up rows and stub actions, for looking at it without a database. */
const ok = async () => ({ ok: true as const, message: "Saved (preview: nothing was changed)." });
const DATA = {
  trialDays: 7,
  mode: "test" as const,
  plans: [
    { id: "pro", name: "Cupel", period: "yearly" as const, amount_paise: 99900, active: true, razorpay_plan_id: "plan_PreviewYearly1", razorpay_offer_id: "offer_PreviewOffer01", offer_name: "Early bird", offer_amount_paise: 69900, offer_ends_at: "2026-12-31T18:29:59Z", offer_limit: 500 },
    { id: "pro-monthly", name: "Cupel", period: "monthly" as const, amount_paise: 12900, active: true, razorpay_plan_id: "plan_PreviewMonthly", razorpay_offer_id: null, offer_name: null, offer_amount_paise: null, offer_ends_at: null, offer_limit: null },
  ],
  revenue: [
    { planId: "pro", subscribers: 38, monthlyPaise: 221_500 },
    { planId: "pro-monthly", subscribers: 12, monthlyPaise: 154_800 },
  ],
};

export default function AdminPlansPreview() {
  if (process.env.NODE_ENV === "production") notFound();
  return <PlansAdmin data={DATA} actions={{ price: ok, offer: ok, open: ok, trial: ok }} />;
}
