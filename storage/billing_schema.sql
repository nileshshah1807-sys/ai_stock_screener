-- =====================================================================
-- Self-serve access: plans, subscriptions, and access carried in the JWT
-- =====================================================================
--
-- Anyone may sign up and gets a 7-day full trial with no card; after it a paid
-- Razorpay subscription is needed. Two plans (yearly, monthly), both markets. The price is DATA
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
-- Whether the early-bird offer was applied to the subscription started at checkout
-- (null until one is started): the first charge is the offer or the plan price.
alter table subscriptions add column if not exists offer_applied boolean;
-- The Razorpay subscription an admin refunded and ended (billing_refund_end_access).
-- Access is refused while it is still the row's subscription, whatever a later
-- webhook says; a new checkout stores a new subscription id and so lifts it.
alter table subscriptions add column if not exists refunded_subscription_id text;

alter table subscriptions enable row level security;

drop policy if exists subscriptions_self_read on subscriptions;
create policy subscriptions_self_read
    on subscriptions for select to authenticated
    using (user_id = (select auth.uid()));

revoke all on subscriptions from anon, authenticated;
grant select (user_id, plan_id, status, trial_ends_at, current_period_end, offer_applied, updated_at)
    on subscriptions to authenticated;

-- Users that already exist have no trial: a row with status 'expired' gives them
-- somewhere for delete-request and checkout to write. Allowlisted users keep
-- access through the allowlist branch of the hook, whatever their row says.
insert into subscriptions (user_id, status)
select id, 'expired' from auth.users
on conflict (user_id) do nothing;

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
--   past_due / cancelled -> still until the later of current_period_end and
--                           trial_ends_at (cancelling in the trial keeps its days)
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
    uid uuid;
    mail text := lower(coalesce(claims ->> 'email', ''));
    member text;
    sub subscriptions%rowtype;
    until_at timestamptz;
    plan_claim text := 'none';
begin
    uid := (event ->> 'user_id')::uuid;  -- inside the handler's reach
    select a.role into member from dashboard_allowlist a where lower(a.email) = mail;
    if member = 'admin' then
        plan_claim := 'admin';
    elsif member is not null then
        plan_claim := 'allowlist';
    else
        select * into sub from subscriptions s where s.user_id = uid;
        if found then
            until_at := case sub.status
                when 'expired' then null
                else greatest(sub.current_period_end, sub.trial_ends_at)
            end;
            -- refunded and ended by an admin: no access, whatever the period end says
            if sub.refunded_subscription_id is not null
               and sub.refunded_subscription_id is not distinct from sub.razorpay_subscription_id then
                until_at := null;
            end if;
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
exception when others then
    raise warning 'token hook: %', sqlerrm;  -- visible in the Supabase auth log
    -- A failing hook would block every sign-in, admins included: hand the token
    -- back unchanged; dashboard_has_access() then uses the allowlist fallback.
    return event;
end;
$$;

grant usage on schema public to supabase_auth_admin;
grant execute on function custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function custom_access_token_hook(jsonb) from public, anon, authenticated;
-- security definer: it reads the tables as its owner, so supabase_auth_admin
-- needs no table grants or policies.
drop policy if exists dashboard_allowlist_auth_admin_read on dashboard_allowlist;
drop policy if exists subscriptions_auth_admin_read on subscriptions;
revoke select on dashboard_allowlist, subscriptions from supabase_auth_admin;

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
-- Applying a Razorpay event, atomically. One UPDATE decides whether the event
-- is new: not the one already applied, and not older than it. Events carry
-- second-resolution times, so on a tie a terminal status (expired > cancelled)
-- is never reverted by a live one. Matches the stored Razorpay subscription, or
-- the user's row while it has none yet. Returns whether a row changed (false
-- = duplicate, stale, or not ours). Called by the webhook with the service role.
-- ---------------------------------------------------------------------
create or replace function billing_status_rank(p_status text)
returns integer
language sql
immutable
as $$
    select case p_status when 'expired' then 2 when 'cancelled' then 1 else 0 end;
$$;

