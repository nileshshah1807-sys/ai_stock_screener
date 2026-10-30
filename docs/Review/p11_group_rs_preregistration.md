# P11 -- NSE group relative strength (WNN-23)

Rules are Jim's, pre-registered in WNN-22 (`research/themes.md` on
`research-notes`, section 4). The rules were committed before the scored run:
WNN-22 on `research-notes`, and this implementation in `d0a961e` on
`study/p11-group-rs`. This file records how each rule was implemented, which
moves no threshold, and adds the 30 Oct 2026 result.

## Map
- Source: 15 Wayback Machine captures of NSE's `ind_nifty500list.csv`,
  4 Oct 2018 to 9 Oct 2026 (a 22 Oct 2026 capture did not download; it is
  after the last signal date). Built by `python -m tools.build_group_map`.
- Each capture is dated by its Wayback timestamp. A stock takes the label of
  the latest capture on or before the signal date that lists it; otherwise the
  first later one, flagged back-filled.
- Labels fold into 16 coarse groups (`backtest/groups.py:COARSE_GROUPS`),
  fixed from the label crosswalk of the 402 companies in both the Jul 2020 and
  May 2022 captures, before any return was looked at.
- **Coverage, measured before scoring** (model_5 universe, 94 month-ends,
  116,078 stock-months): mapped 48.9%, back-filled 4.3%, with a group reading
  (group of 8+ members) 48.7%. The kill rule's floor is 85%.

## Variables and variants
- `Group_RS_6M`: median `Pct_Change_6M` of the stock's group in that month's
  universe (8+ members), minus the universe median (model_5's benchmark).
  Ranking it is the same as ranking `Group_RS_Rank`.
- **A, score** (`model_5_group_score`): `Group_RS_6M` added to the momentum
  block at 0.20, `RS_Sector_6M_Pct`'s production weight, beside the existing
  inputs. Unmapped stocks have no reading (coverage-shrunk, not zero).
- **B, gate** (`model_5_group_gate`): groups ranked by `Group_RS_6M` each
  month; stocks in the bottom third of groups cannot enter the Top 20.
  Unmapped stocks are not held out.
- Each again with back-filled labels treated as unmapped (`*_no_backfill`).

## Judging (monthly Top 20, net of costs, base `model_5`)
- Pass: net CAGR >= model_5 + 2.0 points; max drawdown no more than 3 points
  deeper; CAGR above model_5 in Dec 2018 - Sep 2022 and Oct 2022 - Sep 2026
  signals.
- Kill: coverage < 85%; any pass test fails; more than half the excess return
  from one group (excess attributed by group from the 1/20 holdings of the
  variant minus model_5, summed over months); sign flips without back-filled
  names.
- Diagnostic, not judged: monthly Spearman correlation of `Group_RS_6M` with
  next-month return, alone and with the stock's own 6-month return
  partialled out.

## Command
The code (`backtest/groups.py`, `tools/build_group_map.py`,
`tools/p11_report.py`, the `--group-rs-grid` flag) lives on branch
`study/p11-group-rs`, not on main.

    python -m tools.build_group_map --root reports_advanced/backtest_ext
    python -m tools.run_p0_backtest --with-fundamentals --group-rs-grid \
        --root reports_advanced/backtest_ext --start 2018-12-31 --end 2026-09-30 \
        --horizons 1 --no-pdf --no-comparison --fills-out reports_advanced/p11_fills.csv
    python -m tools.p11_report reports_advanced/p11_fills.csv

## Result (30 Oct 2026) -- KILL, nothing adopted
Run at `d0a961e` (clean; `tools/p11_report.py` added after), 94 signals,
726 s. `p11_fills.csv` sha256 `0a8103316472fe92...`, `group_map.csv`
`784a800fee00c22c...`. The backtest JSON carries no run manifest.

| strategy | net CAGR | Dec18-Sep22 | Oct22-Sep26 | max DD | Sharpe |
|---|---|---|---|---|---|
| model_5 | 43.4 | 50.6 | 36.6 | -24.9 | 1.59 |
| A score | 38.8 | 47.7 | 30.6 | -24.9 | 1.46 |
| B gate | 37.7 | 43.8 | 32.0 | -26.0 | 1.41 |
| A, no back-fill | 40.3 | 49.7 | 31.8 | -25.6 | 1.53 |
| B, no back-fill | 41.1 | 47.1 | 35.5 | -24.9 | 1.50 |

- Coverage 48.9% of universe stock-months (53.3% of model_5's Top 20
  holdings): kill on its own.
- Both variants lose CAGR overall and in both halves; drawdown within 3 points.
- Excess is negative, so no group "supplies most of the gain". A's biggest
  loss is the unmapped bucket (-43.6 pts summed): adding a 0.20 input that
  half the universe lacks shrinks those names' momentum toward neutral.
- No sign flip without back-filled names (all still negative).
- Diagnostic: group RS does predict next-month return in India -- rank IC
  +0.048 (t 4.1), +0.041 (t 4.2) after the stock's own 6-month return -- but
  model_5's Top 20 does not gain from it after costs.
