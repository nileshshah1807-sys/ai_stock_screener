#!/bin/sh
# Build and deploy this dashboard to the production Worker (cupel-dashboard), then prime it.
#
# Run from a clean worktree at origin/main, from dashboard/, after `npm ci`. Needs in the environment
# (never in this file): CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, NEXT_PUBLIC_SUPABASE_ANON_KEY,
# NEXT_PUBLIC_BRANDFETCH_CLIENT_ID. On the office machine, wrap it in md-secret run for each.
# The build must reach Google Fonts (next/font), so it cannot run in a network sandbox.
#
# Watch signed-in pages for 15 minutes after it (Worker exceeded resource limits = Cloudflare 1102);
# to undo: npx wrangler deployments list, then npx wrangler rollback <previous version id> -y.
set -eu
: "${CLOUDFLARE_API_TOKEN:?}" "${CLOUDFLARE_ACCOUNT_ID:?}" "${NEXT_PUBLIC_SUPABASE_ANON_KEY:?}" "${NEXT_PUBLIC_BRANDFETCH_CLIENT_ID:?}"
cd "$(dirname "$0")/.."
# Public values, inlined into the browser bundle at build time.
export NEXT_PUBLIC_SUPABASE_URL="${NEXT_PUBLIC_SUPABASE_URL:-https://aeikzaubhepxjxqdhkjz.supabase.co}"
export NEXT_PUBLIC_SITE_URL="${NEXT_PUBLIC_SITE_URL:-https://cupel.in}"
export NEXT_TELEMETRY_DISABLED=1
log="${TMPDIR:-/tmp}/cupel-cf-build.log"
npx opennextjs-cloudflare build > "$log" 2>&1 || { tail -30 "$log"; exit 1; }
npx wrangler deploy --dry-run 2>&1 | grep "Total Upload" || true
npx opennextjs-cloudflare deploy 2>&1 | grep -E "Deployed|Current Version|rror" || true
# A cold Worker's first requests are the slow ones: take them here, not on a visitor.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do curl -s -o /dev/null -w "%{http_code} " "$NEXT_PUBLIC_SITE_URL/login"; done
echo
