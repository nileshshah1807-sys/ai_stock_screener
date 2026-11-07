#!/usr/bin/env bash
# Applies the billing-related storage/*.sql files to a stub-Supabase Postgres in
# their documented order, then billing_schema.sql AGAIN (the re-apply that once
# dropped other files' column grants), and runs the dashboard's own user reads
# as role `authenticated`. Any SQL error or permission error fails it.
# Usage: PGHOST=... PGPORT=... PGUSER=... PGDATABASE=... tools/check_billing_schema.sh
set -euo pipefail
cd "$(dirname "$0")/.."
psql_() { psql -X -q -o /dev/null -v ON_ERROR_STOP=1 "$@"; }

for f in tools/supabase_stub.sql \
         storage/dashboard_schema.sql \
         storage/billing_schema.sql \
         storage/admin_plans_schema.sql \
         storage/trial_guard_schema.sql \
         storage/billing_schema.sql; do
  echo "applying $f"
  psql_ -f "$f"
done

# A seeded user, then the selects as that user. The column lists are read from
# dashboard/lib/plans.ts so this cannot drift from what the app asks for.
SUB_COLS=$(python3 - <<'PY'
import re
s = open("dashboard/lib/plans.ts").read()
i = s.index('.from("subscriptions")')
print(re.search(r'\.select\("([^"]+)"\)', s[i:]).group(1))
PY
)
PLAN_COLS=$(python3 - <<'PY'
import re
s = open("dashboard/lib/plans.ts").read()
i = s.index('.from("plans")')
print(re.search(r'\.select\("([^"]+)"\)', s[i:]).group(1))
PY
)
echo "subscriptions columns: $SUB_COLS"
echo "plans columns: $PLAN_COLS"

psql_ <<SQL
insert into auth.users (id, email) values ('11111111-1111-1111-1111-111111111111', 'user@example.com') on conflict do nothing;
insert into subscriptions (user_id, status) values ('11111111-1111-1111-1111-111111111111', 'trialing') on conflict (user_id) do nothing;
begin;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
select $SUB_COLS from subscriptions where user_id = '11111111-1111-1111-1111-111111111111';
select $PLAN_COLS from plans where active;
select plan_offer_open('pro');
commit;
begin;
set local role anon;
select $PLAN_COLS from plans where active;
commit;
SQL
echo "billing schema check passed"
