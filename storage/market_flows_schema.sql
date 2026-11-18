-- NSE's daily FII/DII cash-market flows and participant-wise F&O open interest
-- (workers/market_flows.py, a step of the Quarterly filings workflow).
-- Display evidence for the Market page; nothing scores it.
--
-- fii_dii_flows: the provisional cash-market activity NSE publishes each
-- evening, in rupees crore, one row per category (FII = FII/FPI, DII).
-- participant_oi: open interest in equity derivatives, in contracts, one row
-- per participant (Client, DII, FII, Pro).
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/market_flows_schema.sql
-- Safe to re-run. Needs dashboard_has_access() from dashboard_schema.sql.

create table if not exists fii_dii_flows (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    session_date date not null,
    category text not null check (category in ('FII', 'DII')),
    buy_value numeric,
    sell_value numeric,
    net_value numeric,
    updated_at timestamptz not null default now(),

    primary key (market, session_date, category)
);

create table if not exists participant_oi (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    session_date date not null,
    category text not null check (category in ('Client', 'DII', 'FII', 'Pro')),
    future_index_long bigint not null,
    future_index_short bigint not null,
    future_stock_long bigint not null,
    future_stock_short bigint not null,
    option_index_call_long bigint not null,
    option_index_put_long bigint not null,
    option_index_call_short bigint not null,
    option_index_put_short bigint not null,
    option_stock_call_long bigint not null,
    option_stock_put_long bigint not null,
    option_stock_call_short bigint not null,
    option_stock_put_short bigint not null,
    total_long bigint not null,
    total_short bigint not null,
    updated_at timestamptz not null default now(),

    primary key (market, session_date, category)
);

-- Written by the service role only, which bypasses RLS. Read under the same
-- rule as the rest of the read model.
alter table fii_dii_flows enable row level security;
alter table participant_oi enable row level security;

drop policy if exists fii_dii_flows_read on fii_dii_flows;
create policy fii_dii_flows_read
    on fii_dii_flows for select
    using ((select dashboard_has_access()));

drop policy if exists participant_oi_read on participant_oi;
create policy participant_oi_read
    on participant_oi for select
    using ((select dashboard_has_access()));

revoke all on fii_dii_flows from anon;
revoke all on participant_oi from anon;
grant select on fii_dii_flows to authenticated;
grant select on participant_oi to authenticated;
