import type { Metadata } from "next";

/** One set for /pricing, whichever copy serves it (the static one is app/pricing-static). */
export const pricingMetadata: Metadata = {
  title: "Pricing",
  description: "Cupel plans and prices: a yearly and a monthly plan covering NSE and US stocks, a screener, quarterly results and earnings calls. Data for research and education, not investment advice.",
  robots: { index: true, follow: true },
  alternates: { canonical: "/pricing" },
};
