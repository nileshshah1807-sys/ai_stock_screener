-- ---------------------------------------------------------------------
-- support_inbound_emails: one row per email Resend received for the support
-- address that Cupel has turned into a JSM ticket (dashboard/lib/support-inbound.mjs).
-- The insert is the claim: Resend retries a webhook, and only the call whose
-- insert lands makes the ticket. received_at is when it was claimed;
-- completed_at is set once the ticket exists (or the mail was dropped on
-- purpose). A claim with no completed_at older than 5 minutes is a timed-out
-- call and the next retry takes it over. Service role only; viewers can read nothing.
-- Apply by hand.
-- ---------------------------------------------------------------------
create table if not exists support_inbound_emails (
    email_id text primary key,
    received_at timestamptz not null default now(),
    completed_at timestamptz
);
alter table support_inbound_emails add column if not exists completed_at timestamptz;
alter table support_inbound_emails enable row level security;
revoke all on support_inbound_emails from anon, authenticated;
