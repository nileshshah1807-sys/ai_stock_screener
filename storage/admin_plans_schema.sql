-- Admin plan management (/admin/plans). Applied by hand, after
-- storage/billing_schema.sql. Safe to re-run.
--
-- 1. app_settings: one row per setting, written only by the service role
--    (the admin pages). Today: trial_days, the length of a NEW sign-up's trial.
-- 2. billing_start_trial() reads trial_days instead of a literal 7.
-- 3. subscriptions.plan_amount_paise: the plan price a subscriber took, written
--    at checkout, so a later price change never rewrites what they pay.

create table if not exists app_settings (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz not null default now()
);
alter table app_settings enable row level security;
revoke all on app_settings from anon, authenticated;
-- no policy, no grant: only the service role (and the definer function below) reads it.

insert into app_settings (key, value) values ('trial_days', '7'::jsonb)
on conflict (key) do nothing;

create or replace function billing_start_trial()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    days integer;
begin
    select case when jsonb_typeof(value) = 'number' then (value #>> '{}')::numeric::integer end
      into days from public.app_settings where key = 'trial_days';
    days := least(greatest(coalesce(days, 7), 1), 60);  -- a bad value never blocks a sign-up
    insert into public.subscriptions (user_id, status, trial_ends_at)
    values (new.id, 'trialing', now() + make_interval(days => days))
    on conflict (user_id) do nothing;
    return new;
end;
$$;
revoke all on function billing_start_trial() from public, anon, authenticated;

alter table subscriptions add column if not exists plan_amount_paise integer
    check (plan_amount_paise >= 0);
-- Subscribers who exist now took today's price.
update subscriptions s set plan_amount_paise = p.amount_paise
from plans p
where s.plan_id = p.id and s.plan_amount_paise is null;
grant select (plan_amount_paise) on subscriptions to authenticated;
