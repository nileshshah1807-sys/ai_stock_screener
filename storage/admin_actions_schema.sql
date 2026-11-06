-- The log of what an admin did on the /admin page: who, what, to whom, when.
-- Written by the dashboard's server with the service role; no one else can
-- read or write it. target_id has no foreign key, so a deleted user's line stays.
--
-- Not applied by the dashboard; apply by hand after review:
--   psql "$SUPABASE_DB_URL" -f storage/admin_actions_schema.sql   (safe to re-run)

create table if not exists admin_actions (
    id bigint generated always as identity primary key,
    admin_id uuid not null,
    admin_email text not null,
    action text not null,
    target_id uuid,
    target_email text,
    detail jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists admin_actions_created on admin_actions (created_at desc);

-- Service role only: no policy, no grant.
alter table admin_actions enable row level security;
revoke all on admin_actions from anon, authenticated;
