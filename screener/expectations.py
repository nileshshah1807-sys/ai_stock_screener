"""Expectations-gap diagnostics: what the market prices, next to what we scored.

**Display-only. Nothing here enters `Research_Score`, `Decision_Score`, `Rating`
or any rank.** The module is deliberately called after `finalize_recommendations`
so it cannot influence the decision even by accident.

The gap it exists to expose
---------------------------

The factor model scores what has already been filed. `Statement_Latest_Period`
is a closed year; `EPS_CAGR_3Y` is history. The price is a claim about what gets
filed next. When those two disagree the model has no way to say so, because
every input it reads is on the backward-looking side of the disagreement.

LUPIN on 2026-08-24 is the case this was written for: rank 14 of 2,383,
`Research_Score` 99.45, trailing PE 18.13 -- and a forward PE of 21.40. Forward
above trailing has exactly one meaning: the market expects earnings to fall. The
implied forward EPS was Rs 102.22 against a trailing Rs 120.66, a 15.3% decline,
while the median stock in the same run was priced for +42.5%. The model scored
the Rs 120.66 and could not see the rest.

Why this is a diagnostic and not a factor
-----------------------------------------

`Forward_PE` is analyst consensus from Yahoo. Three things disqualify it as a
scored input, and only the third is about principle:

1. **Coverage is 45% and size-biased.** On the run above it was present for
   1,091 of 2,383 rows, median market cap Rs 10,068 Cr where present against
   Rs 523 Cr where absent -- a 19x gap. Inside `_block_score` a missing input
   lowers coverage and shrinks the block toward 50, so scoring it would compress
   the scores of the 55% of the universe that analysts do not cover, almost all
   of it small caps. That re-sorts the universe by analyst attention, which is a
   size proxy, and calls the result better ranking.
2. **It cannot be backtested.** `backtest/xbrl.py` parses filed results; consensus
   estimates are not filed with the exchange and Yahoo serves only today's
   snapshot. Scoring it would make `model_5` unreproducible against the archive
   and cost the ability to validate every *future* change, not just this one.
3. `docs/model_methodology.md` states the exclusion as policy: "no reliable
   point-in-time analyst-consensus and estimate-revision history ... therefore
   absent, not silently approximated."

Displaying it costs none of that. A reader who can see "the market prices a 15%
earnings decline" next to a 99.45 has the counter-argument the score cannot
carry, and the ranking stays reproducible.

The three signals
-----------------

* **Expected earnings change** -- forward EPS implied by `Forward_PE` against
  trailing `EPS`. Consensus, and labelled as such.
* **Implied growth gap** -- `DCF_Implied_FCF_CAGR` (what the market pays for)
  minus `DCF_Assumed_Growth` (what the sector template assumed). Derived from
  price and *reported* cash flow, so unlike the first signal this one needs no
  analyst at all.
* **Guidance transition** -- last quarter's guidance against this quarter's.
  Management withdrawing a commitment it made a quarter ago is a forward signal
  the transcript score cannot express, because v5.x applies transcript evidence
  only on the downside and "unclear" is not scored as adverse.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Guidance ordered from weakest to strongest commitment. "Unclear" sits below
# "maintained" deliberately: a management team that gave a number last quarter
# and declines to this quarter has withdrawn something, and the withdrawal is
# the information. The transition string always reports both raw words, so a
# reader who disagrees with this ordering can still see what actually happened.
GUIDANCE_RANK = {
    "lowered": 0,
    "unclear": 1,
    "maintained": 2,
    "raised": 3,
}

#: Solve states from the reverse DCF whose implied growth is an actual solution
#: rather than a censored bound. A bound means the solver walked off the end of
#: the configured interval; reporting it as "the market expects X" would state a
#: number the model never found.
USABLE_SOLVE_STATES = {"within_range"}


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series("", index=frame.index, dtype=object)
    return frame[column].fillna("").astype(str).str.strip()


def expected_earnings_change(
    price: pd.Series, forward_pe: pd.Series, trailing_eps: pd.Series
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Implied forward EPS, its change against trailing, and a status.

    Returns ``(forward_eps, change_pct, status)``. The status column is the
    point of the exercise: absence of a forward estimate must read as absence,
    never as "no expected decline". Four rows can produce no number, and they
    are not the same thing:

    * no consensus published -- 55% of the universe, mostly small caps
    * trailing loss -- the ratio has no meaning against a negative base
    * consensus expects a loss -- a real and adverse signal, but not a ratio
    * price unavailable
    """
    status = pd.Series("Unavailable: no forward estimate", index=price.index, dtype=object)
    forward_eps = pd.Series(np.nan, index=price.index, dtype=float)
    change = pd.Series(np.nan, index=price.index, dtype=float)

    have_price = price.notna() & (price > 0)
    status = status.mask(~have_price, "Unavailable: no completed price")

    have_fpe = have_price & forward_pe.notna()
    # A negative forward PE is consensus pricing a loss next year. It is adverse
    # evidence and must be surfaced, but it cannot be turned into a percentage
    # change against a positive base, so it gets its own terminal status.
    priced_for_loss = have_fpe & (forward_pe < 0)
    status = status.mask(priced_for_loss, "Priced for a loss")

    usable_fpe = have_fpe & (forward_pe > 0)
    forward_eps = forward_eps.mask(usable_fpe, price / forward_pe)

    have_base = usable_fpe & trailing_eps.notna() & (trailing_eps > 0)
    status = status.mask(
        usable_fpe & trailing_eps.notna() & (trailing_eps <= 0),
        "Unavailable: trailing loss",
    )
    change = change.mask(have_base, (forward_eps / trailing_eps - 1.0) * 100.0)
    return forward_eps, change, status


