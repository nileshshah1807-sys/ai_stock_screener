"""Stage analysis, relative-strength rating, and the entry-timing score.

`Research_Score` answers *how strong is the evidence for this company and its
stock*. It says nothing about *where the stock is in its cycle*: a name that
has already run 250% and is rolling over scores the same 100 as one that broke
out last week, because every trend input it reads looks back six to twelve
months. This module supplies the missing axis.

Two layers, deliberately separate:

* ``stage_features`` is **per security** and pure: adjusted closes in, a dict
  out. Production (`screener.data_collection`) and the point-in-time backtest
  (`backtest.features`) both call it, so the definition cannot drift between
  the number that is published and the number that was validated.
* ``attach_timing`` is **cross-sectional**: it ranks relative strength across
  the universe on the day and blends the timing score into ``Action_Score``.

Stage definition
----------------
Daily moving averages (50/150/200 sessions), calibrated against a third-party
stage screener's labels for the 2026-09-18 cross-section (1,398 matched names,
91% exact agreement; see `docs/Review/p3_stage_timing_preregistration.md`).
Rules are evaluated in order; the first that holds wins:

=================  =========================================================
``Stage 2``        close > MA50 > MA150 > MA200 and MA200 rising
``Stage 4``        close < MA200, MA200 falling, and MA150 below MA200 or
                   MA150 falling
``S2 Candidate``   close above MA150 and MA200 with MA150 rising -- the
                   Stage 2 structure, but not the full stack (usually a
                   pullback under MA50)
``Stage 3``        close below MA150 while the long averages are still
                   rising or still stacked; or below a falling MA200 before
                   MA150 has rolled over
``Stage 1``        anything else
=================  =========================================================

"Rising" and "falling" compare each average with its value 21 sessions earlier.

Relative strength
-----------------
``RS_Raw_Pct`` is the IBD-style weighted return
``0.4*R(63) + 0.2*R(126) + 0.2*R(189) + 0.2*R(252)`` in percent; its
cross-sectional percentile is ``RS_Rating`` (1-99). The same calibration found a
Spearman correlation of 0.976 against the third-party RS percentile.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STAGE_1 = "Stage 1"
STAGE_2 = "Stage 2"
S2_CANDIDATE = "S2 Candidate"
STAGE_3 = "Stage 3"
STAGE_4 = "Stage 4"

STAGE_LABELS = (STAGE_1, STAGE_2, S2_CANDIDATE, STAGE_3, STAGE_4)

#: Stages that belong to an advance. ``Advance_Age_Days`` counts a continuous
#: run inside this set, so a pullback under MA50 does not restart the clock the
#: way it restarts ``Days_In_Stage``.
ADVANCING_STAGES = frozenset({STAGE_2, S2_CANDIDATE})

#: Stages whose onset is the exit signal tested in P5
#: (`docs/Review/p5_stage_overlay_preregistration.md`): selling a holding the
#: session after it breaks into Stage 3 or 4 raised Sharpe and cut drawdowns in
#: both halves of 2018-2026. ``Breakdown_*`` describes the current unbroken run
#: inside this set, so a Stage 3 that deteriorates into Stage 4 keeps the date it
#: first broke down rather than looking like a fresh signal.
BREAKDOWN_STAGES = frozenset({STAGE_3, STAGE_4})

SLOPE_SESSIONS = 21
#: MA200 plus its slope lookback: below this the stage is undefined, not Stage 1.
MIN_STAGE_SESSIONS = 200 + SLOPE_SESSIONS

RS_HORIZONS = ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2))
RS_CHANGE_SESSIONS = 21

#: Stage component of the timing score. Declared in the P3 pre-registration
#: before the backtest ran; not fitted.
STAGE_SCORES = {
    STAGE_2: 100.0,
    S2_CANDIDATE: 70.0,
    STAGE_1: 40.0,
    STAGE_3: 20.0,
    STAGE_4: 0.0,
}

#: Timing-score component weights, also pre-declared.
TIMING_COMPONENT_WEIGHTS = {
    "Stage_Score": 0.40,
    "RS_Rating": 0.20,
    "RS_Trend_Score": 0.20,
    "Extension_Score": 0.20,
}

#: Extension above MA150 (percent) at which the extension score starts falling,
#: and where it reaches zero.
EXTENSION_FULL_PCT = 25.0
EXTENSION_ZERO_PCT = 75.0

# Descriptions of the chart, not instructions. The first version said ENTER /
# WAIT · extended / AVOID, and the P4 diagnostics contradicted the advice:
# inside the research top 50, names >50% above MA150 returned the MOST over the
# next 3-6 months (+13.4 points over 6M), and excluding Stage 3/4 from a
# quarterly top 20 cost 3.9 points a year in 2023-2026. A label that tells the
# reader to wait on the best-performing group is worse than no label.
ENTRY_UPTREND = "Stage 2 · uptrend"
ENTRY_PULLBACK = "Stage 2 · pullback"
ENTRY_STAGE_1 = "Stage 1 · basing"
ENTRY_STAGE_3 = "Stage 3 · topping"
ENTRY_STAGE_4 = "Stage 4 · downtrend"

STAGE_FEATURE_COLUMNS = (
    "Stage",
    "Days_In_Stage",
    "Stage_Entry_Date",
    "Stage_Entry_Price",
    "Stage_Run_Censored",
    "Advance_Age_Days",
    "Advance_Age_Censored",
    "Breakdown_Date",
    "Breakdown_Age_Days",
    "Breakdown_From",
    "Return_Since_Stage_Entry_Pct",
    "Stage2_Entry_Date",
    "Stage2_Entry_Price",
    "Stage2_Exit_Date",
    "Stage2_Entry_Censored",
    "Return_Since_Stage2_Entry_Pct",
    "MA150",
    "MA150_Slope_Pct",
    "Price_To_MA150_Pct",
    "Pct_From_52W_High",
    "Pct_Above_52W_Low",
    "RS_Raw_Pct",
    "RS_Raw_1M_Ago_Pct",
)


def _empty_features():
    out = {column: np.nan for column in STAGE_FEATURE_COLUMNS}
    out["Stage"] = None
    out["Stage_Entry_Date"] = None
    out["Stage_Run_Censored"] = None
    out["Advance_Age_Censored"] = None
    out["Breakdown_Date"] = None
    out["Breakdown_From"] = None
    out["Stage2_Entry_Date"] = None
    out["Stage2_Exit_Date"] = None
    out["Stage2_Entry_Censored"] = None
    return out


def _clean_closes(closes, dates=None):
    series = pd.Series(closes, dtype=float) if not isinstance(closes, pd.Series) else closes
    if dates is not None:
        series = pd.Series(list(pd.to_numeric(series, errors="coerce")),
                           index=pd.to_datetime(list(dates)))
    series = pd.to_numeric(series, errors="coerce")
    series = series[series > 0].dropna()
    if isinstance(series.index, pd.DatetimeIndex) and series.index.tz is not None:
        # Exchange-local calendar dates; the timezone is irrelevant to a count
        # of days and would make the entry date print with an offset.
        series.index = series.index.tz_localize(None)
    return series


def classify_stages(closes):
    """Stage label for every session of ``closes`` (None before it is defined).

    Vectorised over one security's history so the current run's start date can
    be found without re-running the rules session by session.
    """
    values = pd.to_numeric(pd.Series(closes), errors="coerce")
    ma50 = values.rolling(50, min_periods=50).mean()
    ma150 = values.rolling(150, min_periods=150).mean()
    ma200 = values.rolling(200, min_periods=200).mean()
    slope150 = ma150 / ma150.shift(SLOPE_SESSIONS) - 1.0
    slope200 = ma200 / ma200.shift(SLOPE_SESSIONS) - 1.0

    defined = ma200.notna() & slope200.notna() & slope150.notna() & values.notna()
    stage_2 = (values > ma50) & (ma50 > ma150) & (ma150 > ma200) & (slope200 > 0)
    stage_4 = (
        (values < ma200) & (slope200 < 0) & ((ma150 < ma200) | (slope150 < 0))
    )
    candidate = (values > ma150) & (values > ma200) & (slope150 > 0)
    stage_3 = (
        (values < ma150) & ((slope150 > 0) | (slope200 > 0) | (ma150 > ma200))
    ) | ((values < ma200) & (slope200 < 0))

    labels = np.select(
        [~defined, stage_2, stage_4, candidate, stage_3],
        [None, STAGE_2, STAGE_4, S2_CANDIDATE, STAGE_3],
        default=STAGE_1,
    )
    return pd.Series(labels, index=values.index, dtype=object)


def _run_start(labels, members):
    """Index position where the current run of ``members`` began."""
    inside = labels.isin(members).to_numpy()
    if not len(inside) or not inside[-1]:
        return None
    outside = np.flatnonzero(~inside)
    return int(outside[-1] + 1) if len(outside) else 0


def _latest_stage_2_entry(labels):
    """The most recent advance that reached Stage 2: where it entered Stage 2,
    and where the advance ended (``None`` while it is still running).

    An advance is an unbroken run inside ``ADVANCING_STAGES``, so a pullback to
    S2 Candidate does not end it -- the same definition ``Advance_Age_Days``
    uses. Returns ``(run_start, stage_2_entry, run_end)`` as index positions, or
    ``None`` if the history holds no Stage 2 session at all.
    """
    stage_2 = np.flatnonzero((labels == STAGE_2).to_numpy())
    if not len(stage_2):
        return None
    last_stage_2 = int(stage_2[-1])
    advancing = labels.isin(ADVANCING_STAGES).to_numpy()
    before = np.flatnonzero(~advancing[:last_stage_2])
    run_start = int(before[-1] + 1) if len(before) else 0
    after = np.flatnonzero(~advancing[last_stage_2:])
    run_end = last_stage_2 + int(after[0]) if len(after) else None
    entry = run_start + int(np.flatnonzero((labels.iloc[run_start:] == STAGE_2).to_numpy())[0])
    return run_start, entry, run_end


def _calendar_days(index, start_position):
    if isinstance(index, pd.DatetimeIndex):
        return int((index[-1] - index[start_position]).days)
    # No dates supplied: sessions are the only honest unit available.
    return int(len(index) - 1 - start_position)


def _weighted_return_pct(values):
    """IBD-style weighted return in percent, or NaN without a full year."""
    if len(values) <= max(sessions for sessions, _ in RS_HORIZONS):
        return np.nan
    last = float(values.iloc[-1])
    total = 0.0
    for sessions, weight in RS_HORIZONS:
        base = float(values.iloc[-1 - sessions])
        if not base > 0:
            return np.nan
        total += weight * (last / base - 1.0)
    return total * 100.0


def stage_features(closes, dates=None):
    """Stage, extension and raw relative-strength inputs for one security.

    ``closes`` are split/dividend-adjusted, oldest first. With a DatetimeIndex
    (or ``dates``) the day counts are calendar days, matching how stage
    screeners report "days in stage"; without dates they fall back to sessions.
    Every output is NaN/None when its lookback is not fully available.
    """
    out = _empty_features()
    values = _clean_closes(closes, dates)
    if values.empty:
        return out
    price = float(values.iloc[-1])

    if len(values) >= 150:
        ma150 = values.rolling(150).mean()
        out["MA150"] = round(float(ma150.iloc[-1]), 2)
        out["Price_To_MA150_Pct"] = round((price / float(ma150.iloc[-1]) - 1.0) * 100.0, 3)
        if len(values) >= 150 + SLOPE_SESSIONS:
            prior = float(ma150.iloc[-1 - SLOPE_SESSIONS])
            out["MA150_Slope_Pct"] = round((float(ma150.iloc[-1]) / prior - 1.0) * 100.0, 4)

    if len(values) >= 252:
        window = values.iloc[-252:]
        out["Pct_From_52W_High"] = round((price / float(window.max()) - 1.0) * 100.0, 3)
        out["Pct_Above_52W_Low"] = round((price / float(window.min()) - 1.0) * 100.0, 3)

    out["RS_Raw_Pct"] = _weighted_return_pct(values)
    if len(values) > RS_CHANGE_SESSIONS:
        out["RS_Raw_1M_Ago_Pct"] = _weighted_return_pct(values.iloc[:-RS_CHANGE_SESSIONS])

    if len(values) < MIN_STAGE_SESSIONS:
        return out

    labels = classify_stages(values.reset_index(drop=True))
    labels.index = values.index
    current = labels.iloc[-1]
    if current is None:
        return out
    out["Stage"] = current

    start = _run_start(labels, {current})
    first_defined = int(np.flatnonzero(labels.notna().to_numpy())[0])
    out["Days_In_Stage"] = _calendar_days(values.index, start)
    out["Stage_Entry_Price"] = round(float(values.iloc[start]), 2)
    if isinstance(values.index, pd.DatetimeIndex):
        out["Stage_Entry_Date"] = values.index[start].date().isoformat()
    # A run that began on the first classifiable session may have begun
    # earlier: the count is a floor, not a measurement.
    out["Stage_Run_Censored"] = bool(start <= first_defined)
    out["Return_Since_Stage_Entry_Pct"] = round(
        (price / float(values.iloc[start]) - 1.0) * 100.0, 2
    )

    # "When did it enter Stage 2, and what has it done since?" -- answered for
    # the latest advance whether or not it is still running, so a stock that
    # has since broken down still shows where its last advance began and ended.
    latest = _latest_stage_2_entry(labels)
    if latest is not None:
        run_start, entry, run_end = latest
        entry_price = float(values.iloc[entry])
        out["Stage2_Entry_Price"] = round(entry_price, 2)
        out["Return_Since_Stage2_Entry_Pct"] = round((price / entry_price - 1.0) * 100.0, 2)
        # An advance already under way when the data begins may have entered
        # Stage 2 earlier than we can see: the date is then an upper bound.
        out["Stage2_Entry_Censored"] = bool(run_start <= first_defined)
        if isinstance(values.index, pd.DatetimeIndex):
            out["Stage2_Entry_Date"] = values.index[entry].date().isoformat()
            if run_end is not None:
                out["Stage2_Exit_Date"] = values.index[run_end].date().isoformat()

    if current in ADVANCING_STAGES:
        advance_start = _run_start(labels, ADVANCING_STAGES)
        out["Advance_Age_Days"] = _calendar_days(values.index, advance_start)
        # Production downloads two years, so a long advance can predate the
        # first classifiable session: the age is then a floor. Found on
        # VENUSREM, which reads 406 days from a two-year download and 476 from
        # the archive.
        out["Advance_Age_Censored"] = bool(advance_start <= first_defined)

    if current in BREAKDOWN_STAGES:
        breakdown_start = _run_start(labels, BREAKDOWN_STAGES)
        # Only a break that happened inside the data is reported. A breakdown
        # older than the download has no knowable date, and an alert must fire
        # on a transition that was actually observed, never on a guess.
        if breakdown_start > first_defined:
            out["Breakdown_Age_Days"] = _calendar_days(values.index, breakdown_start)
            out["Breakdown_From"] = labels.iloc[breakdown_start - 1]
            if isinstance(values.index, pd.DatetimeIndex):
                out["Breakdown_Date"] = values.index[breakdown_start].date().isoformat()
    return out


def _percentile_rating(values):
    """Cross-sectional percentile on a 1-99 scale; NaN stays NaN."""
    numeric = pd.to_numeric(values, errors="coerce")
    ranked = numeric.rank(pct=True, method="average")
    return (1.0 + 98.0 * ranked).where(numeric.notna())


def extension_score(price_to_ma150_pct):
    """100 up to EXTENSION_FULL_PCT above MA150, falling linearly to 0.

    A close below MA150 scores a neutral 50: that case is already priced by the
    stage component, and scoring it again here would count it twice.
    """
    x = pd.to_numeric(price_to_ma150_pct, errors="coerce")
    span = EXTENSION_ZERO_PCT - EXTENSION_FULL_PCT
    falling = 100.0 * (EXTENSION_ZERO_PCT - x) / span
    score = falling.clip(lower=0.0, upper=100.0)
    score = score.where(x >= 0, 50.0)
    return score.where(x.notna())


_ENTRY_BY_STAGE = {
    STAGE_2: ENTRY_UPTREND,
    S2_CANDIDATE: ENTRY_PULLBACK,
    STAGE_1: ENTRY_STAGE_1,
    STAGE_3: ENTRY_STAGE_3,
    STAGE_4: ENTRY_STAGE_4,
}


def entry_state(stage):
    """The stage in words. Extension and RS change no longer qualify it: both
    were tested in P4 and neither pointed the way the old labels assumed."""
    if stage is None or (isinstance(stage, float) and pd.isna(stage)):
        return None
    return _ENTRY_BY_STAGE.get(stage)


def attach_timing(frame, *, timing_weight=0.0, research_column="Research_Score"):
    """Add RS rating, timing components, Timing_Score and Action_Score.

    ``Action_Score = (1 - w) * research + w * Timing_Score``. A security whose
    timing cannot be computed (too little history) is blended at a neutral 50,
    the same rule the factor blocks apply to absent evidence: absence lowers
    confidence, it does not assert the worst.
    """
    working = frame.copy()
    for column in STAGE_FEATURE_COLUMNS:
        if column not in working:
            working[column] = (
                None
                if column in (
                    "Stage", "Stage_Entry_Date", "Breakdown_Date", "Breakdown_From",
                    "Stage2_Entry_Date", "Stage2_Exit_Date",
                )
                else np.nan
            )

    working["RS_Rating"] = _percentile_rating(working["RS_Raw_Pct"]).round(1)
    prior_rating = _percentile_rating(working["RS_Raw_1M_Ago_Pct"])
    working["RS_Rating_Change_1M"] = (working["RS_Rating"] - prior_rating).round(1)

    working["Stage_Score"] = working["Stage"].map(STAGE_SCORES).astype(float)
    working["RS_Trend_Score"] = _percentile_rating(working["RS_Rating_Change_1M"]).round(1)
    working["Extension_Score"] = extension_score(working["Price_To_MA150_Pct"]).round(1)

    numerator = pd.Series(0.0, index=working.index)
    denominator = pd.Series(0.0, index=working.index)
    for column, weight in TIMING_COMPONENT_WEIGHTS.items():
        values = pd.to_numeric(working[column], errors="coerce")
        present = values.notna()
        numerator = numerator + values.fillna(0.0) * weight
        denominator = denominator + present.astype(float) * weight
    timing = (numerator / denominator.where(denominator > 0)).round(2)
    # Without a stage the remaining components describe momentum, which the
    # research score already carries; a timing score built from them alone
    # would be a second momentum vote wearing a different name.
    working["Timing_Score"] = timing.where(working["Stage_Score"].notna())

    weight = float(timing_weight or 0.0)
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"timing_weight must be within [0, 1], got {weight}")
    working["Timing_Weight"] = weight
    if research_column in working:
        research = pd.to_numeric(working[research_column], errors="coerce")
        working["Action_Score"] = (
            (1.0 - weight) * research + weight * working["Timing_Score"].fillna(50.0)
        ).round(2).where(research.notna())
    else:
        working["Action_Score"] = np.nan

    working["Entry_State"] = [entry_state(stage) for stage in working["Stage"]]
    return working
