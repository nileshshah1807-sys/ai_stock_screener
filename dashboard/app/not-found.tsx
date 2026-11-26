import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import { buttonVariants } from "@/components/ui/button";

/**
 * A URL no route matches. Outside every market layout, so it cannot offer the
 * header's search; it hands the visitor back to the front door, which sends a
 * signed-in viewer on to their market. Static: no viewer data.
 */
export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-4 text-center">
      <BrandMark className="size-10" />
      <h1 className="mt-6 text-title font-semibold">Page not found</h1>
      <Link href="/" className={buttonVariants({ className: "mt-6" })}>
        Go to Cupel
      </Link>
    </main>
  );
}
