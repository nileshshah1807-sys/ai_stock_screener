import { getCloudflareContext } from "@opennextjs/cloudflare";
import type { NextRequest } from "next/server";

import { serveObject, tokenVerifier } from "@/lib/object-gate.mjs";

export const dynamic = "force-dynamic";

const verify = tokenVerifier(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);

/**
 * The static pages' object reads under `next dev`, and if a build ever runs without
 * worker.mjs. Deployed, worker.mjs answers this path before Next loads.
 */
export async function GET(request: NextRequest) {
  const bucket = (getCloudflareContext().env as unknown as Record<string, unknown>).MARKET_DATA;
  return serveObject(request, bucket as Parameters<typeof serveObject>[1], verify);
}
