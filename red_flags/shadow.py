"""Counterfactual red-flag policy output that never mutates live scoring."""

from __future__ import annotations

import pandas as pd


# Keep the red-flag worker's dependency surface small. Importing the full
# screener scoring module also imports market-data clients that this worker
# deliberately does not install.
RATING_ORDER = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "REDUCE": 3, "SELL": 4}


class RedFlagShadowSimulator:
    """Show what confirmed severe evidence would do to a recommendation.

    VIGIL is a discovery feed. Its rows trigger review; they are not treated as
    independently verified issuer facts. The simulator therefore labels all
    changes "if confirmed" and preserves Final_Score and Rating.
    """

    def simulate(self, scored_df):
        simulated = scored_df.copy()
        base_scores = pd.to_numeric(
            simulated.get("Final_Score", pd.Series(float("nan"), index=simulated.index)),
            errors="coerce",
        )
        base_ratings = simulated.get(
            "Rating", pd.Series("", index=simulated.index, dtype=object)
        ).astype(str)
        issuer = pd.to_numeric(
            simulated.get("Red_Flag_Issuer_Severity", pd.Series(0, index=simulated.index)),
            errors="coerce",
        ).fillna(0)
        trading = pd.to_numeric(
            simulated.get("Red_Flag_Trading_Severity", pd.Series(0, index=simulated.index)),
            errors="coerce",
        ).fillna(0)
        current = simulated.get(
            "Red_Flag_Status", pd.Series("No coverage", index=simulated.index)
        ).eq("Available")

        simulated["Shadow_Red_Flag_Review_Required"] = current & ((issuer >= 2) | (trading >= 2))
        simulated["Shadow_Red_Flag_Rating_Cap_If_Confirmed"] = "None"
        buy_cap = current & ((issuer == 2) | (trading == 2))
        hold_cap = current & ((issuer >= 3) | (trading >= 3))
        simulated.loc[buy_cap, "Shadow_Red_Flag_Rating_Cap_If_Confirmed"] = "BUY"
        simulated.loc[hold_cap, "Shadow_Red_Flag_Rating_Cap_If_Confirmed"] = "HOLD"

        hypothetical_scores = base_scores.copy()
        issuer_hard_stop = current & issuer.ge(3)
        hypothetical_scores.loc[issuer_hard_stop] = hypothetical_scores.loc[
            issuer_hard_stop
        ].clip(upper=59.99)
        simulated["Shadow_Red_Flag_Score_If_Confirmed"] = hypothetical_scores.round(2)

        hypothetical_ratings = base_ratings.copy()
        for index in simulated.index[buy_cap]:
            hypothetical_ratings.at[index] = _apply_rating_cap(base_ratings.at[index], "BUY")
        for index in simulated.index[hold_cap]:
            hypothetical_ratings.at[index] = _apply_rating_cap(base_ratings.at[index], "HOLD")
        simulated["Shadow_Red_Flag_Rating_If_Confirmed"] = hypothetical_ratings

        actions = pd.Series("No current red-flag action", index=simulated.index, dtype=object)
        actions.loc[current & issuer.eq(1)] = "Monitor issuer filing evidence"
        actions.loc[current & issuer.eq(2)] = "Review issuer evidence before acting"
        actions.loc[current & issuer.ge(3)] = "Verify issuer filing; hard cap if confirmed"
        actions.loc[current & trading.eq(1) & issuer.lt(2)] = "Monitor exchange surveillance"
        actions.loc[current & trading.eq(2) & issuer.lt(2)] = "Liquidity/trading review required"
        actions.loc[current & trading.ge(3) & issuer.lt(3)] = (
            "Verify exchange restriction; rating cap if confirmed"
        )
        actions.loc[~current & (issuer.gt(0) | trading.gt(0))] = (
            "Stale/partial evidence; refresh before review"
        )
        simulated["Shadow_Red_Flag_Action"] = actions
        simulated["Shadow_Red_Flag_Would_Change"] = (
            hypothetical_scores.ne(base_scores) | hypothetical_ratings.ne(base_ratings)
        )
        return simulated


def _apply_rating_cap(rating: str, cap: str) -> str:
    rating_order = RATING_ORDER.get(rating, len(RATING_ORDER))
    cap_order = RATING_ORDER[cap]
    return cap if rating_order < cap_order else rating