create or replace function billing_apply_event(
    p_razorpay_subscription_id text,
    p_user_id uuid,
    p_plan_id text,
    p_status text,
    p_current_period_end timestamptz,
    p_event_id text,
    p_event_at timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    changed integer;
begin
    if coalesce(p_event_id, '') = '' or p_event_at is null then
        return false;
    end if;
    update subscriptions s set
        razorpay_subscription_id = p_razorpay_subscription_id,
        status = coalesce(p_status, s.status),
        -- paying ends the trial: the row no longer carries a trial end
        trial_ends_at = case when p_status = 'active' then null else s.trial_ends_at end,
        current_period_end = coalesce(p_current_period_end, s.current_period_end),
        plan_id = coalesce(p_plan_id, s.plan_id),
        last_event_id = p_event_id,
        last_event_at = p_event_at,
        updated_at = now()
    where (s.razorpay_subscription_id = p_razorpay_subscription_id
           or (s.razorpay_subscription_id is null and s.user_id = p_user_id))
      and s.last_event_id is distinct from p_event_id
      and (s.last_event_at is null
           or s.last_event_at < p_event_at
           or (s.last_event_at = p_event_at
               and billing_status_rank(coalesce(p_status, s.status)) >= billing_status_rank(s.status)));
    get diagnostics changed = row_count;
    return changed > 0;
end;
$$;
revoke all on function billing_apply_event(text, uuid, text, text, timestamptz, text, timestamptz) from public, anon, authenticated;
grant execute on function billing_apply_event(text, uuid, text, text, timestamptz, text, timestamptz) to service_role;

-- ---------------------------------------------------------------------
-- Refund & end access (admin). Called after the refund and the cancel went
-- through at Razorpay. Ends access now and marks the subscription refunded, so
-- the cancelled / charged webhooks that follow cannot restore the period end
-- (the token hook refuses a refunded subscription). Only the row that still
-- holds that subscription changes; repeating it is harmless. Returns whether it did.
-- ---------------------------------------------------------------------
create or replace function billing_refund_end_access(p_user_id uuid, p_razorpay_subscription_id text)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    changed integer;
begin
    if coalesce(p_razorpay_subscription_id, '') = '' then
        return false;
    end if;
    update subscriptions set
        status = 'cancelled',
        current_period_end = now(),
        refunded_subscription_id = p_razorpay_subscription_id,
        updated_at = now()
    where user_id = p_user_id and razorpay_subscription_id = p_razorpay_subscription_id;
    get diagnostics changed = row_count;
    return changed > 0;
end;
$$;
revoke all on function billing_refund_end_access(uuid, text) from public, anon, authenticated;
grant execute on function billing_refund_end_access(uuid, text) to service_role;

-- ---------------------------------------------------------------------
-- The launch plans, as data (human decision 5 Nov 2026), both markets, same
-- 7-day trial: yearly Rs 999 with an early bird of Rs 699 for the first year to
-- the first 500 subscribers or until 31 Dec 2026 (yearly only), and monthly
-- Rs 129. Seeded without the Razorpay ids: create the plans and the offer in the
-- Razorpay dashboard, then
--   update plans set razorpay_plan_id = 'plan_...', razorpay_offer_id = 'offer_...' where id = 'pro';
--   update plans set razorpay_plan_id = 'plan_...' where id = 'pro-monthly';
-- Until then create-subscription answers no_active_plan. Change a price here.
-- The seed does nothing to rows already present; plans seeded under the old
-- name were renamed by hand (6 Nov 2026):
--   update plans set name = 'Cupel' where name = 'Sievr';
-- ---------------------------------------------------------------------
insert into plans (id, name, amount_paise, period, offer_name, offer_amount_paise, offer_ends_at, offer_limit)
values ('pro', 'Cupel', 99900, 'yearly', 'Early bird', 69900, timestamptz '2026-12-31 23:59:59+05:30', 500)
on conflict (id) do nothing;
insert into plans (id, name, amount_paise, period)
values ('pro-monthly', 'Cupel', 12900, 'monthly')
on conflict (id) do nothing;
