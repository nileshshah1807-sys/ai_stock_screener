-- =====================================================================
-- Invited users join the allowlist when they accept
-- =====================================================================
--
-- An invite sent from Supabase -> Authentication -> Users creates an auth
-- user with invited_at set; accepting the email link sets email_confirmed_at.
-- At that moment this trigger adds the address to dashboard_allowlist as a
-- viewer, so inviting someone is the whole job.
--
-- Only invites count. Sending one needs the dashboard or the service-role
-- key, while a sign-up through the public API (possible with the anon key
-- unless sign-ups are disabled in the project) leaves invited_at null and
-- still reads nothing. A user created with "Create user" rather than invited
-- is not added either; list them by hand.
--
-- The grant fires once, on the confirmation itself, so removing someone from
-- dashboard_allowlist stays removed. An existing row keeps its role: an
-- admin is never demoted to viewer.
--
-- Apply after dashboard_schema.sql:
--   psql "$SUPABASE_DB_URL" -f storage/dashboard_invites_schema.sql
-- Safe to re-run.

create or replace function dashboard_allowlist_invited_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.dashboard_allowlist (email, role)
    values (lower(new.email), 'viewer')
    on conflict (email) do nothing;
    return new;
end;
$$;

-- An invite accepted after it was sent: the usual path.
drop trigger if exists dashboard_allowlist_on_invite_accepted on auth.users;
create trigger dashboard_allowlist_on_invite_accepted
    after update of email_confirmed_at on auth.users
    for each row
    when (
        old.email_confirmed_at is null
        and new.email_confirmed_at is not null
        and new.invited_at is not null
        and new.email is not null
    )
    execute function dashboard_allowlist_invited_user();

-- An invited user written already confirmed, in a single insert.
drop trigger if exists dashboard_allowlist_on_invited_insert on auth.users;
create trigger dashboard_allowlist_on_invited_insert
    after insert on auth.users
    for each row
    when (
        new.email_confirmed_at is not null
        and new.invited_at is not null
        and new.email is not null
    )
    execute function dashboard_allowlist_invited_user();

-- One-off, for invites accepted before the trigger existed. Left commented
-- out because re-running this file would otherwise re-grant anyone since
-- removed from the allowlist:
--
--   insert into dashboard_allowlist (email, role)
--   select lower(email), 'viewer'
--   from auth.users
--   where invited_at is not null
--     and email_confirmed_at is not null
--     and email is not null
--   on conflict (email) do nothing;
