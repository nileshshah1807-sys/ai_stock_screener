# Commercialisation readiness

- **Status:** in progress, see "Progress" below
- **Date:** 2026-11-04
- **Scope:** what stands between Cupel as it runs today (invite-only, two
  markets, scheduled GitHub Actions + Supabase + Vercel) and a paid product,
  plus a read path that holds 10,000 requests per second.

Legal points below are a checklist for counsel, not legal advice. Each one
needs a lawyer's sign-off before launch.

## Progress (2026-11-04)

Done:

- **§1.1, §1.3:** buy/sell ratings and the Returns page are admin-only.
  - Dashboard: redacted on the server (`dashboard/lib/ratings.mjs`, `isAdmin()`
    in `lib/auth.ts`); viewers see scores, ranks and stages.
  - Database: `storage/rating_access_schema.sql` adds `*_visible` views that
    null ratings for non-admins. It is **applied to production**, together
    with re-applied `market_breadth_schema.sql`, `live_quotes_schema.sql` and
    `returns_backfill_schema.sql`, and verified there as a real viewer and a
    real admin.
- **§1.7:** public `/terms`, `/privacy` and `/disclaimer` pages
  (`dashboard/app/(legal)/`), linked from the login page and the app footer.
- **§1.5:** the user confirms they own the code.
- **§1.4:** market-data licensing is deferred by decision.

Next, in this order:

1. ~~Merge PR #198 and deploy~~ (merged and live 4 Nov 2026).
2. ~~Apply `storage/rating_access_lockdown.sql`~~ (applied 4 Nov 2026, after
   the deploy). A viewer now gets "permission denied" on the three base tables,
   and sees 0 ratings through the views; an admin sees all; the service role
   keeps its grants.
3. Close the Storage gap. Since October the full row payload is a gzip object
   in the `market-data` bucket (`snapshot-payload/…`), ratings included, and
   `storage/market_data_storage.sql` lets any invited viewer read it. The
   dashboard redacts it on the server, but a viewer calling Storage with their
   own session can read it. One fix: the publisher writes the rating keys to a
   separate admin-only object.
4. Fill in the placeholders in `dashboard/lib/legal.ts` (address, contact and
   grievance emails, jurisdiction), then have a lawyer read the three pages.

Open, not started: company and GST registration (§1.6), §2 (sign-up, billing,
plans, email), §3 (ops), §4 (read scaling).

## 1. Blockers: do not charge money until these are settled

| # | Gap | Why it blocks | What closes it |
|---|-----|---------------|----------------|
| 1 | **SEBI Research Analyst registration (India)** | The product publishes `Rating` (Strong Buy / Buy / Hold), `Buy_Eligible` and a ranked list of Indian securities. Charging for that is research under the SEBI (Research Analysts) Regulations, 2014, amended in Dec 2024 and Nov 2025. "Not investment advice" in the footer does not change what the output is. | Register as an RA (individual or a company with a principal officer), or partner with a registered RA who signs off the output. Or ship the India product as a screener with no rating, no buy label and no rank, which counsel has to agree is not research. |
| 2 | **SEBI AI-use rules** | Since 2025 a regulated entity is responsible for what its AI/ML tools output and has to tell clients how far AI is used. The outlook score and Concalls stance are LLM output. | An AI-use disclosure on every rated surface, and a written review process for model output. |
| 3 | **Past-performance claims** | The Returns page shows model-portfolio returns. SEBI restricts how RAs advertise past performance (verification framework, 2025). | Hide Returns from paying Indian users until counsel clears it, or label it as an unverified simulation. |
| 4 | **Market data licences** | Prices and quote metadata come from Yahoo through `yfinance`, an unofficial client. Yahoo's terms allow personal use only. NSE and BSE data (bhavcopies, the filing index, shareholding, deals, index constituents) is scraped from exchange websites whose terms forbid commercial redistribution. Nifty and Sensex constituents and names are licensed by NSE Indices and Asia Index. | Licensed feeds. India: NSE Data & Analytics (or an authorised vendor such as TrueData, Global Datafeeds or Accelpix) for EOD/delayed prices and the filing feed, NSE Indices for constituents. US: Polygon, Intrinio, Tiingo or Nasdaq Data Link for prices. **SEC EDGAR is public and can be kept.** This is the largest recurring cost; get quotes first. |
| 5 | **Who owns the code** | 274 commits are authored as `Chirayu Shah/LGSI Cyber Security Unit`, which looks like an employer identity. An employment contract with an IP-assignment clause can give the employer a claim on work done on its time or hardware. Two other people (`Nilesh Shah`, `nileshshah1807-sys`) have about 50 commits, and the PRs merge from the `nileshshah1807-sys` GitHub account. The repo has no LICENSE file. | Check your employment contract (or get a written no-claim from the employer). Sign a founders' agreement and an IP assignment from every contributor to the company. Move the repo into a company-owned GitHub org. |
| 6 | **Company and tax** | Taking payments needs an entity, a bank account, and GST registration in India (digital services). US customers bring sales-tax questions. | Register a Pvt Ltd or LLP, GST, and a payment gateway merchant account. |
| 7 | **Terms, privacy, data protection** | No Terms of Service, Privacy Policy, refund policy or grievance officer exists. India's DPDP Act 2023 (rules notified Nov 2025, phased in) applies to user emails and watchlists. | ToS with a research disclaimer and limitation of liability, a Privacy Policy, a refund/cancellation policy (payment gateways require one), a grievance officer contact, cookie/consent notice, and data deletion on request. |

