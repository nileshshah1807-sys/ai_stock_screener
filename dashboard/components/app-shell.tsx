import { Suspense, type ComponentProps } from "react";

import { AppFrame } from "@/components/app-frame";
import { TrialBanner } from "@/components/trial-banner";
import { trialStartLine } from "@/lib/billing.mjs";
import { readsFromCloudflare } from "@/lib/db/market-repository";
import { getPlans, getSubscription } from "@/lib/plans";

/**
 * The chrome as a server render draws it: AppFrame with the two parts only the
 * server can read, the trial banner's subscription and the Worker's TABLE_BACKEND.
 * A static page draws AppFrame from the browser instead (components/browser-shell.tsx).
 */
export function AppShell(props: Omit<ComponentProps<typeof AppFrame>, "trialBanner" | "liveFromR2">) {
  const { access, id } = props.viewer;
  return (
    <AppFrame
      {...props}
      liveFromR2={readsFromCloudflare("live_quotes")}
      trialBanner={
        access.kind === "trial" && access.daysLeft ? (
          <Suspense fallback={null}>
            <TrialBannerFor days={access.daysLeft} userId={id} />
          </Suspense>
        ) : null
      }
    />
  );
}

/** The banner for a signed-in trial user: says so when a plan is already set up. */
async function TrialBannerFor({ days, userId }: { days: number; userId: string }) {
  const subscription = await getSubscription(userId);
  const plans = subscription?.plan_id ? await getPlans() : null;
  const plan = plans?.find((candidate) => candidate.id === subscription?.plan_id) ?? null;
  return <TrialBanner days={days} setUp={trialStartLine(subscription, plan)} />;
}
