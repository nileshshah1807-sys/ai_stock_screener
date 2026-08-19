# Development Guidelines — Branching, Workflows, and Repository Hygiene

- **Status:** working agreement for day-to-day development
- **Scope:** branch lifecycle, merge strategy, GitHub Actions inventory, cleanup procedure
- **Applies to:** `nileshshah1807-sys/ai_stock_screener`
- **Last reviewed:** 2026-08-19

> **Why this document exists.** Long-lived branches drifted behind `main` while their work
> had already been merged through pull requests. The result was a repo with eleven branches,
> nine of which contained nothing that `main` did not already have, and one model branch
> sitting twenty-two commits stale. Nothing was lost, but the branch list stopped telling the
> truth about what was in flight. The rules below keep that from recurring.

---

## 1. The branch model

Three long-lived branches. Everything else is temporary.

| Branch | Role | Lifetime |
| --- | --- | --- |
| `main` | Production. Scheduled workflows run from here. | Permanent |
| `feat/model-5-factor-architecture` | Model 5.0 factor architecture line | Permanent while Model 5 is the production contract |
| `model-v4-system-redesign` | Model 4.x reference line, kept for comparison | Permanent while 4.x remains the local/manual default |

Every other branch is a **short-lived topic branch**: it exists to carry one change to one
pull request, and it is deleted the moment that PR merges.

### 1.1 Naming

Keep the existing prefixes; they read well in a branch list:

- `feat/<slug>` — new capability
- `fix/<slug>` — corrective change
- `perf/<slug>` — performance work
- `docs/<slug>` — documentation only

Use a slug that names the *outcome*, not the file touched: `fix/statement-derived-coverage`,
not `fix/statements-py`.

### 1.2 Lifetime

A topic branch should live **days, not weeks**. The longer it lives, the more `main` moves
underneath it. If a branch is going to outlive a week, rebase it onto `main` at least every
few days so the eventual merge is small.

---

## 2. The rule that prevents the drift

> **Delete a topic branch the moment its PR merges — locally and on GitHub.**

GitHub can do this automatically. Enable it once:

**Settings → General → Pull Requests → "Automatically delete head branches"**

That single setting would have prevented nine of the eleven stale branches. Turn it on.

For the local side, prune on every fetch. Set it once, globally:

```bash
git config --global fetch.prune true
```

Now `git fetch` (and `git pull`) automatically drops local `origin/*` refs whose remote
branch is gone.

---

## 3. Keeping the long-lived model branches current

`main` is the integration point. The model branches must never be allowed to fall far
behind it.

**After every merge to `main`, fast-forward the model branches:**

```bash
git checkout main && git pull
git checkout feat/model-5-factor-architecture
git merge --ff-only main
git push origin feat/model-5-factor-architecture
```

`--ff-only` is deliberate. If it fails, the branch has diverged — it has commits `main` does
not. That is a real signal, and it deserves a look rather than a merge commit papering over
it. Find out what diverged:

```bash
git log --oneline main..feat/model-5-factor-architecture
```

If that prints nothing, the branch is purely behind and the fast-forward is safe. If it
prints commits, decide whether they belong in `main` before going further.

### 3.1 Cadence

Fast-forward the model branches **on the same day** a PR merges to `main`. This is a
ten-second operation when done regularly and a twenty-two-commit archaeology exercise when
it is not.

---

## 4. Verifying a branch is safe to delete

Never delete on vibes. A branch is safe to delete when its tip is an ancestor of `main` —
that is, `main` already contains every commit it has.

```bash
git merge-base --is-ancestor <branch> main && echo "SAFE: fully merged"
git log --oneline main..<branch>     # must print nothing
```

Both checks must agree. To sweep the whole repo at once:

```bash
git branch -a --no-merged main       # anything listed here has unmerged work
```

### 4.1 When `git branch -d` refuses

`git branch -d` compares the branch against **both** `HEAD` and its upstream tracking
branch. A branch whose local tip is ahead of its own remote will be refused even when it is
fully merged into `main` — git says so explicitly:

```
warning: not deleting branch 'x' that is not yet merged to 'refs/remotes/origin/x',
         even though it is merged to HEAD
```

That message means the content is safe. Confirm with the ancestry check in section 4, then
use `-D`. Do not reach for `-D` first.

### 4.2 Deleting

```bash
git branch -d <branch>                    # local
git push origin --delete <branch>         # remote
```

Record the SHA before deleting a remote branch. A deleted remote branch is recoverable only
if someone knows where it pointed:

```bash
git for-each-ref --format='%(refname:short) = %(objectname)' refs/remotes/origin
```

---

## 5. Recovering from a mistaken delete

Nothing here is truly lost, but the recovery path differs by case.

