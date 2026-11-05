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

  const requestedAt = new Date().toISOString();
  const { error } = await admin
    .from("subscriptions")
    .update({ delete_requested_at: requestedAt })
    .eq("user_id", userId);
  if (error) return NextResponse.json({ error: "write_failed" }, { status: 500 });
  return NextResponse.json({ requested_at: requestedAt });
}
