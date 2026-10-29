"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";
import { CalendarDays, ChevronDown, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Which quarter's results the page shows. The choice is in the URL, with the
 * filters and the search, so a season can be bookmarked; the newest quarter
 * is the page's default and is left out of the URL.
 *
 * Any one-of-a-few choice kept in a URL parameter works the same way (the
 * Analysis tab's index and span): the first option is the default and is
 * left out of the URL.
 */
export function QuarterPicker({
  value,
  options,
  param = "quarter",
  name = "Quarter",
}: {
  value: string;
  options: { value: string; label: string }[];
  param?: string;
  name?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const current = options.find((option) => option.value === value) ?? options[0];

  const choose = (next: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === options[0]?.value) params.delete(param);
    else params.set(param, next);
    // A longer page of the old quarter means nothing in the new one.
    params.delete("shown");
    const text = params.toString();
    startTransition(() => router.push(text ? `${pathname}?${text}` : pathname, { scroll: false }));
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="outline" className="gap-1.5 pr-3" aria-label={`${name}: ${current?.label}`} />}
      >
        {pending ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : (
          <CalendarDays className="size-3.5 text-muted-foreground" aria-hidden />
        )}
        {current?.label}
        <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {options.map((option) => (
          <DropdownMenuItem key={option.value} onClick={() => choose(option.value)}>
            {option.label}
            {option.value === value ? (
              <span className="ml-auto text-xs text-muted-foreground">✓</span>
            ) : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
