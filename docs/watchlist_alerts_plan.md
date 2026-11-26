# Watchlist alert email — plan

Status: proposed, 26 Nov 2026. Nothing built. Item I1 of
[engagement_psychology.md](engagement_psychology.md).

## What it does

When a company on one of your watchlists files results or gets a call transcript,
you get an email: "RELIANCE filed Q2 FY27 results · TCS earnings call transcript".
It lists the facts the bell already shows and links to each stock. Today those
events only reach you if you have the site open (`market_events` → the bell).

## Where it runs (Worker CPU: none)

A Node script run as a GitHub Actions step, right after each
`python -m workers.market_events` step (quarterly-filings, financial-statements,
call-recordings). Nothing runs in the dashboard Worker except one tiny
unsubscribe route that bypasses Next (see below). Node rather than Python because
the email's template (`lib/customer-email.mjs`) and the event wording
(`lib/notifications.mjs`: `describeEvent`, `dedupeEvents`, `groupBySymbol`) are
already JS. One owner each, no second copy.

## Pieces

1. **`storage/watchlist_alerts_schema.sql`** (applied by hand)
   - `alert_settings (user_id, market, enabled bool default true, sent_through timestamptz, sent_today int, day date)`,
     PK `(user_id, market)`. Owner can read and update `enabled` (RLS like
     `notification_reads`); only the service role writes the cursor.
   - Pull the access rule out of `custom_access_token_hook` into
     `plan_for(uid uuid, mail text) returns (plan text, until_at timestamptz)`;
     the hook calls it, so "who has access" stays in one function.
   - `alert_recipients(p_market text)` (service role only): each user with
     access, alerts not off, and at least one watchlist in the market →
     `user_id, email, symbols text[], sent_through, sent_today, day`.
2. **`dashboard/lib/watchlist-alerts.mjs`** (pure, `node:test`). Decides who gets what:
   - events with `detected_at > sent_through`, not `baseline`, symbol in the
     user's watchlists, deduped (`dedupeEvents`);
   - **first sighting**: no `alert_settings` row → the cursor is set to now and
     nothing is sent, so a new user is never sent the last 180 days at once
     (same idea as `market_events`' baseline);
   - **cap**: at most `MAX_ALERTS_PER_DAY` emails a user a market-local day
     (proposed 3). Over the cap, events wait; the cursor has not moved past
     them, so the next allowed run sends them together;
   - the email body: one line per stock (`groupBySymbol` + `describeEvent`),
     newest first, at most 20 lines plus "and N more".
3. **`lib/customer-email.mjs`**: a `watchlist_alert` kind whose content is a
   list rather than two paragraphs; same layout, a `List-Unsubscribe` +
   `List-Unsubscribe-Post: List-Unsubscribe=One-Click` header (Gmail and Yahoo
   require it of bulk senders), and an unsubscribe link in the footer.
   No ratings, scores or buy/sell words, as for every Cupel email.
4. **`dashboard/scripts/watchlist-alerts.mjs`**: `--market NSE|US [--dry-run]`.
   Reads `alert_recipients` and the recent `market_events` with the service
   role, asks the lib, and for each email **moves the cursor first, then sends**
   (an idempotency key of `user/market/sent_through` to Resend). A failed send
   puts the cursor back, as `sendOnce` does today. No `RESEND_API_KEY`: logs and
   exits 0. Never fails the workflow.
5. **Unsubscribe**: `/api/alerts/unsubscribe?u=…&m=…&sig=…`, an HMAC of
   `(user, market)` with a new `ALERTS_SIGNING_SECRET`. Answered in
   `dashboard/worker.mjs` before Next loads (as `/api/objects` is): verify the
   signature, set `enabled = false`, return a one-line page. A GET shows a
   confirm button; the POST (and the one-click header) does the write, so a
   mail scanner opening links cannot unsubscribe anyone.
6. **Account page**: one "Email me when my watchlist stocks report" switch per
   market, reading and writing `alert_settings` from the browser under RLS.
   The rule (default on, which market) sits in the lib, tested there.

## Tests

- `lib/watchlist-alerts.test.mjs`: first sighting sends nothing; only watchlist
  symbols; baseline events never sent; the cap holds and the waiting events go
  in the next email; the US/NSE same-ticker case (TCS) never crosses markets;
  20-line truncation.
- `lib/customer-email.test.mjs`: the new kind's text and HTML, the escaping of
  company names, the unsubscribe header.
- `lib/unsubscribe.test.mjs`: a good signature passes, a changed user or market
  fails, GET does not write.
- `tests/`: the `plan_for` extraction leaves the hook's claims unchanged (run
  the existing billing hook tests).

## Before turning it on

- **Resend's free plan sends 100 emails a day / 3,000 a month.** At the cap of
  3, that is ~33 alerted users on a busy results day. Check the account's plan
  before switching it on for everyone.
- The `cupel.in` sending domain needs SPF/DKIM/DMARC in place (it already sends
  billing mail, so probably done; confirm DMARC exists).
- Switch: `WATCHLIST_ALERTS_ENABLED` repository variable, off until the schema
  is applied, as the other optional steps are.

## Decisions for the owner

1. **On by default or opt-in?** Proposed: on for anyone with a watchlist, with
   one-click unsubscribe in every email and a switch on the account page. An
   alert about stocks someone chose to watch is a service message, not
   marketing, but they must be able to stop it in one click.
2. **Timing: as it happens or once a day?** Proposed: as it happens (each
   15-minute filings run), capped at 3 a day per user. A daily evening digest
   is simpler and quieter but loses "just filed".

## Left out of v1

Push notifications (needs a service worker and a subscription store), the
results' headline numbers in the email (revenue and profit YoY from
`quarterly_filings`; a natural v2), and per-watchlist or per-kind settings.
