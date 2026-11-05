import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { BrandMark } from "@/components/brand-mark";
import { HeroGrid } from "@/components/landing/hero-grid";
import { LandingPricing } from "@/components/landing/landing-pricing";
import { ProductTour } from "@/components/landing/product-tour";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { getSession } from "@/lib/auth";
import { LEGAL, LEGAL_PAGES } from "@/lib/legal";
import { cn } from "@/lib/utils";

const TITLE = "Sievr: daily screener for NSE and US stocks";
const DESCRIPTION =
  "Screen every NSE and US stock, read quarterly results as companies file them, and follow what management said on earnings calls. Data for research and education, not investment advice.";

// The root layout is noindex for the signed-in app; the landing page is the
// one public page meant to be found.
export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  openGraph: { title: TITLE, description: DESCRIPTION, siteName: "Sievr", type: "website" },
};

const NAV = [
  { href: "#product", label: "Product" },
  { href: "#how", label: "How it works" },
  { href: "#pricing", label: "Pricing" },
  { href: "#faq", label: "FAQ" },
];

const FEATURES = [
  ["One screen, two markets", "NSE, BSE-only companies and the US in the same grid, with the same filters and saved views. Switch market without relearning the page."],
  ["Results the evening they land", "Quarterly results are read from the exchange's filings as they are stored, set beside the year-ago quarter on the same basis."],
  ["Earnings calls, read for you", "Every call summarised, with management's tone in a word and the statement that moved it most quoted back."],
  ["Market breadth and Stage 2 counts", "How many stocks sit above their long averages and how many are in Stage 2, for each market, redrawn after the close."],
  ["Index pages", "Open an index and see its constituents in the screener's own grid, with live prices during the session."],
  ["Shareholding and documents", "Shareholding patterns, bulk and block deals, presentations and annual reports for Indian stocks, linked to the exchange archive."],
];

const STEPS = [
  ["We collect", "Exchange filings, SEC EDGAR statements, earnings-call recordings and transcripts, and market prices."],
  ["We process, every day", "After each close the whole universe is re-measured. Companies are compared with their own market, never across it."],
  ["You read and filter", "Screen, open a stock, read the results and the call, and keep a watchlist. A bell tells you when a company you follow reports."],
];

const FAQ = [
  ["Is this investment advice?", "No. Sievr shows data and measurements for research and education. It does not tell you what to buy or sell, and nothing on it is a recommendation. Read the Disclaimer for the details."],
  ["Which markets are covered?", "India (NSE, plus companies listed on BSE alone) and the US, under one subscription."],
  ["Where does the data come from?", "Quarterly results and shareholding from the exchange's filings, US statements from SEC EDGAR, prices from Yahoo Finance. Live prices refresh about every five minutes in market hours and are indicative; the daily measurements update after the close."],
  ["How does the free trial work?", "Sign in with your email and get 7 days of full access. Subscribe from the pricing page when you want to carry on."],
  ["How do I pay, and can I cancel?", "Payments go through Razorpay by UPI or card, and the early-bird price uses UPI Autopay. Cancel any time from your account. A payment is refunded in full within 7 days; see the Refund policy."],
];

const ghost = "rounded-md px-2 py-1 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const section = "mx-auto w-full max-w-6xl px-4 sm:px-6";
const h2 = "text-title max-w-[22ch] text-balance";

