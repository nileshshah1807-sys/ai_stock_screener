# Why people come back: the psychology, and what Cupel does with it

Source: App Breakdown, "How to design an app SO addictive people cant stop using
it" (YouTube, 15 min, watched 26 Nov 2026). The figures below are the video's own
claims, not checked against the original studies.

Status: notes and a backlog. Done on `feat/no-dead-ends` (26 Nov 2026): D2, D3, D6, D10, D11, D14, I2, P2; D4, D5 and D12 turned out to be handled already. The alert email has its own
plan: [watchlist_alerts_plan.md](watchlist_alerts_plan.md).

---

## Part 1 — The psychology in the video

The video's framework has six steps. The first three **get people in**; the last
three **keep them**.

### 1. The Itch: triggers, external then internal
- **Source:** Nir Eyal, *Hooked*.
- **External triggers** are notifications, red badges and emails.
  **Internal triggers** are feelings: boredom, curiosity, worry about falling behind.
- Most opens come from the feeling, not the notification. "Boredom is the
  notification" for TikTok.
- An app fails when it never ties itself to the feeling. A meditation app is
  forgotten by day 3 although the stress is still there.
- Good apps **start with external triggers and, over time, attach themselves
  to the feeling.**
- Write alerts in the user's terms, not the company's. A dating app says
  "someone liked you", never "keep using our app". "We miss you" is corporate
  speak.
- **Do:** name the feeling your app answers. Write notifications that speak to
  it. Send them at the moment the feeling arises, like a commute app reminding
  you on the commute.

### 2. The Lazy Thumb: make the core action effortless
- **Source:** BJ Fogg, Stanford Behavior Design Lab.
- Motivation rises and falls through the day and you can't control it. You
  *can* control how easy the action is, so make it doable even on a
  low-motivation moment.
- **Example:** a calorie app where logging food takes a scroll, a menu and
  typing, against Cal AI's one photo. Cal AI got 15M downloads in 2 years.
- TikTok is one swipe, Tinder one swipe, Duolingo one big button at the bottom.
- **Do:**
  - Name the core action and count its steps, then cut ruthlessly toward one.
  - Make its button the biggest thing on the screen, within thumb reach,
    since about half of users hold the phone one-handed.
  - **Lower the bar for "done".** Duolingo counted a streak for one lesson
    instead of the full daily goal, and retention rose 3.3%.

### 3. The Paved Path: defaults decide
- **Source:** the 2003 European organ-donation study. Where you must opt in,
  about 23% donate; where you must opt out, about 86%. It is the same
  decision; only the default differs.
- Leaving a default takes effort, so people stay on it, even for a decision
  that big and much more for a button choice.
- TikTok is already playing. Duolingo lights up the next lesson. Tinder just
  shows the next person.
- **Do:**
  - The core action is the first thing seen on open: no menu, no choice.
  - List every decision you make users take and give each one a default
    that is good for both the user and you.

### 4. The Slot Machine: variable reward
- **Source:** B.F. Skinner's pigeons (1950s). Pigeons rewarded at random kept
  pecking long after the food stopped. Pigeons rewarded every time quit fast.
- Tinder's co-founder credits this study for the swipe. TikTok's leaked
  internal documents (Kentucky lawsuit, 2024) name a "habit moment" at about
  260 videos.
- Predictable rewards go stale: the tenth badge means nothing.
- **Do:** find your real reward. Vary when it comes and how big it is, but
  make it come often.

### 5. The Bottomless Pit: remove stopping cues
- **Source:** Aza Raskin, who invented infinite scroll and estimates it wastes
  100,000 human lifetimes a day.
- Stopping cues make the brain ask "should I stop?": the end of a page, the
  end of a video, an empty search, an error.
- Most apps are accidentally designed to be left. Every dead end is an exit.
- Duolingo's biggest button after a lesson is "next lesson". Netflix
  autoplays the next episode.
