# AI Stock Screener — working notes

Daily NSE research screener. `app.py` is the composition root; the scheduled
GitHub Actions workflows are the production runtime.

## Commands

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
TRANSCRIPT_ENABLE_FINBERT=false pytest      # 1011 tests, ~35s
ruff check .                                 # must stay clean
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
              fundamental, sector_models, technical, engine)
backtest/     point-in-time simulation, deliberately separate from the live path
workers/      scheduled jobs (dashboard publish, transcripts, red flags)
storage/      Supabase repositories
validation/   reproducibility manifests and replay
dashboard/    Next.js front end, with its own README
```

## Gotchas

- The repo is edited from both Windows and WSL. `.gitattributes` pins LF; keep
  `core.autocrlf=input` locally or the whole tree shows as modified.
- `ruff`'s ratchet list in `pyproject.toml` records rules the codebase does not
  yet satisfy, with counts. Removing an entry means fixing its violations.
