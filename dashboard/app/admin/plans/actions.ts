"use server";

import { revalidatePath } from "next/cache";

import { changePrice, relinkPlan, saveOffer, setPlanOpen, setTrialDays, type OfferInput, type Result } from "@/lib/admin-plans-server";

const done = (r: Result) => {
  if (r.ok) revalidatePath("/admin/plans");
  return r;
};

export async function changePriceAction(planId: string, rupees: string) {
  return done(await changePrice(planId, rupees));
}
export async function relinkPlanAction(planId: string) {
  return done(await relinkPlan(planId));
}
export async function saveOfferAction(planId: string, input: OfferInput) {
  return done(await saveOffer(planId, input));
}
export async function setPlanOpenAction(planId: string, open: boolean) {
  return done(await setPlanOpen(planId, open));
}
export async function setTrialDaysAction(days: string) {
  return done(await setTrialDays(days));
}
