import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { BrandMark } from "@/components/brand-mark";
import { Evening } from "@/components/landing/evening";
import { FactorBar } from "@/components/landing/factor-bar";
import { HeroGrid } from "@/components/landing/hero-grid";
import { LandingMarket } from "@/components/landing/landing-market";
import { LandingMotion } from "@/components/landing/landing-motion";
import { LandingPricing } from "@/components/landing/landing-pricing";
import { Pipeline } from "@/components/landing/pipeline";
import { Sieve } from "@/components/landing/sieve";
import { StageLine } from "@/components/landing/stage-line";
import { VisitorSwap } from "@/components/landing/visitor-swap";
import { SiteFooter } from "@/components/site-footer";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { daysPhrase, trialName } from "@/lib/billing.mjs";
import { getTrialDays } from "@/lib/trial-days";
import { faqJsonLd, siteJsonLd } from "@/lib/seo.mjs";
import { cn } from "@/lib/utils";

const TITLE = "Cupel: NSE and US stock screener, results and earnings calls";
const DESCRIPTION =
  "Screen NSE and US stocks, read quarterly results as companies file them, and follow what management said on earnings calls. Data for research and education, not investment advice.";

// The root layout is noindex for the signed-in app; the landing page is the
// one public page meant to be found.
export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  alternates: { canonical: "/" },
  openGraph: { title: TITLE, description: DESCRIPTION, siteName: "Cupel", type: "website" },
};

// Built once and rebuilt every five minutes, the same page for every visitor (the signed-in buttons
// and the market tab are chosen in the browser): served from the cache, not rendered per request.
export const revalidate = 300;

const COVERAGE = [
  ["Quarterly results", "Exchange filing", "Financial statements"],
  ["Earnings calls", "Usually read that evening", "Not covered"],
  ["Management guidance", "Read from the call", "Not covered"],
] as const;

const NAV = [
  { href: "#how", label: "How it works" },
  { href: "#ranking", label: "Ranking" },
  { href: "#stage", label: "Stage" },
  { href: "#pricing", label: "Pricing" },
  { href: "#faq", label: "FAQ" },
];

const faq = (trialDays: number) => [
  ["Is this investment advice?", "No. Cupel shows data and measurements for research and education. It does not tell you what to buy or sell, and nothing on it is a recommendation. Read the Disclaimer for the details."],
  ["Which markets are covered?", "India (NSE, plus companies listed on BSE alone) and the US, under one subscription."],
  ["Where does the data come from?", "Quarterly results and shareholding from the exchange's filings, US statements from SEC EDGAR, prices from Yahoo Finance. Live prices refresh about every five minutes in market hours and are indicative; the daily measurements update after the close."],
  ["How does the free trial work?", `Sign in with your email and get ${daysPhrase(trialDays)} of full access. Subscribing during the trial ends it and starts your plan at once, with the first payment that day, and it is refunded in full within 7 days of a payment.`],
  ["How do I pay, and can I cancel?", "Payments go through Razorpay by UPI or card, and the early-bird price uses UPI Autopay. Cancel any time from your account. A payment is refunded in full within 7 days; see the Refund policy."],
];

const ghost = "rounded-md px-2.5 py-2 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const section = "mx-auto w-full max-w-6xl px-4 sm:px-6";
const h2 = "text-title max-w-[22ch] text-balance";

