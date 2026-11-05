import { createClient } from "@/lib/supabase/server";

export type Plan = {
  id: string;
  name: string;
  amount_paise: number;
  period: "monthly" | "yearly";
  /** An introductory price for the first period, while the offer is open. */
  offer?: { name: string; amount_paise: number; ends_at: string | null } | null;
  /** The introductory price as stored, open or not: what someone who took it pays. */
  offer_amount_paise?: number | null;
};

export type Subscription = {
  plan_id: string | null;
  status: "trialing" | "active" | "past_due" | "cancelled" | "expired";
  trial_ends_at: string | null;
  current_period_end: string | null;
  /** Whether the introductory price was taken at checkout; null before it was recorded. */
  offer_applied?: boolean | null;
};

/**
 * The plans on sale, exactly as the plans table holds them. The price is data:
 * nothing here or in a page states an amount. Readable signed out, because the
 * pricing page is public. null when the read fails, so the page can say so
 * rather than show an empty list as if nothing were for sale.
 */
export async function getPlans(): Promise<Plan[] | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("plans")
    .select("id, name, amount_paise, period, offer_name, offer_amount_paise, offer_ends_at")
    .eq("active", true);
  if (error) {
    console.error("Could not read plans", error.message);
    return null;
  }
  const plans = await Promise.all(
    (data ?? []).map(async (row): Promise<Plan> => {
      const plan: Plan = { id: row.id, name: row.name, amount_paise: row.amount_paise, period: row.period };
      if (row.offer_amount_paise == null) return plan;
      plan.offer_amount_paise = row.offer_amount_paise;
      // Whether the offer is still open (its date, and how many have taken it)
      // is the database's to say: it counts the subscribers.
      const { data: open } = await supabase.rpc("plan_offer_open", { p_plan: row.id });
      if (open === true) {
        plan.offer = { name: row.offer_name ?? "Offer", amount_paise: row.offer_amount_paise, ends_at: row.offer_ends_at };
      }
      return plan;
    }),
  );
  // Yearly first: it is the plan the page leads with.
  return plans.sort((a, b) => Number(b.period === "yearly") - Number(a.period === "yearly"));
}

/** The signed-in person's own subscription row (RLS shows no other). */
export async function getSubscription(userId: string): Promise<Subscription | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("subscriptions")
    .select("plan_id, status, trial_ends_at, current_period_end, offer_applied")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) {
    console.error("Could not read subscription", error.message);
    return null;
  }
  return (data as Subscription | null) ?? null;
}