## 2. Product gaps for a paid self-serve service

| Area | Today | Needed |
|------|-------|--------|
| Sign-up | Invite-only: `shouldCreateUser: false` + `dashboard_allowlist` | Self-serve sign-up, email verification, a free trial |
| Billing | None | Razorpay (India, UPI/mandates) and/or Stripe (US). Webhooks write a `subscriptions` table, which drives access |
| Entitlements | `dashboard_has_access()` checks only membership | Plans (free / paid / per-market). Put the plan in the JWT (Supabase custom access token hook) so neither RLS nor the app needs a table read per request (see §4) |
| Email | Supabase built-in SMTP (a few messages an hour) | Custom SMTP (Resend, SES, Postmark) for magic links, receipts and alerts |
| Account | No settings page | Profile, plan, invoices, cancel, delete account |
| Admin | Supabase console | An admin view for users, plans, refunds and comps |
| Onboarding | None | First-run tour, methodology page (`docs/model_methodology.md` is the source) |
| Support | None | Help/FAQ, support email or chat, status page |
| Analytics | None | Product analytics (PostHog or Plausible) and in-app feedback/NPS |
| Mobile | Responsive web | Fine for launch; a PWA manifest is cheap |

## 3. Operations gaps

- **Error tracking and alerting:** no Sentry or equivalent in the dashboard or
  the workers. A failed 16:30 IST run is only visible through the staleness
  banner. Add error tracking and a failed-workflow alert to email or Slack.
- **Pipeline SLA:** production depends on GitHub Actions cron plus
  cron-job.org dispatches. Both are best-effort. For a paid product, document
  the publish SLA, alert when a run is late, and decide whether to move to a
  scheduler you control.
- **Fragile sources:** NSE and BSE scraping, the recording-page browser
  automation and Yahoo all break without notice. Licensed feeds (§1.4) remove
  most of this.
- **Database:** confirm the Supabase plan has daily backups and PITR. The
  tables applied "by hand" (`storage/*.sql`) need a migration runner so a new
  environment can be rebuilt.
- **Staging:** add a staging Supabase project and a Vercel preview that point
  at it. Today local runs read the production Supabase.
- **Region:** functions and the DB are in Tokyo (`hnd1`, `ap-northeast-1`).
  Indian users pay about 100 ms per round trip. Consider Mumbai (`bom1` +
  `ap-south-1`) when the DB moves.
- **Secrets:** rotate everything once the repo moves orgs. Check that git
  history holds no keys before granting new collaborators access.

## 4. Scaling the read path to 10,000 requests/second

### Where the load lands today

Every page is `force-dynamic` and reads Supabase **as the signed-in user**:

1. `getClaims()`: local JWT check (cheap).
2. `dashboard_allowlist` lookup in `requireAccess()`, plus the same lookup
   inside `dashboard_has_access()` in every RLS policy (once per statement).
3. Page reads: `getLatestRun`, `getSnapshotPage` (with `count: "exact"`),
   sectors, and the bell (`notification_reads` + a `market_events` count).

That is roughly 5–8 Postgres statements per page view. Nothing is cached
across users, although the data is the same for everyone: it changes once a
day at publish, and live quotes change every 5 minutes. At 10k page views/s
that is about 50–80k statements/s. A single Supabase instance does not serve
that, and Vercel function cost grows linearly with traffic.

*These figures are estimates from reading the code. Nothing was load-tested.*

### Target design: cache what is shared, compute only what is per-user

1. **Entitlement in the token, not a table.** A Supabase custom access token
   hook adds `plan` (and `markets`) to the JWT when it is issued. `requireAccess()`
   reads the claim. RLS uses `auth.jwt() ->> 'plan'`. The per-request allowlist
   read goes away. Revocation takes effect at the next token refresh (1 h
   default; shorten it if needed).
2. **Shared reads go through Next's data cache.** `getLatestRun`,
   `getSnapshotPage`, `getStock`, sectors, movers, indices, results and
   concalls are wrapped in `unstable_cache` / `"use cache"`, keyed by market,
   run date and filters, and tagged by market. The publisher (and the
   quarterly-filings worker) calls a revalidate endpoint for that tag when a
   run lands. This needs a **server-only reader credential** that is not the
   viewer's session, which reverses the README's "service-role key never
   reaches the app" rule. The safer form is a dedicated Postgres role that can
   only `SELECT` the shared read-model tables. **This is the decision that
   needs your approval.**
