-- cupel-core, laid by hand: D1-only tables with no Supabase twin
-- (workers/ipos.py). Created by `python -m tools.d1_tables apply`.
CREATE TABLE IF NOT EXISTS "ipos" (
    "market" TEXT NOT NULL DEFAULT 'NSE',
    "symbol" TEXT NOT NULL,
    "board" TEXT NOT NULL,
    "company" TEXT,
    "status" TEXT NOT NULL,
    "issue_start" TEXT,
    "issue_end" TEXT,
    "price_low" REAL,
    "price_high" REAL,
    "issue_price" REAL,
    "lot_size" INTEGER,
    "issue_size_shares" INTEGER,
    "subscription_times" REAL,
    "listing_date" TEXT,
    "listing_open" REAL,
    "listing_close" REAL,
    PRIMARY KEY ("market", "symbol", "board")
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS "ipo_subscriptions" (
    "market" TEXT NOT NULL DEFAULT 'NSE',
    "symbol" TEXT NOT NULL,
    "as_of" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "shares_offered" INTEGER,
    "shares_bid" INTEGER,
    "times" REAL,
    PRIMARY KEY ("market", "symbol", "as_of", "category")
) WITHOUT ROWID;
