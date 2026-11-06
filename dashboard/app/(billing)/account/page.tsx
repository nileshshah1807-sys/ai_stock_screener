import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PaymentHistory } from "@/components/billing/payment-history";
import { AccountView } from "@/components/billing/account-view";
import { getSession } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";
import { getPlans, getSubscription } from "@/lib/plans";

export const metadata: Metadata = { title: "Account" };

export default async function AccountPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const session = await getSession();
  if (!session) redirect("/login");
  const params = await searchParams;

  // The name and join date are the account's own (auth user), read with the person's session.
  const supabase = await createClient();
  const [subscription, plans, { data: auth }] = await Promise.all([getSubscription(session.id), getPlans(), supabase.auth.getUser()]);
  const savedName = auth.user?.user_metadata?.full_name;
  const plan = plans?.find((candidate) => candidate.id === subscription?.plan_id) ?? null;
  return (
    <AccountView
      email={session.email}
      name={typeof savedName === "string" ? savedName : null}
      createdAt={auth.user?.created_at ?? null}
      payments={<PaymentHistory />}
      kind={session.access.kind}
      subscription={subscription}
      plan={plan}
      plans={plans}
      welcome={params.welcome === "1"}
    />
  );
}
