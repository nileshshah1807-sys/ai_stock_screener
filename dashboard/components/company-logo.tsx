"use client";

import Image from "next/image";
import { useState } from "react";

import { cn } from "@/lib/utils";

type LogoSize = "sm" | "lg";

const SIZES: Record<LogoSize, { pixels: number; className: string }> = {
  sm: { pixels: 32, className: "size-8 rounded-lg text-[10px]" },
  lg: { pixels: 56, className: "size-14 rounded-xl text-sm" },
};

function normalizeDomain(value: string | null | undefined): string | null {
  const domain = value?.trim().toLowerCase().replace(/^www\./, "");
  if (!domain || !/^[a-z0-9.-]+\.[a-z0-9-]{2,}$/i.test(domain)) return null;
  return domain;
}

export function CompanyLogo({
  symbol,
  domain,
  size = "sm",
  className,
}: {
  symbol: string;
  domain: string | null | undefined;
  size?: LogoSize;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const clientId = process.env.NEXT_PUBLIC_BRANDFETCH_CLIENT_ID?.trim();
  const normalizedDomain = normalizeDomain(domain);
  const dimensions = SIZES[size];
  const logoUrl =
    clientId && normalizedDomain
      ? `https://cdn.brandfetch.io/domain/${encodeURIComponent(normalizedDomain)}` +
        `/w/${dimensions.pixels * 2}/h/${dimensions.pixels * 2}` +
        `/fallback/lettermark/type/icon?c=${encodeURIComponent(clientId)}`
      : null;

  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden border bg-card font-mono font-bold uppercase text-muted-foreground shadow-xs",
        dimensions.className,
        className,
      )}
    >
      {logoUrl && !failed ? (
        <Image
          src={logoUrl}
          width={dimensions.pixels}
          height={dimensions.pixels}
          alt=""
          className="size-full object-contain p-1"
          // Brandfetch already sizes, formats, caches, and serves the asset.
          // Sending it through another optimizer only adds a second image bill.
          unoptimized
          onError={() => setFailed(true)}
        />
      ) : (
        <span>{symbol.trim().charAt(0) || "?"}</span>
      )}
    </span>
  );
}
