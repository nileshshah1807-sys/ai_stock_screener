import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { BrandMark } from "@/components/brand-mark";
import { CuratedRanking } from "@/components/landing/curated-ranking";
import { CallsBlock, StageBlock } from "@/components/landing/feature-blocks";
import { HeroGrid } from "@/components/landing/hero-grid";
import { LandingMotion } from "@/components/landing/landing-motion";
import { LandingPricing } from "@/components/landing/landing-pricing";
import { ProductTour } from "@/components/landing/product-tour";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { getSession } from "@/lib/auth";
import { LEGAL, LEGAL_PAGES } from "@/lib/legal";
import { cn } from "@/lib/utils";

const TITLE = "Cupel: daily screener for NSE and US stocks";
const DESCRIPTION =
  "Screen NSE and US stocks, read quarterly results as companies file them, and follow what management said on earnings calls. Data for research and education, not investment advice.";

// The root layout is noindex for the signed-in app; the landing page is the
// one public page meant to be found.
export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  openGraph: { title: TITLE, description: DESCRIPTION, siteName: "Cupel", type: "website" },
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
  ["Earnings calls, read for you", "Management's tone in a word and the statement that moved it most, for calls we have a transcript or recording of."],
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
  ["Is this investment advice?", "No. Cupel shows data and measurements for research and education. It does not tell you what to buy or sell, and nothing on it is a recommendation. Read the Disclaimer for the details."],
  ["Which markets are covered?", "India (NSE, plus companies listed on BSE alone) and the US, under one subscription."],
  ["Where does the data come from?", "Quarterly results and shareholding from the exchange's filings, US statements from SEC EDGAR, prices from Yahoo Finance. Live prices refresh about every five minutes in market hours and are indicative; the daily measurements update after the close."],
  ["How does the free trial work?", "Sign in with your email and get 7 days of full access. Subscribe from the pricing page when you want to carry on."],
  ["How do I pay, and can I cancel?", "Payments go through Razorpay by UPI or card, and the early-bird price uses UPI Autopay. Cancel any time from your account. A payment is refunded in full within 7 days; see the Refund policy."],
];

const ghost = "rounded-md px-2.5 py-2 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const X_URL = "https://x.com/ChirayuShah2103";
const X_LABEL = "@ChirayuShah2103 on X (opens in a new tab)";

function XIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-4 fill-current">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

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
        <section data-spotlight className="landing-ledger landing-clip landing-spot border-b">
          <div aria-hidden data-parallax="0.12" className="landing-dots" />
          <div aria-hidden data-parallax="0.4" className="landing-glow -right-28 top-4 size-[34rem]" />
          <div aria-hidden data-parallax="-0.25" className="landing-glow -bottom-32 -left-32 size-[24rem] opacity-60" />
          <div className={cn(section, "grid items-center gap-10 py-14 sm:py-20 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-14")}>
            <div className="motion-safe:animate-rise">
              <h1 className="text-[clamp(2.25rem,5.4vw,4rem)] font-semibold leading-[1.04] tracking-[-0.035em] text-balance">
                NSE and US stocks, screened daily.
              </h1>
              <p className="mt-5 max-w-[46ch] text-lead text-muted-foreground sm:text-base">
                A curated shortlist from the whole market, ranked daily on management guidance, value, momentum and risk, so there is far less to search and filter. Read results the evening companies file them. India and the US, one subscription.
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
              <div data-parallax="0.07">
                <HeroGrid />
              </div>
            </div>
          </div>
        </section>

        <section id="ranking" className={cn(section, "scroll-mt-16 border-b py-14 sm:py-20")}>
          <CuratedRanking />
        </section>

        <section id="calls" className={cn(section, "scroll-mt-16 py-14 sm:py-20")}>
          <CallsBlock />
        </section>

        <section id="stage" className="landing-clip scroll-mt-16 border-y bg-card">
          <div aria-hidden data-parallax="0.3" className="landing-glow -left-40 top-10 size-[30rem] opacity-50" />
          <div className={cn(section, "py-14 sm:py-20")}>
            <StageBlock />
          </div>
        </section>

        <section id="product" className={cn(section, "scroll-mt-16 py-14 sm:py-20")}>
          <h2 data-reveal className={h2}>Everything on one page per question</h2>
          <div className="mt-10">
            <ProductTour />
          </div>
        </section>

        <section id="features" className="border-y bg-card">
          <div className={cn(section, "grid gap-10 py-14 sm:py-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,2.2fr)]")}>
            <h2 data-reveal className={h2}>What you get</h2>
            <dl data-stagger className="grid gap-x-10 gap-y-7 md:grid-cols-2">
              {FEATURES.map(([name, body]) => (
                <div key={name} className="landing-feature border-t pt-4">
                  <dt className="text-lead font-semibold">{name}</dt>
                  <dd className="mt-1.5 max-w-[52ch] text-sm leading-relaxed text-muted-foreground">{body}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section id="how" className={cn(section, "scroll-mt-16 py-14 sm:py-20")}>
          <h2 data-reveal className={h2}>How it works</h2>
          <ol data-stagger className="mt-10 grid gap-8 md:grid-cols-3">
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
          <div className={cn(section, "py-14 sm:py-20")}>
            <h2 data-reveal className={h2}>One subscription, both markets</h2>
            <p className="mt-3 text-sm text-muted-foreground">Start with 7 days free. The plans below are read live from our billing records.</p>
            <div className="mt-10">
              <Suspense fallback={<div className="panel h-72 motion-safe:animate-pulse" aria-hidden />}>
                <LandingPricing />
              </Suspense>
            </div>
          </div>
        </section>

        <section id="faq" className={cn(section, "scroll-mt-16 py-14 sm:py-20")}>
          <h2 data-reveal className={h2}>Questions</h2>
          <div data-stagger className="mt-8 max-w-3xl divide-y border-y">
            {FAQ.map(([q, a]) => (
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

        <section id="about" className="border-t bg-card">
          <div className={cn(section, "grid gap-6 py-14 sm:py-20 md:grid-cols-2")}>
            <h2 data-reveal className={h2}>Built by one person, for people who read filings</h2>
            <div>
              <p className="max-w-[56ch] text-sm leading-relaxed text-muted-foreground">
              Cupel is made and run by {LEGAL.operator}, {LEGAL.operatorForm}. It started as a personal screener for reading results and calls faster, and it stays small on purpose: a few pages, each doing one job well. Mistakes in the data are fixed when reported.
              </p>
              <a href={X_URL} target="_blank" rel="me noopener" aria-label={X_LABEL} className="mt-4 flex w-fit items-center gap-2 rounded-md text-sm font-medium text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <XIcon /> @ChirayuShah2103 on X
              </a>
            </div>
          </div>
        </section>

        <section className="landing-mesh bg-primary text-primary-foreground">
          <div className={cn(section, "flex flex-col items-start gap-5 py-14 sm:py-20")}>
            <h2 data-reveal className={h2}>Try it on this week&apos;s results</h2>
            <div className="flex flex-wrap gap-3">
              <Link href={session ? "/screener" : "/login?trial=1"} className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 px-5")}>
                {session ? "Open the app" : "Start 7-day free trial"}
              </Link>
              {session ? null : <Link href="/login" className="inline-flex h-11 items-center rounded-md px-4 text-sm font-medium underline underline-offset-4 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Sign in</Link>}
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
            <a href={X_URL} target="_blank" rel="me noopener" aria-label={X_LABEL} className="inline-flex items-center gap-1.5 hover:text-foreground hover:underline">
              <XIcon /> X
            </a>
            {contact ? <a href={`mailto:${contact}`} className="hover:text-foreground hover:underline">Contact: {contact}</a> : null}
          </nav>
          <p className="mt-6 text-xs text-muted-foreground">
            Data for research and education, not investment advice. {LEGAL.service} is not a SEBI-registered investment adviser or research analyst. © {new Date().getFullYear()} {LEGAL.service}.
          </p>
        </div>
      </footer>
    </div>
  );
}
