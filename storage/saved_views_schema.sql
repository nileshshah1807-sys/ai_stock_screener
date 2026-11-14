-- Saved screener views, kept in the viewer's account rather than the browser.
--
-- A view is a name and the screener URL's view-owned query string
-- (dashboard/lib/view-match.mjs VIEW_KEYS: filters, sort, columns and the
-- viewer's own weights `w=`). It carries nothing the URL does not.
--
-- Applied by hand, after dashboard_schema.sql (it uses dashboard_has_access()).
-- Re-applying is safe. Until it is applied the dashboard keeps the views in
-- localStorage; once it is, each viewer's local views move here on their next
-- screener visit and are cleared from the browser.

create table if not exists saved_views (
    id uuid primary key default gen_random_uuid(),
    -- auth.uid() as the default, so the browser never supplies it, and the
    -- RLS with-check below refuses any other value.
    user_id uuid not null default auth.uid()
        references auth.users(id) on delete cascade,
    market text not null check (market in ('NSE', 'US')),
    name text not null,
    query text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint saved_views_name_present check (length(btrim(name)) > 0),
    constraint saved_views_name_bounded check (length(name) <= 60),
    constraint saved_views_query_bounded check (length(query) <= 2000)
);

-- Case-insensitive, as watchlists_owner_name_idx: "Banks" beside "banks" is a
-- duplicate to the person reading their own views.
create unique index if not exists saved_views_owner_name_idx
    on saved_views (user_id, market, lower(name));

-- At most 50 views per user and market (SAVED_VIEWS_MAX in
-- dashboard/lib/saved-views.mjs; a test keeps the two equal). In the database
-- because the API is reachable with the viewer's own token, not only through
-- the dashboard. Per row, so a multi-row insert counts its own earlier rows;
-- the advisory lock serialises one user's concurrent inserts. An update that
-- moves a row to another market is checked too; any other update is not.
create or replace function saved_views_enforce_cap()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    if tg_op = 'UPDATE' and new.market = old.market then
        return new;
    end if;
    perform pg_advisory_xact_lock(hashtext('saved_views:' || new.user_id::text || ':' || new.market));
    if (select count(*) from saved_views
        where user_id = new.user_id and market = new.market) >= 50 then
        raise exception 'saved_views_cap: at most 50 saved views per market'
            using errcode = 'P0001';
    end if;
    return new;
end;
$$;

drop trigger if exists saved_views_cap on saved_views;
create trigger saved_views_cap
    before insert or update of market on saved_views
    for each row execute function saved_views_enforce_cap();

alter table saved_views enable row level security;

-- One `for all` policy, as watchlists_owner_all: the same condition governs
-- every operation, and `with check` stops a row being written for another user.
drop policy if exists saved_views_owner_all on saved_views;
create policy saved_views_owner_all
    on saved_views for all
    to authenticated
    using (user_id = (select auth.uid()) and (select dashboard_has_access()))
    with check (user_id = (select auth.uid()) and (select dashboard_has_access()));

revoke all on saved_views from anon;
grant select, insert, update, delete on saved_views to authenticated;
