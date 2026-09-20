# Winnow — working notes

Daily equity research screener across two markets, NSE and US. `app.py` is the
composition root; the scheduled GitHub Actions workflows are the production
runtime, one per market.

## Commands

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
TRANSCRIPT_ENABLE_FINBERT=false pytest      # 1085 tests, ~35s
ruff check .                                 # must stay clean

MARKET=US python app.py                      # the same pipeline, US universe
```

Tests are `unittest`-style classes run under pytest. `TRANSCRIPT_ENABLE_FINBERT=false`
keeps the FinBERT path — and the torch import behind it — out of the run; CI and
the scheduled workflows set the same flag.

## Conventions

- **Logging, not printing.** Every module does `logger = logging.getLogger(__name__)`.
  `print()` is acceptable only under `tools/`, where console output is the interface.
- **Rounding goes through `screener.numeric`.** Use `round_half_up` /
  `round_series_half_up`, never bare `round()` on an exported number. Python,
  NumPy and pandas disagree at exact half-cent boundaries, and exports must be
  version-stable.
- **Missing vendor values go through `safe_float`** (`screener.numeric`), which
  treats `None`, `NaN` and stray text alike as "not reported".
- **Absent evidence is not a zero.** Scores are coverage-normalised: a component
  whose input was never reported leaves both the numerator and the denominator,
  and the result is shrunk toward neutral. Never let an unreported metric score
  as the worst observed value.

## Markets

- **`MARKET` selects the market; everything else follows.** `screener/markets.py`
  holds one `MarketProfile` per market — ticker suffix, timezone, session
  cutoff, benchmark index, universe source, currency. A profile supplies
  **defaults only**: every env var keeps its old name and precedence, so an
  unset `MARKET` resolves to exactly the NSE values the pipeline used before it
  was market-aware. That property is what the test suite asserts, and it is why
  adding a market did not disturb the existing one.
- **The scoring layer is market-agnostic and must stay that way.**
  `screener/scoring/`, `factors.py` and `stage.py` are cross-sectional *within
  one run's frame*, so a US run ranks US stocks against US stocks with no
  changes. Never introduce a market branch into a score.
- **Env vars named `*_INR` and `*_IST` are read as market currency and market
  local time.** `MIN_AVG_TURNOVER_INR` is dollars on a US run;
  `MARKET_BAR_COMPLETE_AFTER_IST` is 16:00 ET. The names are kept for
  compatibility with the schema, the publisher and existing workflows, and
  renaming them would cascade for no behavioural gain.
- **`market` is part of every read-model key.** A symbol does not identify a
  company across exchanges — TCS is Tata Consultancy on NSE and The Container
  Store in the US. Any new query against `screener_snapshot`, `screener_history`
  or `price_series` must filter on it; `DashboardRepository` is scoped to one
  market at construction so it cannot be forgotten.
- **NSE-only evidence degrades, it does not fail.** The impact-cost overlay
  (`screener/liquidity.py`), transcript sentiment and the VIGIL red-flag feed
  have no US counterpart. They are switched off by env in the US workflow and
  the affected columns read "Unavailable" or stay neutral — never zero.

## Boundaries that matter

- **`screener/recommendation.py` is the only writer of canonical decisions**
  (`Rating`, `Rank`, `Buy_Eligible`, `Final_Score`, ...). The scoring layer emits
  components and `Core_*` diagnostics only. A rescored export purges stale
  canonical columns first.
- **`backtest/` is point-in-time.** It must never read anything the model could
  not have seen on the day being simulated.
- **`app.py` is also a backwards-compatible API.** It re-exports names that
  callers and tests import directly, so its "unused" imports are deliberate —
  `pyproject.toml` exempts it from `F401`. Do not strip them.
- **Dependencies are locked.** Edit `requirements*.in`, then regenerate the
  `.txt` locks (each lock header carries its command). `torch` and `transformers`
  stay in the production lock because `validation/reproducibility.py` records
  their versions in the run manifest; removing them changes the manifest hash.

## Layout

```
screener/     live scoring path (scoring/ is a package: constants, points,
              fundamental, sector_models, technical, engine); markets.py and
              universe.py hold the per-market facts and universe sources
backtest/     point-in-time simulation, deliberately separate from the live path
workers/      scheduled jobs (dashboard publish, transcripts, red flags)
storage/      Supabase repositories
validation/   reproducibility manifests and replay
dashboard/    Next.js front end, with its own README; routes are nested
              under /[market] (/nse, /us)
```

## Gotchas

- The repo is edited from both Windows and WSL. `.gitattributes` pins LF; keep
  `core.autocrlf=input` locally or the whole tree shows as modified.
- `ruff`'s ratchet list in `pyproject.toml` records rules the codebase does not
  yet satisfy, with counts. Removing an entry means fixing its violations.
