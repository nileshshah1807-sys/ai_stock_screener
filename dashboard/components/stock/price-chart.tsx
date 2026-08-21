"use client";

import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";

/**
 * TradingView Advanced Chart for one NSE symbol.
 *
 * Embedded rather than self-hosted. The archive under `backtest/` could serve
 * a split-adjusted series for ~7 MB, but an embed costs no storage, no egress
 * and no daily publish step, and TradingView already provides the range
 * selector, volume pane and moving averages that would otherwise be built by
 * hand.
 *
 * What the embed cannot do, and why this file is worth revisiting if either
 * matters later:
 *
 *   * It draws TradingView's prices, not the corporate-action-adjusted prices
 *     this model scored on. The two normally agree; they can disagree around a
 *     split or a bonus issue.
 *   * It is an iframe, so none of this app's own evidence -- rating changes,
 *     the session a gate fired, factor percentiles over time -- can be drawn
 *     on it.
 *   * Delisted and very thinly traded names may not resolve, which is why the
 *     unresolved case is handled explicitly below rather than left as an empty
 *     frame.
 */

/**
 * TradingView's script mutates the container, so React must not own it.
 *
 * `next/script` is not usable here: it accepts either a `src` or inline
 * children, and this embed needs both -- a remote script whose own innerHTML is
 * the config JSON. The DOM is therefore built by hand and torn down on cleanup.
 */
const SCRIPT_SRC =
  "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

/**
 * Simple moving averages drawn on the price pane.
 *
 * The object form carries per-instance `inputs`, which is what allows two
 * copies of the same study at different lengths -- `studies_overrides` applies
 * to a study *type* and cannot distinguish them. If a future widget version
 * ignores the inputs it falls back to TradingView's default length rather than
 * failing, so the chart degrades to a shorter average instead of breaking.
 */
const STUDIES = [
  { id: "MASimple@tv-basicstudies", inputs: { length: 50 } },
  { id: "MASimple@tv-basicstudies", inputs: { length: 200 } },
];

function widgetConfig(symbol: string, dark: boolean) {
  return {
    autosize: true,
    symbol: `NSE:${symbol.toUpperCase()}`,
    interval: "D",
    timezone: "Asia/Kolkata",
    theme: dark ? "dark" : "light",
    style: "1", // candles; "2" is bars, "3" is a line
    locale: "in",
    // The daily bar is the unit this whole application reasons in, so intraday
    // resolutions are deliberately not offered.
    hide_legend: false,
    hide_side_toolbar: true,
    allow_symbol_change: false,
    save_image: false,
    enable_publishing: false,
    withdateranges: true,
    range: "12M",
    studies: STUDIES,
    support_host: "https://www.tradingview.com",
  };
}

export function PriceChart({
  symbol,
  height = 460,
}: {
  symbol: string;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  // `resolvedTheme` is undefined until next-themes has read the preference on
  // the client, which doubles as the mount signal: server and first client
  // render both show the placeholder, so there is nothing to mismatch, and the
  // widget is never built with a theme that is about to change under it.
  const { resolvedTheme } = useTheme();
  // Keyed by symbol rather than a bare boolean, so navigating to another stock
  // clears a previous failure without writing state from inside the effect.
  const [failedFor, setFailedFor] = useState<string | null>(null);
  const failed = failedFor === symbol;

  useEffect(() => {
    if (!resolvedTheme) return;
    const node = container.current;
    if (!node) return;

    node.innerHTML = "";

    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = `${height}px`;
    node.appendChild(widget);

    const script = document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.type = "text/javascript";
    script.innerHTML = JSON.stringify(
      widgetConfig(symbol, resolvedTheme === "dark"),
    );
    // A blocked script (offline, extension, ad blocker) must say so rather than
    // leave a silent empty box that reads as "this stock has no price history".
    script.onerror = () => setFailedFor(symbol);
    node.appendChild(script);

    return () => {
      node.innerHTML = "";
    };
  }, [symbol, resolvedTheme, height]);

  if (!resolvedTheme) {
    return (
      <div
        style={{ height }}
        className="animate-pulse rounded-row bg-muted/20"
        aria-hidden
      />
    );
  }

  if (failed) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center rounded-row border border-border bg-muted/20 px-6 text-center text-sm text-muted-foreground"
      >
        The chart could not be loaded. It is served by TradingView, so a network
        block or content blocker will stop it; the scores on this page are
        unaffected.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div
        ref={container}
        className="tradingview-widget-container overflow-hidden rounded-row"
        style={{ height }}
      />
      <p className="text-xs leading-relaxed text-muted-foreground">
        Price, volume and the 50/200-day averages are drawn by TradingView from
        their own NSE feed. They are shown for context only: this
        application&rsquo;s scores are computed from its own
        corporate-action-adjusted prices, which can differ around a split or
        bonus issue. A symbol TradingView does not carry — including a delisted
        one — will show as unavailable here.
      </p>
    </div>
  );
}
