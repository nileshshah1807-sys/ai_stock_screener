import { NextResponse } from "next/server";

import { LEGAL } from "@/lib/legal";
import { handleInbound } from "@/lib/support-inbound.mjs";
import { MAX_INBOUND_BYTES } from "@/lib/support.mjs";
import { createAdminClient } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

/**
 * Resend's `email.received` webhook for the support address: mail to it becomes a
 * JSM ticket. Signed by Resend (RESEND_INBOUND_WEBHOOK_SECRET); unsigned calls get
 * 401. Dedupe is the insert into support_inbound_emails
 * (storage/support_inbound_schema.sql, applied by hand).
 */
export async function POST(request: Request) {
  const admin = createAdminClient();
  if (!admin) return NextResponse.json({ error: "not_configured" }, { status: 503 });
  const rawBody = await request.text();
  if (rawBody.length > MAX_INBOUND_BYTES) return NextResponse.json({ error: "too_large" }, { status: 413 });

  const { status, body } = await handleInbound({
    rawBody,
    headers: request.headers,
    env: process.env,
    supportAddress: LEGAL.contactEmail,
    claim: async (emailId: string) => {
      const { error } = await admin.from("support_inbound_emails").insert({ email_id: emailId });
      if (!error) return true;
      if (error.code === "23505") return false; // already ticketed
      throw error;
    },
    release: async (emailId: string) => void (await admin.from("support_inbound_emails").delete().eq("email_id", emailId)),
  });
  return NextResponse.json(body, { status });
}
