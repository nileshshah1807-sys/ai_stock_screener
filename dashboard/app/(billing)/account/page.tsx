import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AccountView } from "@/components/billing/account-view";
import { getSession } from "@/lib/auth";
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

  const [subscription, plans] = await Promise.all([getSubscription(session.id), getPlans()]);
  const plan = plans?.find((candidate) => candidate.id === subscription?.plan_id) ?? null;
  return (
    <AccountView
      email={session.email}
      kind={session.access.kind}
      subscription={subscription}
      plan={plan}
      welcome={params.welcome === "1"}
    />
  );
}
