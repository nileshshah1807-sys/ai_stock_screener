# Research scripts

Offline studies on the Returns engine (`lib/returns.mjs`), run on data cached
from Supabase. They read with the service-role key and never write. Results
and the ~75 MB data cache go to `out/`, which git ignores.

From `dashboard/`, with the repo's `.env` loaded:

```bash
set -a && . ../.env && set +a
node scripts/research/data.mjs design 2025-09-30   # backtest rankings, states, prices, indexes
node scripts/research/data.mjs holdout             # Sep 2025 to the latest run
node scripts/research/filter-study.mjs             # 324 runs -> out/facts.json
node scripts/research/p7.mjs                       # 16 runs  -> out/p7-design.json
node scripts/research/p7-holdout.mjs               # 2 runs   -> out/p7-holdout.json
node scripts/research/data.mjs design 2026-08-10   # the whole backtest, for rolling windows
node scripts/research/rolling.mjs filters          # ~8,200 windows -> out/rolling-filters.json (~2 min)
node scripts/research/rolling.mjs rules            # ~3,600 windows -> out/rolling-rules.json
node scripts/research/rolling-summary.mjs          # out/rolling-summary.json
node scripts/research/invested.mjs                 # 100/80/60/40% invested -> out/invested.json
node scripts/research/report.mjs                   # out/report.html
node scripts/research/pdf.mjs                      # out/report.pdf (needs playwright)
```

`engine.mjs` reproduces what the Returns page does for backtest dates --
the same buy lists, hold rules and engine -- plus the P7 rules
(`regimeAt` is `classify_regime` from `screener/benchmark.py`).

`p8-forward.mjs` is the live test of the trailing stop, pre-registered in
`docs/Review/p8_trailing_stop_forward_preregistration.md`; refresh the data
with `data.mjs holdout` first. It has no decision to make before September 2027.

The published report and the P7 pre-registration are in `docs/Review/`. The
P7 holdout year (Oct 2025 - Sep 2026) is spent: re-running `p7-holdout.mjs`
reproduces the recorded result; testing a new rule on it would not be a test.
