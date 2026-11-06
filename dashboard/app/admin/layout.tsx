import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import { LEGAL } from "@/lib/legal";

export default function AdminLayout({ children }: LayoutProps<"/">) {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-12">
      <div className="mb-8 flex items-center justify-between gap-4">
        <Link href="/screener" className="inline-flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <BrandMark className="size-4" />
          </span>
          <span className="text-lead font-semibold tracking-[-0.011em]">{LEGAL.service}</span>
        </Link>
        <Link href="/screener" className="rounded text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Back to the app
        </Link>
      </div>
      {children}
    </main>
  );
}
