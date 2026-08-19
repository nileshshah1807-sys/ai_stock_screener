"""Price-only strategies and benchmarks for the Phase A milestone.

These exist to answer `p0.md` §7E -- *is Model 5.0 primarily a momentum strategy
with fundamental decoration?* -- before any point-in-time fundamental data is
available. The momentum and risk blocks need only price history, and the
equal-weight eligible-universe benchmark needs only the universe, so both come
straight from the bhavcopy archive.

The momentum weights are the production weights from
`screener.factors.MOMENTUM_FEATURES`, with one documented omission:
``RS_Sector_6M_Pct`` (weight 0.20) requires sector classification, which the
bhavcopy does not carry. The remaining four inputs are renormalised over the 0.80
that is left. A momentum-only result from this module is therefore *not* the
production momentum block exactly -- it is that block without its sector-relative
term, and any comparison must say so.

Scoring reuses `screener.factors._block_score` rather than reimplementing the
composite. It is private by naming convention, but copying the coverage-shrinkage
arithmetic here would let the two drift apart, and a divergence between the
ablation's scorer and production's would silently become part of every comparison.
Reusing it means the only difference between a run here and the production block
is the input set, which is the thing being tested.

Note that the production percentile is a pure rank transform with no
winsorization: `FACTOR_WINSOR_LOWER_PCT` / `FACTOR_WINSOR_UPPER_PCT` exist in
config but are read by nothing. Rank transforms bound outlier influence anyway, so
nothing here compensates for their absence.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# (column, weight, higher_is_better) -- production MOMENTUM_FEATURES minus the
# sector-relative term, renormalised over the surviving 0.80.
MOMENTUM_PRICE_FEATURES = (
    ("RiskAdj_Momentum_12_1", 0.30 / 0.80, True),
    ("RiskAdj_Momentum_6_1", 0.25 / 0.80, True),
    ("RS_Market_6M_Pct", 0.15 / 0.80, True),
    ("Trend_Quality_R2", 0.10 / 0.80, True),
)

# Production RISK_FEATURES minus Trading_Frequency_60D's exact definition, which
# is approximated here by Trading_Frequency from the archive.
RISK_PRICE_FEATURES = (
    ("Volatility_Ann_Pct", 0.25, False),
    ("Max_Drawdown_1Y_Pct", 0.20, True),
    ("Trading_Frequency", 0.20, True),
    ("Downside_Deviation_Pct", 0.15, False),
    ("Gap_Risk_Pct", 0.10, False),
    ("Return_Concentration_1Y", 0.10, False),
)


def weighted_block(frame, features, *, min_coverage=0.50, min_group=8, groups=None):
    """Coverage-shrunk weighted percentile composite, via the production scorer.

    Delegates to `screener.factors._block_score`, which applies the production
    rule that absence lowers confidence rather than asserting the worst: a missing
    input leaves both the numerator and the denominator, and the block is then
    shrunk toward neutral 50 by its own coverage.

    ``groups`` is None by default because the bhavcopy archive carries no sector
    classification. Production ranks inside sector; these price-only ablations
    rank market-wide. That is a real difference and is stated in the run report
    rather than hidden.
    """
    from screener.factors import _block_score

    score, coverage, _sufficient, _percentiles = _block_score(
        frame,
        features,
        groups,
        min_group=int(min_group),
        min_coverage=float(min_coverage),
    )
    return score, coverage


def attach_market_relative(frame, *, benchmark_return_6m=None):
    """Market-relative 6-month strength.

    The benchmark is the equal-weight median of the cross-section itself rather
    than an index, because the eligible universe *is* the comparison the model
    makes. Using an index would fold a size bet into a momentum measurement.
    """
    working = frame.copy()
    six_month = pd.to_numeric(working.get("Momentum_6_1_Pct"), errors="coerce")
    reference = (
        float(benchmark_return_6m)
        if benchmark_return_6m is not None
        else float(six_month.median())
        if six_month.notna().any()
        else np.nan
    )
    working["RS_Market_6M_Pct"] = six_month - reference
    return working


class Strategy:
    """A named scoring rule over a point-in-time cross-section."""

    name = "abstract"

    def score(self, frame):  # pragma: no cover - interface
        raise NotImplementedError


class MomentumOnly(Strategy):
    """Production momentum block minus its sector-relative term."""

    name = "momentum_only"

    def score(self, frame):
        working = attach_market_relative(frame)
        score, coverage = weighted_block(working, MOMENTUM_PRICE_FEATURES)
        working["Score"] = score
        working["Score_Coverage"] = coverage
        return working


class RiskOnly(Strategy):
    """Production risk block, price-derived inputs only."""

    name = "risk_only"

    def score(self, frame):
        working = frame.copy()
        score, coverage = weighted_block(working, RISK_PRICE_FEATURES)
        working["Score"] = score
        working["Score_Coverage"] = coverage
        return working


class MomentumRiskBlend(Strategy):
    """Momentum and risk at their production relative weights (25 vs 5).

    The closest price-only approximation of Model 5.0 available before the
    fundamental blocks land. It is not Model 5.0 and must not be reported as it --
    quality, growth and value together carry 70% of the production score.
    """

    name = "momentum_risk_blend"

    def score(self, frame):
        working = attach_market_relative(frame)
        momentum, momentum_coverage = weighted_block(working, MOMENTUM_PRICE_FEATURES)
        risk, risk_coverage = weighted_block(working, RISK_PRICE_FEATURES)
        weights = {"momentum": 0.25, "risk": 0.05}
        total = sum(weights.values())
        numerator = momentum.fillna(50.0) * weights["momentum"] + risk.fillna(
            50.0
        ) * weights["risk"]
        working["Score"] = numerator / total
        working["Momentum_Score"] = momentum
        working["Risk_Score"] = risk
        working["Score_Coverage"] = (momentum_coverage + risk_coverage) / 2.0
        return working


class EqualWeightUniverse(Strategy):
    """The benchmark from `p0.md` §7B: every eligible name, equally weighted.

    Scores every security identically, so a portfolio drawn from it is the
    universe average. This controls for the size and breadth exposure that a
    small-cap-heavy strategy would otherwise be credited with.
    """

    name = "equal_weight_universe"

    def score(self, frame):
        working = frame.copy()
        working["Score"] = 50.0
        working["Score_Coverage"] = 1.0
        return working


class RandomRanking(Strategy):
    """A seeded random score -- the null hypothesis, made explicit.

    Not in `p0.md`, but worth running: it calibrates what a rank IC of "about
    zero" actually looks like on this universe and horizon, so a small positive
    IC can be judged against a measured null rather than an assumed one.
    """

    name = "random_ranking"

    def __init__(self, seed=7):
        self.seed = int(seed)

    def score(self, frame):
        working = frame.copy()
        # Seeded per signal date so the run is reproducible but not identical
        # across dates, which would create artificial serial correlation.
        signal = str(working.get("Signal_Date", pd.Series(["x"])).iloc[0])
        generator = np.random.default_rng(
            abs(hash((self.seed, signal))) % (2**32)
        )
        working["Score"] = generator.uniform(0, 100, len(working))
        working["Score_Coverage"] = 1.0
        return working


DEFAULT_STRATEGIES = (
    MomentumOnly(),
    RiskOnly(),
    MomentumRiskBlend(),
    EqualWeightUniverse(),
    RandomRanking(),
)
