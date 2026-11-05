-- =====================================================================
-- Self-serve access: plans, subscriptions, and access carried in the JWT
-- =====================================================================
--
-- Anyone may sign up and gets a 7-day full trial with no card; after it a paid
-- Razorpay subscription is needed. One plan, both markets. The price is DATA
-- (plans.amount_paise), never code. Ratings stay admin-only whatever the plan
-- (rating_access_schema.sql reads dashboard_is_admin(), untouched here).
--
-- Access is read from the signed token, not from a table, on every request
-- (docs/commercialisation_readiness.md s.4.1): a custom access token hook puts
--   plan         admin | allowlist | trial | <plans.id> | none
--   access_until epoch seconds (absent for admin and allowlist)
-- into the JWT when it is issued. A change (payment, cancellation, a revoked
-- invite) reaches a signed-in user at the next token refresh, within the
-- token's lifetime.
--
-- Apply by hand, in order, after storage/dashboard_schema.sql:
--   1. psql "$SUPABASE_DB_URL" -f storage/billing_schema.sql   (safe to re-run)
--   2. Supabase dashboard -> Authentication -> Hooks -> Custom Access Token:
--      choose public.custom_access_token_hook.
--   3. Insert the plan (see the end of this file), with the Razorpay plan id.
-- Until step 2 a token has no `plan` claim and dashboard_has_access() falls
-- back to the allowlist table, so existing users keep access throughout.

-- ---------------------------------------------------------------------
-- plans: what can be bought. Readable by anyone (the pricing page).
-- ---------------------------------------------------------------------
create table if not exists plans (
    id text primary key,
    name text not null,
    amount_paise integer not null check (amount_paise >= 0),
    period text not null check (period in ('monthly', 'yearly')),
    -- The plan created in the Razorpay dashboard (plan_...). Null until it is.
    razorpay_plan_id text,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    -- An introductory offer off amount_paise (a Razorpay offer, not a second
    -- plan): open until offer_ends_at or until offer_limit subscribers have
    -- set the plan up, whichever comes first. All data, none of it code.
    offer_name text,
    offer_amount_paise integer check (offer_amount_paise >= 0),
    offer_ends_at timestamptz,
    offer_limit integer,
    razorpay_offer_id text
);
alter table plans add column if not exists offer_name text;
alter table plans add column if not exists offer_amount_paise integer;
alter table plans add column if not exists offer_ends_at timestamptz;
alter table plans add column if not exists offer_limit integer;
alter table plans add column if not exists razorpay_offer_id text;

alter table plans enable row level security;

drop policy if exists plans_read on plans;
create policy plans_read on plans for select to anon, authenticated using (active);

revoke all on plans from anon, authenticated;
grant select (id, name, amount_paise, period, active, offer_name, offer_amount_paise, offer_ends_at, offer_limit)
    on plans to anon, authenticated;