3. **Per-user data is loaded after render.** The bell, watchlist marks and
   notifications load in the browser after the page renders, the way live
   quotes already do. The shared page can then be cached whole.
4. **Pages cached at the edge.** Once 1–3 are in place, the shared pages can
   be ISR-rendered and served from Vercel's CDN. `proxy.ts` verifies the JWT
   and its `plan` claim before the cached response is served. Function
   invocations then scale with publishes, not with viewers.
5. **Live data.** Browser polling of `live_quotes` (≥30 s, `MIN_POLL_MS`) and
   the `live_market` / `live_breadth` RPCs hit Postgres per viewer. Have the
   live-quotes worker write one JSON snapshot per market to Storage or the
   CDN every 5 minutes, and have browsers fetch that file. The DB then sees
   one write per 5 minutes instead of one read per viewer per poll.
6. **Cheap wins whatever else is done:** `count: "estimated"` or a cached
   count for the screener grid, and add a Supavisor transaction-mode pooler
   URL for any direct Postgres access.

With 1–5 in place, almost all of the 10k RPS is CDN hits. Postgres handles
per-user writes, watchlists and the bell, which is a small fraction of traffic.

### Proving it

Write a k6 (or Grafana Cloud k6) script that signs in N test users and replays
screener, stock-page and market-page navigation. Run it against a **staging**
project, never production. Pass criterion: 10k RPS sustained for 10 minutes,
p95 < 300 ms, a CDN hit ratio above 95%, and Postgres CPU below 50%.

## 5. Reference: how WealthLab (wealthlab.in) is set up

Read on 2026-11-04 from its public pages and public JS only, without signing in.

- **Data vendor: not disclosed.** The browser talks only to WealthLab's own
  API (`apiv2.wealthlab.in`, nginx on Ubuntu, so a self-hosted server), which
  hides the upstream source. The disclaimer says only "stock exchanges (NSE,
  BSE) and market data vendors". No vendor name appears in the bundles. The
  only hits are TradingView (an invite-only Pine indicator and watchlist
  export) and Zerodha/Upstox (tradebook CSV import), neither of which is a
  data feed. Signed in (a trial account), every screen still loads its data
  only from `apiv2.wealthlab.in`: `/api/live-prices` (intraday quotes),
  `/api/stocks/{EX:SYM}/price-history`, `extended-fundamentals` ("UPD" date on
  the panel) and `announcements`. The chart is their own, not TradingView's
  hosted library. The one upstream source the page shows is BSE: filing links
  point straight at `bseindia.com/xml-data/corpfiling/AttachHis/…` PDFs.
  Intraday quotes mean they hold *some* live feed (a broker API or a vendor
  such as TrueData), but it is not visible from the browser.
- **Regulatory posture:** a sole proprietorship that states it is *not*
  SEBI-registered, calls itself a "data analytics platform for research and
  educational purposes", and presents Stage 2 / RS / "Alpha Edge" as
  "technical tools… NOT trading signals or recommendations". It publishes no
  Buy/Hold labels. That is the "screener without ratings" route from §1.1.
  Whether that wording holds up is a legal question, not a precedent.
- **Stack:** Razorpay (subscriptions, coupons, PDF invoices), Mixpanel + GTM
  analytics, Cloudflare in front, WhatsApp support, ToS / Privacy (DPDP Act) /
  Disclaimer pages, subscription-only access.

## 6. MiroFish

MiroFish (`666ghj/MiroFish`, AGPL-3.0) builds LLM personas from seed
documents and simulates how they would discuss a topic on simulated
Twitter/Reddit. Use it to rehearse positioning and pricing, for example "how
would Indian retail investors react to a ₹499/month screener with these
features?". Two limits:

- **It does not test the application.** It never opens the dashboard, clicks
  through it or measures load. Its feedback is synthetic opinion from an LLM,
  not user feedback. Real multi-user feedback needs a closed beta with
  in-app surveys (§2 Analytics). Multi-user load is the k6 test in §4.
- **It needs paid third-party accounts and sends your material to them:**
  `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME` (any OpenAI-compatible
  API; it warns of high token use and suggests under 40 rounds) and
  `ZEP_API_KEY` (Zep Cloud memory graph). The seed documents (product brief,
  pricing, methodology) are uploaded to both providers.

Setup (Python 3.11–3.12, Node 18+, `uv`): clone it outside this repo, copy
`.env.example` to `.env`, fill in the keys, run `npm run setup:all`, then
`npm run dev` (frontend :3000, backend :5001). Keep it out of this repo. AGPL
code linked into Cupel would force Cupel's source open.
