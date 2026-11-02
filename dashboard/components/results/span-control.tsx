"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";

import { SegmentedControl } from "@/components/segmented-control";

/**
 * A few-choice setting kept in a URL parameter, as a segmented control: the
 * Analysis tab's quarter count. The first option is the default and is left
 * out of the URL, like QuarterPicker.
 */
export function SpanControl({
  param,
  name,
  value,
  defaultValue,
  options,
}: {
  param: string;
  name: string;
  value: string;
  /** Left out of the URL. */
  defaultValue: string;
  options: { value: string; label: string }[];
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const choose = (next: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === defaultValue) params.delete(param);
    else params.set(param, next);
    const text = params.toString();
    startTransition(() => router.push(text ? `${pathname}?${text}` : pathname, { scroll: false }));
  };

  return <SegmentedControl label={name} value={value} onChange={choose} options={options} />;
}