-- ---------------------------------------------------------------------
-- subscriptions: one row per user, written by the sign-up trigger and the
-- Razorpay webhook (service role). A user reads only their own row.
-- ---------------------------------------------------------------------
create table if not exists subscriptions (
    user_id uuid primary key references auth.users (id) on delete cascade,
    plan_id text references plans (id),
    status text not null default 'trialing'
        check (status in ('trialing', 'active', 'past_due', 'cancelled', 'expired')),
    trial_ends_at timestamptz,
    -- The end of the period paid for (Razorpay's current_end); a cancelled or
    -- unpaid subscription keeps access until then.
    current_period_end timestamptz,
    razorpay_subscription_id text unique,
    -- The last Razorpay event applied: an older or repeated event is ignored.
    last_event_id text,
    last_event_at timestamptz,
    -- Set when the user asks to delete their account; a person acts on it.
    delete_requested_at timestamptz,
    updated_at timestamptz not null default now()
);
alter table subscriptions add column if not exists delete_requested_at timestamptz;

alter table subscriptions enable row level security;

drop policy if exists subscriptions_self_read on subscriptions;
create policy subscriptions_self_read
    on subscriptions for select to authenticated
    using (user_id = (select auth.uid()));

revoke all on subscriptions from anon, authenticated;
grant select (user_id, plan_id, status, trial_ends_at, current_period_end, updated_at)
    on subscriptions to authenticated;

-- The trial starts when the user is first created.
create or replace function billing_start_trial()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.subscriptions (user_id, status, trial_ends_at)
    values (new.id, 'trialing', now() + interval '7 days')
    on conflict (user_id) do nothing;
    return new;
end;
$$;

revoke all on function billing_start_trial() from public, anon, authenticated;

drop trigger if exists billing_start_trial_on_signup on auth.users;
create trigger billing_start_trial_on_signup
    after insert on auth.users
    for each row execute function billing_start_trial();

-- ---------------------------------------------------------------------
-- The access token hook. Runs as supabase_auth_admin each time a token is
-- issued. Order: admin, then the allowlist (existing users keep access with no
-- expiry), then the subscription.
--   trialing   -> plan 'trial',   access until trial_ends_at
--   active     -> plan <plan id>, until current_period_end
--   past_due / cancelled -> still until current_period_end (paid for)
--   expired, or nothing -> plan 'none', no access_until
-- ---------------------------------------------------------------------
create or replace function custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
declare
    claims jsonb := coalesce(event -> 'claims', '{}'::jsonb);
    uid uuid := (event ->> 'user_id')::uuid;
    mail text := lower(coalesce(claims ->> 'email', ''));
    member text;
    sub subscriptions%rowtype;
    until_at timestamptz;
    plan_claim text := 'none';
begin
    select a.role into member from dashboard_allowlist a where lower(a.email) = mail;
    if member = 'admin' then
        plan_claim := 'admin';
    elsif member is not null then
        plan_claim := 'allowlist';
    else
        select * into sub from subscriptions s where s.user_id = uid;
        if found then
            until_at := case sub.status
                when 'trialing' then sub.trial_ends_at
                when 'expired' then null
                else sub.current_period_end
            end;
            if until_at is not null and until_at > now() then
                plan_claim := case sub.status when 'trialing' then 'trial' else coalesce(sub.plan_id, 'none') end;
            else
                until_at := null;
            end if;
        end if;
    end if;

    claims := claims || jsonb_build_object('plan', plan_claim);
    if until_at is not null and plan_claim not in ('none', 'admin', 'allowlist') then
        claims := claims || jsonb_build_object('access_until', floor(extract(epoch from until_at))::bigint);
    else
        claims := claims - 'access_until';
    end if;
    return jsonb_set(event, '{claims}', claims);
end;
$$;

grant usage on schema public to supabase_auth_admin;
grant execute on function custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function custom_access_token_hook(jsonb) from public, anon, authenticated;
grant select on dashboard_allowlist, subscriptions to supabase_auth_admin;

drop policy if exists dashboard_allowlist_auth_admin_read on dashboard_allowlist;
create policy dashboard_allowlist_auth_admin_read
    on dashboard_allowlist for select to supabase_auth_admin using (true);
drop policy if exists subscriptions_auth_admin_read on subscriptions;
create policy subscriptions_auth_admin_read
    on subscriptions for select to supabase_auth_admin using (true);

-- ---------------------------------------------------------------------
-- dashboard_has_access(): admin OR allowlisted OR trial/paid and not expired,
-- read from the token. A token issued before the hook was enabled has no
-- `plan` claim; it falls back to the allowlist table until it is refreshed
-- (shortcut: drop the fallback branch once every session has refreshed).
-- ---------------------------------------------------------------------
create or replace function dashboard_has_access()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select case
        when auth.jwt() ->> 'plan' is null then exists (
            select 1 from dashboard_allowlist a
            where lower(a.email) = lower(coalesce(auth.jwt() ->> 'email', ''))
        )
        when auth.jwt() ->> 'plan' in ('admin', 'allowlist') then true
        when auth.jwt() ->> 'plan' = 'none' then false
        else coalesce(auth.jwt() ->> 'access_until', '') ~ '^[0-9]+$'
             and (auth.jwt() ->> 'access_until')::bigint > floor(extract(epoch from now()))::bigint
    end;
$$;

-- Whether a plan's introductory offer is still open: before its end date and
-- with fewer than offer_limit subscribers (plan_id is set when the mandate is
-- authorised). The pricing page asks this rather than counting other users.
create or replace function plan_offer_open(p_plan text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select coalesce(
        p.offer_amount_paise is not null
        and (p.offer_ends_at is null or p.offer_ends_at > now())
        and (p.offer_limit is null or (select count(*) from subscriptions s where s.plan_id = p.id) < p.offer_limit),
        false)
    from plans p where p.id = p_plan and p.active;
$$;
revoke all on function plan_offer_open(text) from public;
grant execute on function plan_offer_open(text) to anon, authenticated;

-- ---------------------------------------------------------------------
-- The launch plan, as data (human decision 5 Nov 2026): one yearly plan,
-- Rs 999, both markets; early bird Rs 699 for the first year to the first 500
-- subscribers or until 31 Dec 2026. No monthly plan. Seeded without the Razorpay
-- ids: create the plan and the offer in the Razorpay dashboard, then
--   update plans set razorpay_plan_id = 'plan_...', razorpay_offer_id = 'offer_...' where id = 'pro';
-- Until then create-subscription answers no_active_plan. Change a price here.
-- ---------------------------------------------------------------------
insert into plans (id, name, amount_paise, period, offer_name, offer_amount_paise, offer_ends_at, offer_limit)
values ('pro', 'Winnow', 99900, 'yearly', 'Early bird', 69900, timestamptz '2026-12-31 23:59:59+05:30', 500)
on conflict (id) do nothing;
