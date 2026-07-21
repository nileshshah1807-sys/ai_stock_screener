# AI Stock Screener

Daily NSE stock screener with Reverse DCF analysis, CSV reports, dashboard output, and email delivery.

## Railway Cache

Attach a Railway Volume and mount it at `/data`, then set:

```text
OUTPUT_DIR=/data/reports_advanced
YFINANCE_CACHE_DIR=/data/yfinance_cache
FUND_CACHE_MAX_AGE_DAYS=30
PRICE_CACHE_MAX_AGE_HOURS=18
```

Without a Railway Volume, cache files are lost when the container is rebuilt or redeployed.
  
