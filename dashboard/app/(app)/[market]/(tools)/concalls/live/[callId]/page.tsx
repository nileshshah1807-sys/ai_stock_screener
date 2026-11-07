import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft } from "lucide-react";

import { LiveTranscript } from "@/components/concalls/live-transcript";
import { StockIdentity } from "@/components/stock-identity";
import { getLiveCall } from "@/lib/live-calls";
import { marketFromSlug, marketPath } from "@/lib/markets";
import { getCompanyFacts } from "@/lib/queries";

export const metadata: Metadata = { title: "Live call" };
export const dynamic = "force-dynamic";

/** One call as it is spoken. NSE only, like the Concalls page. */
export default async function LiveCallPage({ params }: PageProps<"/[market]/concalls/live/[callId]">) {
  const { market: slug, callId: raw } = await params;
  const market = marketFromSlug(slug)!;
  if (market.code !== "NSE") notFound();
  const callId = decodeURIComponent(raw);
  const [found, facts] = await Promise.all([getLiveCall(market.code, callId), getCompanyFacts(market.code)]);
  if (!found) notFound();
  const { call, lines, sample } = found;
  const logo = (facts ?? []).find((fact) => fact.symbol === call.symbol)?.logo_domain;

  return (
    <div className="mx-auto max-w-3xl space-y-4 px-4 py-5 sm:px-6">
      <Link
        href={`${marketPath(market.slug, "/concalls")}?view=live`}
        className="inline-flex items-center gap-1 rounded text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft className="size-3.5" aria-hidden /> Live now
      </Link>
      {sample ? (
        <p className="text-xs text-muted-foreground">
          Sample call: the live-call tables are not applied to this preview, so these lines are made up.
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Unverified automatic transcript, made as the call is spoken. It may contain errors and is not a record of what was said; the company&rsquo;s filed transcript is.
      </p>
      <LiveTranscript
        callId={call.call_id}
        sample={sample}
        startedAt={call.started_at}
        initialLines={lines}
        initialState={call.state}
        identity={<StockIdentity symbol={call.symbol} logoDomain={logo} link={!sample} size="md" className="min-w-0 flex-1" />}
      />
    </div>
  );
}