- **Do:** list every dead end (list ends, empty searches, error states) and
  make each one lead somewhere.

### 6. The Piggy Bank: stored value
- Netflix says its recommendations save it $1B a year. Leaving means teaching
  a new service your taste from scratch.
- Every use leaves something behind (taste, playlists, friends), so leaving
  costs more the more you used it.
- The test: **"If someone uninstalls it today, do they lose anything?"** If
  not, they won't come back.
- **Do:** treat every search, click and input as a signal of what people came
  for, and give them more of it. Let them build something (progress,
  personalisation) they know they would lose.

---

## Part 2 — What this means for Cupel

### Our guardrail first
Cupel is investment research. We want people to come back **to be informed**,
not to trade more. That rules out three of the video's levers in their raw form:

- **No manufactured variable rewards:** no random badges, confetti or "mystery"
  picks. Variable reward pushes people to act more often, and in markets that
  means overtrading. It would also look like advice we are not registered to
  give (SEBI), and the verdict is deliberately hidden.
- **No infinite feed of stocks** and no autoplay into the next idea. We remove
  *dead ends* (places that strand you) but keep natural ends.
- **No streaks or guilt.** A streak for checking a stock app rewards
  compulsion, not judgement.
- Everything else (triggers, effortless core actions, good defaults, no dead
  ends, stored value) fits Cupel well and serves the user.

House rules still apply: **no explainer copy** (a nudge is a link or button
with a short label, not a sentence), and **static first** (nothing new runs
per request in the Worker).

### 1. The Itch → "Did my stock just report? What did management say?"

**Our internal triggers:** curiosity and anxiety about a company you own or
watch, at moments we can predict:
- the evening a company files results (NSE filings come mostly after 15:30 IST);
- the evening of its earnings call;
- the day before a result is due;
- a sharp move in a held name;
- the market close.

**What we have:** the bell and notifications page (results and transcript
events, scoped to your watchlists), the home page's "Since" card and
watchlist-today card.

**The gap:** every trigger lives *inside* the site. Nothing reaches you outside it.

| # | Implement | Effort | Notes |
|---|---|---|---|
| I1 | **Watchlist alert email** ("RELIANCE filed Q2 FY27 results") | M | Planned: [watchlist_alerts_plan.md](watchlist_alerts_plan.md). The single biggest lever. |
| I2 ✅ | **Unread count in the browser tab title**, e.g. `(3) Cupel` | S | Uses the bell's existing count; a badge you see while in other tabs. Browser only, no Worker cost. |
| I3 | **"Results tomorrow" line in the alert email** for watchlist stocks with `next_result_date` = tomorrow | S, after I1 | `upcoming_events` already has the date. It turns the email into the thing you check *before* the result too. |
| I4 | Alert wording in the user's terms: "TCS filed its results", never "New activity on Cupel" | — | A rule for I1 and every later alert. |
| I5 | Web push (PWA) | L | Later: needs a service worker and subscription storage. Email first. |

### 2. The Lazy Thumb → the core actions, counted

Cupel's core actions:
1. **"What happened to my stocks?"**
2. **"Add this stock to a watchlist"**
3. **"Look up a stock"**

| # | Implement | Effort | Notes |
|---|---|---|---|
| L1 | **Count the taps** for each of the three, on a phone, from a cold open | S | Not measured yet. Goal: one tap from home for 1 and 2; one tap + typing for 3. |
| L2 | Home opens on the watchlist-today card above everything else for anyone with a watchlist | S | Check `HERO_CARDS` / `cardsFor` in `lib/home.mjs`; the rule lives there and is tested there. |
| L3 | One-tap watch from every row (screener, results, concalls, sector and index members), not just the stock page | S–M | `quick-watch` exists on home; reuse it. |
| L4 | **Lower the bar for "done"**: reading the one-line result summary *is* a complete visit | S | The results card's headline (revenue and profit YoY) visible without opening the stock page. |

### 3. The Paved Path → defaults for every choice

