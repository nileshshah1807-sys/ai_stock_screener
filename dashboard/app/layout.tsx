import type { Metadata } from "next";
import { Geist } from "next/font/google";

import { ThemeProvider } from "@/components/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";

import "./globals.css";

/*
 * ---------------------------------------------------------------------------
 * Typeface: Geist (Vercel, SIL Open Font License)
 * ---------------------------------------------------------------------------
 *
 * ONE family for the entire interface -- headings, labels, tickers, prices,
 * every figure in the grid. A separate mono for tickers and numbers read as
 * two unrelated fonts sharing a table; what those call sites need is aligned
 * figures, and Geist's `tnum` feature provides them in the same face.
 *
 * Geist is a neutral grotesque drawn for interfaces: open apertures at 12px,
 * a tall x-height that keeps a dense grid legible, and tight, even figures
 * that hold up at display size with negative tracking.
 *
 * Columnar alignment is requested through `font-variant-numeric: tabular-nums`
 * -- see the `.tabular` and `.font-mono` rules in globals.css.
 *
 * next/font downloads the variable file at build time and serves it from this
 * origin, so it costs one same-origin request rather than a third-party DNS
 * lookup, TLS handshake and render-blocking stylesheet.
 */
const geist = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Winnow",
    template: "%s · Winnow",
  },
  description:
    "Daily equity research screener across NSE and US markets: model decision " +
    "scores, evidence gates, and execution suitability.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geist.variable} h-full antialiased`}
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
