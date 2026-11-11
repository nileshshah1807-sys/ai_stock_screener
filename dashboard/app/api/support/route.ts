import { NextResponse } from "next/server";

import { getSession } from "@/lib/auth";
import { MAX_BODY_BYTES, createLimiter, submitSupport } from "@/lib/support.mjs";

export const dynamic = "force-dynamic";

const limiter = createLimiter();

/**
 * The Help & Support form. Signed-in only (the request is raised for the session's email, never a typed
 * one); the page shows signed-out visitors a mailto link instead of the form.
 * 200 {ok}, 400/429 {error: text to show}, 401, 413, 502, 503 {error:
 * "not_configured"} when JSM is not set up.
 */
export async function POST(request: Request) {
  // Refuse by the declared size before reading, and again by the real one.
  if (Number(request.headers.get("content-length")) > MAX_BODY_BYTES) return NextResponse.json({ error: "Message too long." }, { status: 413 });
  const text = await request.text();
  if (text.length > MAX_BODY_BYTES) return NextResponse.json({ error: "Message too long." }, { status: 413 });
  let body = null;
  try {
    body = JSON.parse(text);
  } catch {}
  const session = await getSession();
  // Cloudflare sets cf-connecting-ip to the client; x-forwarded-for is the fallback for local runs.
  const ip = request.headers.get("cf-connecting-ip") || request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
  const { status, body: payload } = await submitSupport({ body, email: session?.email ?? null, env: process.env, keys: [ip, session?.id ?? ip], limiter });
  return NextResponse.json(payload, { status });
}
