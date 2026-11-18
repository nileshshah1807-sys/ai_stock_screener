-- cupel-evidence, laid by hand: a D1-only table with no Supabase twin
-- (workers/market_flows.py). Created by `python -m tools.d1_tables apply`.
CREATE TABLE IF NOT EXISTS "fii_dii_flows" (
    "market" TEXT NOT NULL DEFAULT 'NSE',
    "session_date" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "buy_value" REAL,
    "sell_value" REAL,
    "net_value" REAL,
    PRIMARY KEY ("market", "session_date", "category")
) WITHOUT ROWID;
