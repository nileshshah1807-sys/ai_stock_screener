"use client";

import { useEffect, useRef } from "react";
import { useTheme } from "next-themes";

import { WIDGET_SRC, widgetConfig } from "@/lib/tradingview.mjs";
import type { MarketCode } from "@/lib/markets";

/**
 * TradingView's Advanced Chart widget for one stock (lib/tradingview.mjs says
 * why and when). The widget's script reads its configuration from its own
 * text, so it is added fresh on every symbol or theme change.
 */
export function TradingViewChart({
  symbol,
  market,
  height = 460,
}: {
  symbol: string;
  market: MarketCode;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const node = container.current;
    if (!node || !resolvedTheme) return;
    // The script restyles its container, so the height lives on our outer box
    // and the container only fills it.
    const host = document.createElement("div");
    host.className = "tradingview-widget-container";
    host.style.height = "100%";
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = "100%";
    const script = document.createElement("script");
    script.src = WIDGET_SRC;
    script.async = true;
    script.text = JSON.stringify(widgetConfig(symbol, market, resolvedTheme === "dark"));
    host.append(widget, script);
    node.replaceChildren(host);
    return () => node.replaceChildren();
  }, [symbol, market, resolvedTheme]);

  return (
    <div
      ref={container}
      className="overflow-hidden rounded-md"
      style={{ height }}
      aria-label={`${symbol} price chart`}
    />
  );
}
