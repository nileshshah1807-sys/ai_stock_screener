import type { Metadata } from "next";
import { getTrialDays } from "@/lib/trial-days";
import { Suspense } from "react";

import { BrandMark } from "@/components/brand-mark";
import { SiteFooter } from "@/components/site-footer";
import { sessionMaxAgeSeconds } from "@/lib/session-policy.mjs";

import { LoginPanel, LoginPanelView } from "./login-panel";

export const metadata: Metadata = { title: "Sign in" };
export const revalidate = 300;

export default async function LoginPage() {
  // Static, refreshed every 5 minutes: the query string (?error, ?trial) is read in the browser
  // (LoginPanel), so a visit renders nothing on the server -- the Worker's CPU limit is 10 ms.
  const trialDays = await getTrialDays();
  const panelProps = { trialDays, sessionLabel: sessionLifetimeLabel() };

  return (
    <div className="flex min-h-dvh flex-col">
      <main className="flex flex-1 items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          {/* The same mark-in-a-disc and wordmark as the app header, so the door
              and the room behind it are visibly the same product. */}
          <div className="mb-6 flex animate-rise items-center justify-center gap-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <BrandMark className="size-4" />
            </span>
            <span className="text-lead font-semibold tracking-[-0.011em]">
              Cupel
            </span>
          </div>

          <Suspense fallback={<LoginPanelView {...panelProps} errorCode={null} trial={false} />}>
            <LoginPanel {...panelProps} />
          </Suspense>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}

/** "7 days", "12 hours" -- the configured lifetime in the largest unit that divides it. */
function sessionLifetimeLabel(): string {
  const hours = sessionMaxAgeSeconds() / 3600;
  const [count, unit] =
    hours >= 24 && hours % 24 === 0 ? [hours / 24, "day"] : [hours, "hour"];
  return `${Number(count.toFixed(1))} ${unit}${count === 1 ? "" : "s"}`;
}
