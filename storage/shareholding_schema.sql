-- =====================================================================
-- Shareholding patterns and bulk/block deals, as NSE discloses them
-- =====================================================================
--
-- Display evidence for the stock page's Shareholding tab; nothing scores it.
-- Written by workers/shareholding.py (a step of the Quarterly filings
-- workflow), parsed by screener/shareholding.py. NSE only: the US has no
-- quarterly shareholding pattern and no bulk deals.
--
-- shareholding_patterns: one row per (market, symbol, quarter end), the
-- latest filing of that quarter. A revision is a new record_id and replaces
-- the row. Percentages are of total shares, in percent:
--   promoter, fii (Institutions - Foreign), dii (Institutions - Domestic),
--   public (the rest, employee trusts and government included)
-- and `holders` is the named holders the format requires, largest first:
--   [{name, group: promoter|fii|dii|public, pct, shares}]
-- A group nobody is in is 0 (a complete filing omits its subtotal); all four
-- are null only when the document has no grand total to read them against.
--
-- bulk_block_deals: one row per printed trade, as the exchange lists it.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/shareholding_schema.sql
-- Safe to re-run. Needs dashboard_has_access() from dashboard_schema.sql.

create table if not exists shareholding_patterns (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    period_end date not null,
    -- The exchange's id for the filing this row was parsed from.
    record_id text not null,
    filed_at timestamptz not null,
    document_url text not null,
    company text,
    promoter numeric,
    fii numeric,
    dii numeric,
    public numeric,
    shareholders bigint,
    shares numeric,
    holders jsonb not null default '[]'::jsonb,
    -- screener.shareholding.PARSER_VERSION; an older row is read again.
    parser_version integer not null,
    parsed_at timestamptz not null default now(),

    primary key (market, symbol, period_end)
);

create table if not exists bulk_block_deals (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    kind text not null check (kind in ('bulk', 'block')),
    deal_date date not null,
    symbol text not null,
    client_name text not null,
    side text not null,
    quantity bigint not null,
    price numeric not null,
    remarks text,

    primary key (market, kind, deal_date, symbol, client_name, side, quantity, price)
);

-- Serves the stock page: one company's deals, newest first.
create index if not exists bulk_block_deals_symbol_idx
    on bulk_block_deals (market, symbol, deal_date desc);

-- Written by the service role only, which bypasses RLS. Read by the stock
-- page under the same rule as the rest of the read model.
alter table shareholding_patterns enable row level security;
alter table bulk_block_deals enable row level security;

drop policy if exists shareholding_patterns_read on shareholding_patterns;
create policy shareholding_patterns_read
    on shareholding_patterns for select
    using ((select dashboard_has_access()));

drop policy if exists bulk_block_deals_read on bulk_block_deals;
create policy bulk_block_deals_read
    on bulk_block_deals for select
    using ((select dashboard_has_access()));

revoke all on shareholding_patterns from anon;
revoke all on bulk_block_deals from anon;
grant select on shareholding_patterns to authenticated;
grant select on bulk_block_deals to authenticated;
