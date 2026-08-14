import type { Metadata } from "next";
import localFont from "next/font/local";

import { ThemeProvider } from "@/components/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";

import "./globals.css";

/*
 * ---------------------------------------------------------------------------
 * Typeface: Satoshi (Deni Anggara, Indian Type Foundry via Fontshare)
 * ---------------------------------------------------------------------------
 *
 * ONE family for the entire interface -- headings, labels, tickers, prices,
 * every figure in the grid. There is no second "mono" face any more, and that
 * is the point: the previous pairing set stock symbols and numbers in Geist
 * Mono while everything around them was General Sans, which read as two
 * unrelated fonts sharing a table.
 *
 * Satoshi is the family that makes a single face possible here. It ships a
 * `tnum` feature, so its digits are proportional by default -- which is what
 * you want for a 64px KPI figure -- and switch to fixed-width on demand for
 * anything that has to line up down a column. General Sans could not do this:
 * it has no `tnum` at all and its "1" advances 384 units against "0" at 630,
 * so a column of prices simply would not align, which is why it needed a mono
 * companion in the first place.
 *
 * Columnar alignment is requested through `font-variant-numeric: tabular-nums`
 * -- see the `.tabular` and `.font-mono` rules in globals.css.
 *
 * Self-hosted: the whole 300-900 weight range is one 42KB variable file, so it
 * costs a single same-origin request rather than a third-party DNS lookup, TLS
 * handshake and render-blocking stylesheet. Licence is vendored beside the
 * font as Satoshi-LICENSE.txt.
 */
const satoshi = localFont({
  variable: "--font-sans",
  display: "swap",
  src: [
    {
      path: "./fonts/Satoshi-Variable.woff2",
      weight: "300 900",
      style: "normal",
    },
    {
      path: "./fonts/Satoshi-VariableItalic.woff2",
      weight: "300 900",
      style: "italic",
    },
  ],
});

export const metadata: Metadata = {
  title: {
    default: "NSE Screener",
    template: "%s · NSE Screener",
  },
  description:
    "Daily NSE research screener: model decision scores, evidence gates, and execution suitability.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${satoshi.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <TooltipProvider delay={200}>{children}</TooltipProvider>
          <Toaster position="bottom-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}
