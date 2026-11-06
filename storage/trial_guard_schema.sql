-- =====================================================================
-- Trial abuse guard: who has had a free trial, as salted hashes
-- =====================================================================
-- The sign-up trigger (billing_schema.sql) still grants the 7-day trial: it cannot
-- see the request. After sign-in the dashboard (lib/trial-guard.ts, service role)
-- compares the person's signals with earlier trials and, if a rule fires, sets the
-- subscription to 'expired' and stamps trial_denied_at. The rules live in
-- dashboard/lib/trial-guard.mjs.
--
-- Nothing raw is stored: ip_hash, device_hash and email_hash are HMAC-SHA256 under
-- the TRIAL_GUARD_SALT environment variable (set in Vercel by hand).
--
-- Apply by hand, after storage/billing_schema.sql:
--   psql "$SUPABASE_DB_URL" -f storage/trial_guard_schema.sql   (safe to re-run)

create table if not exists trial_signals (
    user_id uuid primary key references auth.users (id) on delete cascade,
    ip_hash text,
    device_hash text,
    email_hash text not null,
    granted boolean not null,
    reason text not null,
    created_at timestamptz not null default now()
);
create index if not exists trial_signals_ip on trial_signals (ip_hash) where granted;
create index if not exists trial_signals_device on trial_signals (device_hash) where granted;
create index if not exists trial_signals_email on trial_signals (email_hash) where granted;

-- Service role only: no policy, no grant.
alter table trial_signals enable row level security;
revoke all on trial_signals from anon, authenticated;

-- Set when the guard refused the trial; the pricing page and account card say why.
alter table subscriptions add column if not exists trial_denied_at timestamptz;
grant select (trial_denied_at) on subscriptions to authenticated;
