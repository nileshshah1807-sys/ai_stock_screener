/** Supabase views a reader names, as SQLite subqueries over their D1 tables (lib/db/market-repository.ts). */

// The Supabase view, as SQLite over its table (storage/quarterly_filings_schema.sql).
export const RESULT_FEED = `(SELECT market, symbol, period_end,
    coalesce(min(broadcast_at), min(filed_at)) AS announced_at,
    max(company) AS company,
    max(is_consolidated) AS has_consolidated,
    max(1 - is_consolidated) AS has_standalone,
    max(CAST(json_extract(lines, '$.period_days') AS INTEGER)) AS period_days
  FROM quarterly_filings
  WHERE json_extract(lines, '$.revenue') IS NOT NULL OR json_extract(lines, '$.net_profit') IS NOT NULL
     OR json_extract(lines, '$.cumulative.revenue') IS NOT NULL OR json_extract(lines, '$.cumulative.net_profit') IS NOT NULL
  GROUP BY market, symbol, period_end) AS "quarterly_result_feed"`;
