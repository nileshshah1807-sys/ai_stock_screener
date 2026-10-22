"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Run health, as an icon among the account controls.
 *
 * It was the sixth tab in the primary nav. That group is the reader's
 * destinations -- where the stocks are -- and run health is about the system
 * that produced them: looked at when something seems off, not on the way to a
 * stock. It sits with the other things about the app itself (theme, session).
 *
 * Still a link with its own URL, and still marked current for assistive
 * technology and by a filled ground, since the nav's lens no longer does it.
 */
export function HealthLink({ href }: { href: string }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      aria-label="Run health"
      title="Run health"
      className={cn(
        buttonVariants({ variant: "ghost", size: "icon" }),
        "text-muted-foreground hover:text-foreground",
        active && "bg-(--control) text-foreground",
      )}
    >
      <Activity className="size-4" aria-hidden />
    </Link>
  );
}
