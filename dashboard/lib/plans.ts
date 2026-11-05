import { createClient } from "@/lib/supabase/server";

export type Plan = {
  id: string;
  name: string;
  amount_paise: number;
  period: "monthly" | "yearly";
};

export type Subscription = {
  plan_id: string | null;
  status: "trialing" | "active" | "past_due" | "cancelled" | "expired";
  trial_ends_at: string | null;
  current_period_end: string | null;
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
    .select("id, name, amount_paise, period")
    .eq("active", true)
    .order("amount_paise", { ascending: true });
  if (error) {
    console.error("Could not read plans", error.message);
    return null;
  }
  return (data ?? []) as Plan[];
}

/** The signed-in person's own subscription row (RLS shows no other). */
export async function getSubscription(userId: string): Promise<Subscription | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("subscriptions")
    .select("plan_id, status, trial_ends_at, current_period_end")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) {
    console.error("Could not read subscription", error.message);
    return null;
  }
  return (data as Subscription | null) ?? null;
}