| # | Implement | Effort | Notes |
|---|---|---|---|
| P1 | **List every decision** a new viewer faces (market, screener view, sort, results quarter and filters, concalls filter, watchlist name) and write down its default | S | Audit only. Most probably have one; the point is to check. |
| P2 ✅ | **First watchlist made for you**: on a new viewer's first add, create "My watchlist" silently instead of asking for a name | S | Organ-donation logic: the name prompt is an opt-in wall. |
| P3 | **Search opens on suggestions before you type**: your watchlist, recent stock pages, today's results | S–M | The picker (`components/screener/stock-picker.tsx`) shows nothing until you type. |
| P4 | Results and Concalls default to "My watchlists" when you have one, "All" otherwise | S | Likely partly there (the empty-state copy mentions watchlists); confirm the default. |

### 4. The Slot Machine → show the real variety, invent none

The reward on Cupel is **news about your companies**, and it is already
variable: some evenings three results, some nothing. We don't add randomness;
we make the real variety visible at a glance.

| # | Implement | Effort | Notes |
|---|---|---|---|
| S1 | The "Since your last visit" card leads the home page when it has something: "3 results · 1 call · 2 big moves" | S | `SinceCard` exists; this is ordering and a count line. |
| S2 | A result's surprise as a short label beside it (profit +38% YoY, margin up 2 pts) | M | Facts from `quarterly_filings`, no rating or buy/sell words. |
| S3 ✅ | **The home page moves while the market does**: each index tile draws today's line (five-minute levels, the previous close dashed, the last point beating while open) in place of the month, and the day's biggest index movers glide past beneath the tiles | M | Lines: `live/{MARKET}/intraday.json`, written by the live-quotes worker, read in the browser through `/api/objects`. Ticker: the live movers the Top movers card already reads. No server work per request. |

### 5. The Bottomless Pit → the dead-end audit

Every place below currently ends the visit. Each should offer a next step:
a button or link, not a sentence.

| # | Where | Today | Lead them to | Effort |
|---|---|---|---|---|
| D1 | **Stock search, no match**: [stock-picker.tsx:313](../dashboard/components/screener/stock-picker.tsx) | "No match for X." | Closest names (typo-tolerant); the search index already has every symbol and name | S–M |
| D2 ✅ | **Any bad URL**: no `not-found.tsx` anywhere in `app/` | Next's default 404 | A Cupel 404 with the search box, home and the watchlist; a stock that is gone (`stocks/[symbol]/page.tsx:281,288`) also shows its sector page | S |
| D3 ✅ | **Screener, no stocks match**: [screener-table.tsx:81](../dashboard/components/screener/screener-table.tsx) | Text telling you to widen filters | A **Clear filters** button, and "Remove *X* → 42 stocks" for the filter that removes the most | S / M |
| D4 (already there) | **Results, nothing matches**: [results/page.tsx:333-338](../dashboard/app/(app)/[market]/(tools)/results/page.tsx) | "No results match…" / "No results filed for Q yet." | Clear-search button; for an empty quarter, a link to the previous quarter and to what is lined up (`upcoming_events`) | S |
| D5 (already there) | **Concalls, none for your watchlists**: [concalls/page.tsx:147-152](../dashboard/app/(app)/[market]/(tools)/concalls/page.tsx) | "No recent calls for the companies on your watchlists." | Your watchlist's *upcoming* calls, and a "Show all calls" button | S |
| D6 ✅ (page) | **Bell and notifications, nothing new**: [bell.tsx:126](../dashboard/components/notifications/bell.tsx), [notifications/page.tsx:109](../dashboard/app/(app)/[market]/notifications/page.tsx) | "Nothing new…" | What is next for your watchlist: "INFY results 28 Nov · HDFCBANK call 2 Dec" | S |
| D7 | **No watchlists / empty watchlist**: [watchlists/page.tsx:134,141,171](../dashboard/app/(app)/[market]/watchlists/page.tsx) | Empty-state title | One-tap adds: the largest companies, today's results, the stocks you recently opened | S–M |
| D8 | **Lined-up sheet, none match**: [upcoming-sheet.tsx:201](../dashboard/components/upcoming/upcoming-sheet.tsx) | "No results are lined up." | The next dated items beyond the window | S |
| D9 | **IPOs, none open**: [ipos/page.tsx:202](../dashboard/app/(app)/[market]/(tools)/ipos/page.tsx) | "No issue is bidding or announced right now." | Recent listings and how they did | S |
| D10 ✅ | **Index or sector members, no match**: [member-table.tsx:82](../dashboard/components/screener/member-table.tsx) | "No X matches…" | Clear-search; "search all stocks" carrying the term | S |
| D11 ✅ | **Results analysis, no results**: [results/analysis/page.tsx:225](../dashboard/app/(app)/[market]/(tools)/results/analysis/page.tsx) | "No results for these filters." | Clear filters | S |
| D12 (not a dead end) | **Screener's last page**: [pagination.tsx:37](../dashboard/components/screener/pagination.tsx) | "No results" | Clear filters / back to page 1 | S |
| D13 | **The end of a stock page** opened from a list (watchlist, screener, results) | The page ends (sector peers is the only way on) | **Next in your list → TCS**: Duolingo's "next lesson", for going through your watchlist after results | M |
| D14 ✅ | **Error boundary**: only `(market)/error.tsx` exists | Next's default error | A retry button and a way home on every route group | S |

