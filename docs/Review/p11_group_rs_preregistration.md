# P11 -- NSE group relative strength (WNN-23)

Rules are Jim's, pre-registered in WNN-22 (`research/themes.md` on
`research-notes`, section 4). Committed before any scored run. This file
records how each rule was implemented; nothing here moves a threshold.

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
    python -m tools.build_group_map --root reports_advanced/backtest_ext
    python -m tools.run_p0_backtest --with-fundamentals --group-rs-grid \
        --root reports_advanced/backtest_ext --start 2018-12-31 --end 2026-09-30 \
        --horizons 1 --no-pdf --no-comparison --fills-out reports_advanced/p11_fills.csv
    python -m tools.p11_report reports_advanced/p11_fills.csv
