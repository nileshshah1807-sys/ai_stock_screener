-- cupel-evidence, laid by hand: a D1-only table with no Supabase twin
-- (workers/ipos.py). Created by `python -m tools.d1_tables apply`.
-- One row per NSE issue (mainboard and SME), open, upcoming or listed within a
-- year. "subscription" is a JSON array of the book's top-level categories.
CREATE TABLE IF NOT EXISTS "ipo_issues" (
    "market" TEXT NOT NULL DEFAULT 'NSE',
    "symbol" TEXT NOT NULL,
    "company" TEXT,
    "board" TEXT,
    "open_date" TEXT,
    "close_date" TEXT,
    "listing_date" TEXT,
    "price_low" REAL,
    "price_high" REAL,
    "issue_price" REAL,
    "lot_size" INTEGER,
    "face_value" REAL,
    "book_shares" REAL,
    "registrar" TEXT,
    "rhp_url" TEXT,
    "detail_read" INTEGER,
    "subscription" TEXT,
    "subscription_total" REAL,
    "subscription_as_of" TEXT,
    "book_final" INTEGER,
    "listing_open" REAL,
    "listing_close" REAL,
    "listing_checked" INTEGER,
    "gmp" REAL,
    "gmp_pct" REAL,
    "gmp_peak" REAL,
    "gmp_as_of" TEXT,
    PRIMARY KEY ("market", "symbol")
) WITHOUT ROWID;
