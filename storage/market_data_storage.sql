-- =====================================================================
-- Supabase Storage bucket for file-shaped market data
-- =====================================================================
--
-- Chart price series moved here from the price_series / price_calendar
-- tables. The free plan's database stops accepting writes at 500 MB, and those
-- tables were ~80 MB of it; Storage has its own 1 GB, under the same auth.
--
-- Layout (all gzip JSON, the same fields the table rows held):
--   price-series/{MARKET}/calendar.json.gz
--   price-series/{MARKET}/symbols/{SYMBOL}.json.gz
--
-- Written by workers/price_series_publisher.py with the service role, which
-- bypasses these policies. Read by the dashboard as the signed-in viewer, so
-- the same invite-list rule as every other read applies.
--
-- Apply in the Supabase SQL editor. Safe to re-run.

insert into storage.buckets (id, name, public)
values ('market-data', 'market-data', false)
on conflict (id) do nothing;

drop policy if exists market_data_read on storage.objects;
create policy market_data_read
    on storage.objects for select
    to authenticated
    using (bucket_id = 'market-data' and public.dashboard_has_access());

-- ---------------------------------------------------------------------
-- After tools/migrate_price_series_to_storage.py reports every market
-- verified and the dashboard reads from Storage, reclaim the space:
--
--   drop table if exists price_series;
--   drop table if exists price_calendar;
-- ---------------------------------------------------------------------