def implied_growth_gap(
    implied_cagr: pd.Series, assumed_growth: pd.Series, solve_state: pd.Series
) -> pd.Series:
    """Market-implied FCF growth minus the growth the DCF assumed, in points.

    Negative means the market pays for less growth than the valuation model
    credited the company with -- which is precisely why that model reports
    upside. Both inputs come from price and reported cash flow, so this signal
    is free of the coverage and backtestability problems that keep `Forward_PE`
    out of the score.
    """
    usable = (
        implied_cagr.notna()
        & assumed_growth.notna()
        & solve_state.str.lower().isin(USABLE_SOLVE_STATES)
    )
    gap = pd.Series(np.nan, index=implied_cagr.index, dtype=float)
    return gap.mask(usable, (implied_cagr - assumed_growth) * 100.0)


def guidance_transition(
    previous: pd.Series, current: pd.Series, eligible: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """``"raised -> unclear"`` and whether that is a step down.

    Only current-cycle transcripts qualify. A prior-cycle call compared against
    the one before it describes a transition that is two quarters stale, and
    the rest of the pipeline already treats prior-cycle evidence as neutral.
    """
    prev_clean = previous.str.lower()
    curr_clean = current.str.lower()
    known = (
        eligible
        & prev_clean.isin(GUIDANCE_RANK)
        & curr_clean.isin(GUIDANCE_RANK)
    )
    label = pd.Series("", index=previous.index, dtype=object)
    label = label.mask(known, prev_clean + " -> " + curr_clean)

    prev_rank = prev_clean.map(GUIDANCE_RANK)
    curr_rank = curr_clean.map(GUIDANCE_RANK)
    downgraded = known & (curr_rank < prev_rank)
    return label, downgraded.fillna(False)


def attach_expectations_gap(frame: pd.DataFrame, config=None) -> pd.DataFrame:
    """Attach the expectations-gap columns. Additive; changes nothing existing."""
    if frame is None or len(frame) == 0:
        return frame

    decline_warn = float(
        getattr(config, "EXPECTATIONS_EPS_DECLINE_WARN_PCT", -5.0)
    )

    working = frame.copy()

    forward_eps, change, status = expected_earnings_change(
        _numeric(working, "Current_Price"),
        _numeric(working, "Forward_PE"),
        _numeric(working, "EPS"),
    )
    have_change = change.notna()
    status = status.mask(have_change & (change <= decline_warn), "Priced for decline")
    status = status.mask(
        have_change & (change > decline_warn) & (change < 0.0), "Priced roughly flat"
    )
    status = status.mask(have_change & (change >= 0.0), "Priced for growth")

    working["Expected_EPS_Forward"] = forward_eps.round(2)
    working["Expected_EPS_Change_Pct"] = change.round(2)
    working["Expectations_Status"] = status

    gap = implied_growth_gap(
        _numeric(working, "DCF_Implied_FCF_CAGR"),
        _numeric(working, "DCF_Assumed_Growth"),
        _text(working, "DCF_Solve_State"),
    )
    working["Implied_Growth_Gap_Pct"] = gap.round(2)

    eligible = (
        working.get(
            "Transcript_Scoring_Eligible", pd.Series(False, index=working.index)
        )
        .fillna(False)
        .astype(bool)
    )
    label, downgraded = guidance_transition(
        _text(working, "Transcript_Previous_Guidance"),
        _text(working, "Transcript_Guidance"),
        eligible,
    )
    working["Guidance_Transition"] = label
    working["Guidance_Downgraded"] = downgraded

    # One sentence, only when there is something adverse to say. An empty string
    # on a healthy row keeps the column honest: a warning that fires on every
    # row is not a warning, and the dashboard renders nothing rather than a
    # reassurance the model has not earned.
    notes = pd.Series("", index=working.index, dtype=object)

    def append(current: pd.Series, mask: pd.Series, text: pd.Series) -> pd.Series:
        """Add one sentence where ``mask`` holds.

        Written as an accumulator rather than a pair of ``mask`` calls keyed on
        "is the note empty yet". That form reads the column it is in the middle
        of writing, so the second call sees the string the first just wrote and
        appends the same sentence twice.
        """
        addition = text.where(mask.fillna(False), "")
        return (current + " " + addition).str.strip()

    notes = append(
        notes,
        have_change & (change <= decline_warn),
        "Market prices a "
        + change.abs().round(1).astype(str)
        + "% earnings decline against trailing EPS; the score is computed on trailing.",
    )
    notes = append(
        notes,
        status.eq("Priced for a loss"),
        pd.Series(
            "Consensus expects a loss next year; the score is computed on "
            "reported trailing profit.",
            index=working.index,
        ),
    )
    # `Implied_Growth_Gap_Pct` is exported but deliberately does NOT raise a
    # warning. Measured across the 2026-08-24 run it is near-symmetric about
    # zero -- median +3.06, negative on 46.5% of the 901 rows that have it --
    # because `DCF_Assumed_Growth` is a sector template, not a company forecast.
    # A negative gap therefore says "this sector's template is optimistic
    # relative to the market", which is the normal state and true of nearly half
    # the universe. Wired to the warning at any useful threshold it fired on
    # 22.6% of rows and 9 of the top 12, which is wallpaper rather than a
    # warning. It stays a per-stock diagnostic, where "the DCF's upside rests on
    # an assumed 14.5% the market only pays 9.85% for" is exactly the right
    # thing to read next to that upside.
    notes = append(
        notes,
        downgraded,
        "Guidance moved " + label + " on the latest call.",
    )

    working["Expectations_Warning"] = notes
    return working
