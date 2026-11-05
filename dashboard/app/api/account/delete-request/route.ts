import { NextResponse } from "next/server";

import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

/**
 * Records that the signed-in user asked to delete their account
 * (subscriptions.delete_requested_at); a person acts on it. Nothing is deleted
 * here. 200: {requested_at}.
 */
export async function POST() {
  const admin = createAdminClient();
  if (!admin) return NextResponse.json({ error: "billing_not_configured" }, { status: 503 });

  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const userId = typeof data?.claims?.sub === "string" ? data.claims.sub : "";
  if (!userId) return NextResponse.json({ error: "unauthenticated" }, { status: 401 });

  // Keep the first request's time; fail loudly if the user has no row.
  const { data: row, error: readError } = await admin
    .from("subscriptions")
    .select("delete_requested_at")
    .eq("user_id", userId)
    .maybeSingle();
  if (readError) return NextResponse.json({ error: "read_failed" }, { status: 500 });
  if (!row) return NextResponse.json({ error: "no_subscription" }, { status: 404 });
  if (row.delete_requested_at) return NextResponse.json({ requested_at: row.delete_requested_at });

  const requestedAt = new Date().toISOString();
  const { data: written, error } = await admin
    .from("subscriptions")
    .update({ delete_requested_at: requestedAt })
    .eq("user_id", userId)
    .select("user_id");
  if (error || !written?.length) return NextResponse.json({ error: "write_failed" }, { status: 500 });
  return NextResponse.json({ requested_at: requestedAt });
}