export default async function LandingPage() {
  const trialDays = await getTrialDays();

  return (
    <div className="landing flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:shadow-md">
        Skip to content
      </a>

      <div aria-hidden data-progress className="landing-progress" />
      <LandingMotion />

      <header className="sticky top-0 z-40 border-b bg-background">
        <div className={cn(section, "flex h-14 items-center gap-4")}>
          <Link href="/" className="flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <BrandMark className="size-4" />
            </span>
            <span className="text-lead font-semibold tracking-[-0.011em]">Cupel</span>
          </Link>
          <nav aria-label="Sections" className="ml-4 hidden items-center gap-1 md:flex">
            {NAV.map((item) => (
              <a key={item.href} href={item.href} className={ghost}>{item.label}</a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <VisitorSwap
              signedIn={<Link href="/screener" className={cn(buttonVariants(), "h-9")}>Open the app</Link>}
              signedOut={
                <>
                  <Link href="/login" className={cn(buttonVariants({ variant: "ghost" }), "hidden h-9 sm:inline-flex")}>Sign in</Link>
                  <Link href="/login?trial=1" className={cn(buttonVariants(), "h-9")}>
                    <span className="sm:hidden">Try free</span>
                    <span className="hidden sm:inline">Start {trialName(trialDays)}</span>
                  </Link>
                </>
              }
            />
          </div>
        </div>
      </header>

      <main id="main" className="flex-1">
        <LandingMarket>
          <section className="border-b">
            <div className={cn(section, "py-12 sm:py-16")}>
              <div className="max-w-3xl motion-safe:animate-rise">
                <h1 className="text-[clamp(2.25rem,5.4vw,4rem)] font-semibold leading-[1.04] tracking-[-0.035em] text-balance">
                  Thousands of stocks in. A short list out.
                </h1>
                <p className="mt-5 max-w-[46ch] text-lead text-muted-foreground sm:text-base">
                  Cupel screens NSE and US stocks every evening, so you start from a short list, not a whole market.
                </p>
                <div className="mt-7 flex flex-wrap items-center gap-3">
                  <VisitorSwap
                    signedIn={<Link href="/screener" className={cn(buttonVariants({ size: "lg" }), "h-11 px-5")}>Open the app</Link>}
                    signedOut={
                      <>
                        <Link href="/login?trial=1" className={cn(buttonVariants({ size: "lg" }), "h-11 px-5")}>Start {trialName(trialDays)}</Link>
                        <Link href="/login" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 px-5")}>Sign in</Link>
                      </>
                    }
                  />
                </div>
                <p className="mt-4 text-xs text-muted-foreground">Data for research and education, not investment advice.</p>
              </div>
              <div className="mx-auto mt-10 max-w-3xl">
                <Sieve />
                <div className="mt-6">
                  <HeroGrid />
                </div>
              </div>
            </div>
          </section>

          <section id="how" className={cn(section, "scroll-mt-16 py-14 sm:py-20")}>
            <h2 data-reveal className={h2}>From filings to your screen, every evening</h2>
            <div className="mt-10">
              <Pipeline />
            </div>
            <p className="mt-6 max-w-[64ch] text-xs text-muted-foreground">
              Sources: NSE and BSE filings, SEC EDGAR, Yahoo Finance. Live prices are indicative.
            </p>
          </section>

          <section id="ranking" className="scroll-mt-16 border-y bg-card">
            <div className={cn(section, "py-14 sm:py-20")}>
              <h2 data-reveal className={h2}>What the ranking weighs</h2>
              <div data-reveal className="mt-10 max-w-3xl">
                <FactorBar />
              </div>
              <table className="mt-8 w-full max-w-3xl text-left text-sm">
                <caption className="pb-2 text-left text-xs text-muted-foreground">India and US differ here</caption>
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th scope="col" className="py-2 pr-4 font-medium">Evidence</th>
                    <th scope="col" className="py-2 pr-4 font-medium">India</th>
                    <th scope="col" className="py-2 font-medium">US</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {COVERAGE.map(([what, india, us]) => (
                    <tr key={what}>
                      <th scope="row" className="py-2 pr-4 font-medium">{what}</th>
                      <td className="py-2 pr-4">{india}</td>
                      <td className="py-2">{us}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-6 max-w-[60ch] text-sm font-medium">A way to decide what to read first. Not a buy or sell call, and not investment advice.</p>
            </div>
          </section>

        <section id="stage" className={cn(section, "scroll-mt-16 py-14 sm:py-20")}>
          <h2 data-reveal className={h2}>See where a stock is in its cycle</h2>
          <div className="mt-8 max-w-3xl">
            <StageLine />
          </div>
        </section>

        <section id="evening" className="scroll-mt-16 border-y bg-card">
          <div className={cn(section, "py-14 sm:py-20")}>
            <h2 data-reveal className={h2}>Results land. Cupel reads them that evening.</h2>
            <div className="mt-10 max-w-4xl">
              <Evening />
            </div>
          </div>
        </section>

        </LandingMarket>

        <section id="pricing" className="scroll-mt-16">
          <div className={cn(section, "py-14 sm:py-20")}>
            <h2 data-reveal className={h2}>One subscription, both markets</h2>
            <p className="mt-3 text-sm text-muted-foreground">Start with {daysPhrase(trialDays)} free. Prices are in Indian rupees (INR).</p>
            <div className="mt-10">
              <Suspense fallback={<div className="panel h-72 motion-safe:animate-pulse" aria-hidden />}>
                <LandingPricing />
              </Suspense>
            </div>
          </div>
        </section>

        <section id="faq" className={cn(section, "scroll-mt-16 border-t py-14 sm:py-20")}>
          <h2 data-reveal className={h2}>Questions</h2>
          <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: faqJsonLd(faq(trialDays)) }} />
          <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: siteJsonLd() }} />
          <div data-stagger className="mt-8 max-w-3xl divide-y border-y">
            {faq(trialDays).map(([q, a]) => (
              <details key={q} className="group py-4">
                <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-4 rounded text-lead font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                  {q}
                  <span aria-hidden className="text-muted-foreground transition-transform group-open:rotate-45">+</span>
                </summary>
                <p className="mt-3 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">{a}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="bg-primary text-primary-foreground">
          <div className={cn(section, "flex flex-col items-start gap-5 py-14 sm:py-20")}>
            <h2 data-reveal className={h2}>Try it on this week&apos;s results</h2>
            <div className="flex flex-wrap gap-3">
              <VisitorSwap
                signedIn={<Link href="/screener" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 px-5")}>Open the app</Link>}
                signedOut={
                  <>
                    <Link href="/login?trial=1" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 px-5")}>Start {trialName(trialDays)}</Link>
                    <Link href="/login" className="inline-flex h-11 items-center rounded-md px-4 text-sm font-medium underline underline-offset-4 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Sign in</Link>
                  </>
                }
              />
            </div>
          </div>
        </section>
      </main>

      <SiteFooter width="max-w-6xl px-4 sm:px-6" />
    </div>
  );
}
