import { NextResponse } from "next/server";

import { LEGAL } from "@/lib/legal";
import { claimEmail, handleInbound } from "@/lib/support-inbound.mjs";
import { MAX_INBOUND_BYTES } from "@/lib/support.mjs";
import { createAdminClient } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";
// Fetching the mail and opening the ticket take seconds; an unfinished claim goes stale after five minutes.
export const maxDuration = 60;

const TABLE = "support_inbound_emails";

/**
 * Resend's `email.received` webhook for the support address: mail to it becomes a
 * JSM ticket. Signed by Resend (RESEND_INBOUND_WEBHOOK_SECRET); unsigned calls get
 * 401. Dedupe is a claim row in support_inbound_emails (storage/support_inbound_schema.sql,
 * applied by hand): a finished email is never ticketed twice, an unfinished claim older
 * than five minutes (a timed-out call) is taken over by the retry.
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
    claim: (emailId: string) =>
      claimEmail(
        {
          insert: async (id: string, at: number) => {
            const { error } = await admin.from(TABLE).insert({ email_id: id, received_at: new Date(at).toISOString() });
            if (!error) return true;
            if (error.code === "23505") return false; // already claimed
            throw error;
          },
          // Only an unfinished claim, and only one older than the cut-off, is taken over.
          reclaim: async (id: string, staleBefore: number, at: number) => {
            const { data, error } = await admin
              .from(TABLE)
              .update({ received_at: new Date(at).toISOString() })
              .eq("email_id", id)
              .is("completed_at", null)
              .lt("received_at", new Date(staleBefore).toISOString())
              .select("email_id");
            if (error) throw error;
            return (data?.length ?? 0) > 0;
          },
        },
        emailId,
      ),
    complete: async (emailId: string) => {
      const { error } = await admin.from(TABLE).update({ completed_at: new Date().toISOString() }).eq("email_id", emailId);
      if (error) throw error;
    },
    release: async (emailId: string) => {
      const { error } = await admin.from(TABLE).delete().eq("email_id", emailId);
      if (error) throw error;
    },
  });
  return NextResponse.json(body, { status });
}
