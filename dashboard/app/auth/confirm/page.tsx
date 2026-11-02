import type { Metadata } from "next";

import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { confirmLink } from "@/app/login/actions";

export const metadata: Metadata = { title: "Continue to Winnow" };

/**
 * Where an emailed link lands. The one-time token is spent by the button, not
 * by loading this page: mail providers open links to scan them, and a link that
 * signed in on load would be used up before the person clicked it.
 */
export default async function ConfirmPage({ searchParams }: PageProps<"/auth/confirm">) {
  const params = await searchParams;
  const one = (key: string) => (typeof params[key] === "string" ? (params[key] as string) : "");

  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex animate-rise items-center justify-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <BrandMark className="size-4" />
          </span>
          <span className="text-lead font-semibold tracking-[-0.011em]">Winnow</span>
        </div>
        <div className="panel animate-rise p-6 sm:p-8">
          <h1 className="text-heading font-semibold">Continue to Winnow</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Press the button to finish signing in. The link works once and expires 15 minutes after it was sent.
          </p>
          <form action={confirmLink} className="mt-6">
            <input type="hidden" name="token_hash" value={one("token_hash")} />
            <input type="hidden" name="type" value={one("type")} />
            <input type="hidden" name="next" value={one("next")} />
            <Button type="submit" className="h-10 w-full">
              Continue
            </Button>
          </form>
        </div>
      </div>
    </main>
  );
}
