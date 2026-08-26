"use client";

import Image from "next/image";
import { useState } from "react";

import { resolveLogoDomain } from "@/lib/logo-domain.mjs";
import { cn } from "@/lib/utils";

type LogoSize = "sm" | "lg";

const SIZES: Record<LogoSize, { pixels: number; className: string }> = {
  sm: { pixels: 32, className: "size-8 text-[10px]" },
  lg: { pixels: 56, className: "size-14 text-sm" },
};

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
  const resolvedDomain = resolveLogoDomain(domain);
  const dimensions = SIZES[size];
  const logoUrl =
    clientId && resolvedDomain
      ? `https://cdn.brandfetch.io/domain/${encodeURIComponent(resolvedDomain)}` +
        `/w/${dimensions.pixels * 2}/h/${dimensions.pixels * 2}` +
        `/fallback/lettermark/type/icon?c=${encodeURIComponent(clientId)}`
      : null;

  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center font-mono font-bold uppercase text-muted-foreground",
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
          className="size-full object-contain"
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