| Situation | Recovery |
| --- | --- |
| Local branch deleted | `git reflog` → `git branch <name> <sha>` |
| Remote branch deleted, SHA known | `git push origin <sha>:refs/heads/<name>` |
| Remote branch deleted, SHA unknown | GitHub Settings → check the PR page; the merge commit still references it |
| Deleted file or workflow | `git checkout <sha> -- <path>` |

Local reflog entries expire after 90 days by default. Recover promptly.

---

## 6. GitHub Actions inventory

Three workflows are live. Anything not on this list should not exist in
`.github/workflows/`.

| Workflow | File | Trigger | Purpose |
| --- | --- | --- | --- |
| Daily stock screener | `daily-stock-screener.yml` | `schedule` + `workflow_dispatch` | Production run. Scheduled runs are Model 5.0; manual dispatches are isolated 4.x smoke runs. |
| Red flag shadow | `red-flag-shadow.yml` | scheduled | Shadow red-flag evidence collection |
| Transcript sentiment | `transcript-sentiment.yml` | scheduled | Earnings call transcript sentiment |

### 6.1 The scheduled/manual split

`daily-stock-screener.yml` behaves differently depending on how it is triggered, and this is
intentional. Scheduled runs alone may reuse production caches, append backtest history,
query the red-flag store, and send notifications. Every manual dispatch is an isolated
candidate run writing to `.validation-output/<run_id>/` with email disabled.

**Consequence:** you cannot validate production behaviour by clicking "Run workflow". A
manual dispatch is a 4.x smoke test by design (`FACTOR_MODEL_ENABLED=False`).

### 6.2 Retired workflows

Three workflows were removed on 2026-08-19 as development-only tooling. They remain in git
history and can be restored with `git checkout <sha> -- <path>`.

| Retired workflow | What it did | Why removed |
| --- | --- | --- |
| `backfill-logo-domains.yml` | One-shot Supabase backfill of company logo domains | Backfill completed; manual dispatch only |
| `candidate-model-validation.yml` | Isolated Model 5.0 candidate validation | Superseded by Model 5.0 reaching production |
| `seed-production-statement-cache.yml` | Seeded the production statement cache from a candidate artifact | Bootstrap tool; the daily run now sustains its own cache |

**Before adding a workflow, ask whether it is permanent.** A one-shot migration or backfill
is better run as a local script than left in `.github/workflows/` where it accumulates. If
it must be a workflow, note its expected retirement in this table when you add it.

---

## 7. The statement cache contract

Worth understanding before touching cache keys or the retired seeding workflow.

The daily screener restores `reports_advanced/statement_cache.csv` from cache prefix
`stock-screener-statements-v1-<os>-` and saves it back on every scheduled run. It is
**self-sustaining**: the daily cadence keeps the entry warm, well inside GitHub's 7-day
eviction window for unused caches.

If that cache is ever lost — a multi-day gap in scheduled runs, a repo cache eviction, or a
manual purge — the screener rebuilds it from scratch. `STATEMENT_FETCH_MAX_SYMBOLS_PER_RUN`
is `2500` on scheduled runs precisely so a cold first run can build the whole NSE universe.

**The tradeoff to know:** `FACTOR_MIN_STATEMENT_UNIVERSE_COVERAGE` is `0.95`. A cold rebuild
may land below that threshold on its first run and produce degraded factor output until
coverage recovers. This is the capability the retired seeding workflow used to shortcut. It
is an acceptable one-day cost, not a silent failure — but do not schedule a cache purge the
night before you need a clean report.

Statements deliberately use a **separate cache entry** from market data. Adding
`statement_cache.csv` to the composite market-data cache changes GitHub's hidden cache
version and invalidates every warm production entry created before Model 5.0. Keep them
separate.

---

## 8. Pre-merge checklist

Before opening a pull request:

- [ ] Branch is named `<type>/<outcome-slug>`
- [ ] Branch is current with `main` (`git merge --ff-only main` succeeds, or you rebased)
- [ ] Regression tests pass locally
- [ ] No one-shot migration workflow left in `.github/workflows/`
- [ ] Docs updated if the change alters the production contract, cache keys, or model version

After merging:

- [ ] Head branch deleted (automatic if the repo setting in section 2 is on)
- [ ] Model branches fast-forwarded and pushed (section 3)

---

## 9. Quick reference

```bash
# What is actually unmerged anywhere?
git branch -a --no-merged main

# Is this branch safe to delete?
git merge-base --is-ancestor <branch> main && echo SAFE

# Catch a model branch up to main
git checkout <model-branch> && git merge --ff-only main && git push

# Record remote SHAs before any cleanup
git for-each-ref --format='%(refname:short) = %(objectname)' refs/remotes/origin

# Prune dead remote-tracking refs
git fetch --prune

# See branches by staleness
git for-each-ref --sort=-committerdate \
  --format='%(committerdate:short)  %(refname:short)' refs/heads refs/remotes/origin
```
