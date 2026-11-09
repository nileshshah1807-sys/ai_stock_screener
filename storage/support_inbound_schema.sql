-- ---------------------------------------------------------------------
-- support_inbound_emails: one row per email Resend received for the support
-- address that Cupel has turned into a JSM ticket (dashboard/lib/support-inbound.mjs).
-- The insert is the claim: Resend retries a webhook, and only the call whose
-- insert lands makes the ticket. Service role only; viewers can read nothing.
-- Apply by hand.
-- ---------------------------------------------------------------------
create table if not exists support_inbound_emails (
    email_id text primary key,
    received_at timestamptz not null default now()
);
alter table support_inbound_emails enable row level security;
revoke all on support_inbound_emails from anon, authenticated;
