import { NextResponse } from "next/server";

import { createLimiter, submitSupport } from "@/lib/support.mjs";

export const dynamic = "force-dynamic";

const limiter = createLimiter();

/**
 * The Help & Support form. Public: someone locked out must be able to write.
 * 200 {ok}, 400/429 {error: text to show}, 502 {error}, 503 {error:
 * "not_configured"} when JSM is not set up (the form then offers a mailto link).
 */
export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
  const { status, body: payload } = await submitSupport({ body, env: process.env, ip, limiter });
  return NextResponse.json(payload, { status });
}