Corrections after reading the code closely: Results and Concalls already offer
"Clear search and filters" whenever a search, a filter or a watchlist scope is on
(a watchlist scope counts as a filter there), so D4 and D5 needed nothing. The
screener's "No results" (D12) is the pager's count beside the grid, not a page
of its own. The bell's empty panel already ends in "See all notifications"; the
notifications page now offers "Show all of {market}" or "Clear filters". The
home page's quick watch already made a first list on the spot; P2 brings the
same one tap to the stock page's Watch button.

Kept as they are (a true "nothing", where a link would be noise): stock-page
evidence like "No documents yet", "No earlier call to compare with", and the
admin and billing states.

### 6. The Piggy Bank → what someone leaves behind on Cupel

**What we have:**
- watchlists;
- saved screener views (up to 50, moving to the account);
- "Your score" weights;
- the read state of notifications.

Someone who leaves loses these, which is good. They are also invisible: nothing
says "you have built this".

| # | Implement | Effort | Notes |
|---|---|---|---|
| B1 | **Watchlist notes**: `watchlist_items.note` (280 chars) is in the schema, but `lib/watchlists.ts` never reads it | S–M | "Why I watch this" beside the stock and on its page: the most personal thing we could hold. |
| B2 | **Recently viewed stocks** (browser storage first, account later) | S | Feeds P3 and D1/D7, so it pays three times. |
| B3 | Your score and saved views shown as yours on home ("Your views: Quality compounders · 12 new matches") | M | Saved views become a reason to come back, not just a setting. |
| B4 | **Measure the habit moment** | M | There is no product analytics in the dashboard today. Before guessing ours (say, a watchlist of 5+ stocks that has received its first result event), count a few first-party events: watchlist created, stock added, alert opened. Privacy policy and consent come first; no third-party tracker. |

---

## Suggested order

1. **Quick wins (S), one PR:** D2, D3, D4, D5, D6, D11, D12, D14, I2, P2.
   These are mostly empty-state buttons and links; each rule goes in a
   `lib/*.mjs` function with a test, per the house rule.
2. **Alerts:** I1, then I3 (the plan is written).
3. **Personal layer:** B2, then P3, D1 and D7 built on it; B1 notes.
4. **Measure, then tune:** L1 tap counts, P1 defaults audit, B4 events.
5. **Later:** D13 next-in-list, S2 surprise labels, B3, I5 web push.