export default async function LandingPage() {
  const session = await getSession();
  const contact = LEGAL.contactEmail.startsWith("[") ? null : LEGAL.contactEmail;

  return (
    <div className="landing flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:shadow-md">
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b bg-background">
        <div className={cn(section, "flex h-14 items-center gap-4")}>
          <Link href="/" className="flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <BrandMark className="size-4" />
            </span>
            <span className="text-lead font-semibold tracking-[-0.011em]">Sievr</span>
          </Link>
          <nav aria-label="Sections" className="ml-4 hidden items-center gap-1 md:flex">
            {NAV.map((item) => (
              <a key={item.href} href={item.href} className={ghost}>{item.label}</a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            {session ? (
              <Link href="/screener" className={cn(buttonVariants(), "h-9")}>Open the app</Link>
            ) : (
              <>
                <Link href="/login" className={cn(buttonVariants({ variant: "ghost" }), "h-9")}>Sign in</Link>
                <Link href="/login?trial=1" className={cn(buttonVariants(), "hidden h-9 sm:inline-flex")}>Start 7-day free trial</Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="flex-1">
        <section className="landing-ledger border-b">
          <div className={cn(section, "grid items-center gap-10 py-14 sm:py-20 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-14")}>
            <div className="motion-safe:animate-rise">
              <h1 className="text-[clamp(2.25rem,5.4vw,4rem)] font-semibold leading-[1.04] tracking-[-0.035em] text-balance">
                Every NSE and US stock, screened daily.
              </h1>
              <p className="mt-5 max-w-[46ch] text-lead text-muted-foreground sm:text-base">
                Filter the whole market, read results the evening companies file them, and see what management said on the earnings call. India and the US, one subscription.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Link href={session ? "/screener" : "/login?trial=1"} className={cn(buttonVariants({ size: "lg" }), "h-11 px-5")}>
                  {session ? "Open the app" : "Start 7-day free trial"}
                </Link>
                {session ? null : (
                  <Link href="/login" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 px-5")}>Sign in</Link>
                )}
              </div>
              <p className="mt-4 text-xs text-muted-foreground">Data for research and education, not investment advice.</p>
            </div>
            <div className="min-w-0 motion-safe:animate-rise" style={{ animationDelay: "120ms" }}>
              <HeroGrid />
            </div>
          </div>
        </section>

        <section id="product" className={cn(section, "scroll-mt-16 py-16 sm:py-24")}>
          <h2 className={h2}>Everything on one page per question</h2>
          <div className="mt-10">
            <ProductTour />
          </div>
        </section>

        <section id="features" className="border-y bg-card">
          <div className={cn(section, "py-16 sm:py-24")}>
            <h2 className={h2}>What you get</h2>
            <dl className="mt-10 grid gap-x-12 gap-y-8 md:grid-cols-2">
              {FEATURES.map(([name, body]) => (
                <div key={name} className="border-t pt-4">
                  <dt className="text-lead font-semibold">{name}</dt>
                  <dd className="mt-1.5 max-w-[52ch] text-sm leading-relaxed text-muted-foreground">{body}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section id="how" className={cn(section, "scroll-mt-16 py-16 sm:py-24")}>
          <h2 className={h2}>How it works</h2>
          <ol className="mt-10 grid gap-8 md:grid-cols-3">
            {STEPS.map(([name, body], i) => (
              <li key={name} className="relative border-t-2 border-foreground pt-4">
                <span className="sr-only">Step {i + 1}: </span>
                <h3 className="text-lead font-semibold">{name}</h3>
                <p className="mt-1.5 max-w-[40ch] text-sm leading-relaxed text-muted-foreground">{body}</p>
              </li>
            ))}
          </ol>
          <p className="mt-10 max-w-[64ch] text-sm text-muted-foreground">
            Sources: NSE and BSE filings, SEC EDGAR, Yahoo Finance prices. Daily measurements update after each close; live prices are indicative and may be delayed.
          </p>
        </section>

        <section id="pricing" className="scroll-mt-16 border-y bg-card">
          <div className={cn(section, "py-16 sm:py-24")}>
            <h2 className={h2}>One subscription, both markets</h2>
            <p className="mt-3 text-sm text-muted-foreground">Start with 7 days free. The plans below are read live from our billing records.</p>
            <div className="mt-10">
              <Suspense fallback={<div className="panel h-72 motion-safe:animate-pulse" aria-hidden />}>
                <LandingPricing />
              </Suspense>
            </div>
          </div>
        </section>

        <section id="faq" className={cn(section, "scroll-mt-16 py-16 sm:py-24")}>
          <h2 className={h2}>Questions</h2>
          <div className="mt-8 max-w-3xl divide-y border-y">
            {FAQ.map(([q, a]) => (
              <details key={q} className="group py-4">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded text-lead font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                  {q}
                  <span aria-hidden className="text-muted-foreground transition-transform group-open:rotate-45">+</span>
                </summary>
                <p className="mt-3 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">{a}</p>
              </details>
            ))}
          </div>
        </section>

        <section id="about" className="border-t bg-card">
          <div className={cn(section, "grid gap-6 py-16 sm:py-24 md:grid-cols-2")}>
            <h2 className={h2}>Built by one person, for people who read filings</h2>
            <p className="max-w-[56ch] text-sm leading-relaxed text-muted-foreground">
              Sievr is made and run by {LEGAL.operator}, {LEGAL.operatorForm}. It started as a personal screener for reading results and calls faster, and it stays small on purpose: a few pages, each doing one job well. Mistakes in the data are fixed when reported.
            </p>
          </div>
        </section>

        <section className="border-t">
          <div className={cn(section, "flex flex-col items-start gap-5 py-16 sm:py-20")}>
            <h2 className={h2}>Try it on this week&apos;s results</h2>
            <div className="flex flex-wrap gap-3">
              <Link href={session ? "/screener" : "/login?trial=1"} className={cn(buttonVariants({ size: "lg" }), "h-11 px-5")}>
                {session ? "Open the app" : "Start 7-day free trial"}
              </Link>
              {session ? null : <Link href="/login" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 px-5")}>Sign in</Link>}
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t bg-card">
        <div className={cn(section, "py-10")}>
          <nav aria-label="Legal" className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">
            {LEGAL_PAGES.map((page) => (
              <Link key={page.href} href={page.href} className="hover:text-foreground hover:underline">{page.label}</Link>
            ))}
            <Link href="/pricing" className="hover:text-foreground hover:underline">Pricing</Link>
            {contact ? <a href={`mailto:${contact}`} className="hover:text-foreground hover:underline">Contact: {contact}</a> : null}
          </nav>
          <p className="mt-6 text-xs text-muted-foreground">
            Data for research and education, not investment advice. © {new Date().getFullYear()} {LEGAL.service}.
          </p>
        </div>
      </footer>
    </div>
  );
}
