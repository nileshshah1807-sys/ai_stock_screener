-- =====================================================================
-- Recently listed stocks the screener has not rated yet
-- =====================================================================
--
-- A mainboard listing reaches the scored universe only once it has 60 trading
-- sessions of history and clears the liquidity floor. Until then it was simply
-- absent from the dashboard, which read as "the screener missed this IPO".
-- This table makes the wait visible: one row per recent listing that is NOT in
-- the latest published run, with the reason it is not rated yet.
--
-- Deliberately outside screener_snapshot. These rows carry no score, rating or
-- rank -- recommendation.py remains the only writer of those -- and keeping
-- them out of the snapshot means no rank count, summary tile, export or model
-- input can mistake an unrated listing for a rated one.
--
-- Self-cleaning: workers/new_listings.py replaces the set on every run, so a
-- listing leaves this table the day it enters the scored universe.
--
-- NSE only for now: the US universe source carries no listing date.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f storage/new_listings_schema.sql
-- Safe to re-run.

create table if not exists new_listings (
    market text not null default 'NSE' check (market in ('NSE', 'US')),
    symbol text not null,
    company text,
    isin text,
    series text,
    listed_on date not null,

    -- insufficient_history | below_liquidity_floor | no_price_data | pending_run
    status text not null,
    sessions integer,
    sessions_required integer not null,
    first_session date,
    first_close numeric,
    last_session date,
    last_close numeric,
    change_since_first_pct numeric,
    avg_turnover_20d numeric,
    median_turnover_20d numeric,
    turnover_floor numeric not null,
    market_cap numeric,

    updated_at timestamptz not null default now(),

    primary key (market, symbol)
);

create index if not exists new_listings_listed_idx
    on new_listings (market, listed_on desc);

alter table new_listings enable row level security;

-- Same access rule as the rest of the read model: signed in and allowlisted.
drop policy if exists new_listings_read on new_listings;
create policy new_listings_read
    on new_listings for select
    using (dashboard_has_access());
