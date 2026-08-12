import type { Metadata } from "next";
import { ShieldX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/server";

import { signOut } from "../login/actions";

export const metadata: Metadata = { title: "No access" };

/**
 * Reached when someone authenticates successfully but is not on the allowlist.
 * Distinguishing this from "not signed in" avoids a confusing loop where a
 * valid session is repeatedly bounced back to a login form that then reports
 * success.
 */
export default async function NoAccessPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-12">
      <div className="w-full max-w-md text-center">
        <ShieldX className="mx-auto size-8 text-muted-foreground" aria-hidden />
        <h1 className="mt-4 text-lg font-semibold">Access not enabled</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {user?.email ? (
            <>
              <span className="font-mono">{user.email}</span> is signed in but
              is not on the dashboard invite list.
            </>
          ) : (
            "This account is not on the dashboard invite list."
          )}
        </p>
        <p className="mt-4 text-xs text-muted-foreground">
          An administrator can grant access by adding the address to{" "}
          <code className="font-mono">dashboard_allowlist</code>.
        </p>

        <form action={signOut} className="mt-6">
          <Button type="submit" variant="outline" formAction={signOut}>
            Sign out
          </Button>
        </form>
      </div>
    </main>
  );
}
