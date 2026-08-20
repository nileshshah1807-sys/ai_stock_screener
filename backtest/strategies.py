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


def attach_market_relative(frame, *, benchmark_return_6m=None,
                           benchmark_return_12m=None):
    """Market-relative 6-month strength.

    The benchmark is the equal-weight median of the cross-section itself rather
    than an index, because the eligible universe *is* the comparison the model
    makes. Using an index would fold a size bet into a momentum measurement.
    """
    working = frame.copy()

    def column(name):
        # ``frame.get`` returns None for an absent column, and pd.to_numeric on
        # None yields a scalar NaN rather than a Series -- which then blows up
        # on ``.notna()``. An absent input must produce an all-NaN column so the
        # gate reading it fails on absence instead of crashing.
        values = working.get(name)
        if values is None:
            return pd.Series(np.nan, index=working.index, dtype=float)
        return pd.to_numeric(values, errors="coerce")

    six_month = column("Momentum_6_1_Pct")
    reference = (
        float(benchmark_return_6m)
        if benchmark_return_6m is not None
        else float(six_month.median())
        if six_month.notna().any()
        else np.nan
    )
    working["RS_Market_6M_Pct"] = six_month - reference

    # The STRONG BUY gate reads a 12-month relative strength on the same basis.
    twelve_month = column("Pct_Change_12M")
    reference_12m = (
        float(benchmark_return_12m)
        if benchmark_return_12m is not None
        else float(twelve_month.median())
        if twelve_month.notna().any()
        else np.nan
    )
    working["RS_Market_12M_Pct"] = twelve_month - reference_12m
    return working


class Strategy:
    """A named scoring rule over a point-in-time cross-section.

    ``score`` may accept a ``shared`` mapping of work already done for this
    cross-section. The runner scores Model 5.0 once per rebalance and passes it
    through, so the five block-level ablations read from that result instead of
    recomputing the whole factor model five more times.
    """

    name = "abstract"
    #: Whether this strategy reads ``shared["model_5"]``.
    needs_model5 = False

    def score(self, frame, shared=None):  # pragma: no cover - interface
        raise NotImplementedError


class MomentumOnly(Strategy):
    """Production momentum block minus its sector-relative term."""

    name = "momentum_only"

    def score(self, frame, shared=None):
        working = attach_market_relative(frame)
        score, coverage = weighted_block(working, MOMENTUM_PRICE_FEATURES)
        working["Score"] = score
        working["Score_Coverage"] = coverage
        return working


class RiskOnly(Strategy):
    """Production risk block, price-derived inputs only."""

    name = "risk_only"

    def score(self, frame, shared=None):
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

    def score(self, frame, shared=None):
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

    def score(self, frame, shared=None):
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

    def score(self, frame, shared=None):
        import hashlib

        working = frame.copy()
        # Seeded per signal date so the null varies across dates -- one seed for
        # the whole run would impose the same ordering every month and create
        # artificial serial correlation in a benchmark that must have none.
        #
        # The digest is blake2b rather than the builtin hash(): Python randomises
        # string hashing per process, so hash() gave a different null on every
        # invocation. The measured "no signal" baseline has to be reproducible or
        # it cannot calibrate anything.
        signal = str(working.get("Signal_Date", pd.Series(["x"])).iloc[0])
        digest = hashlib.blake2b(
            f"{self.seed}:{signal}".encode("utf-8"), digest_size=8
        ).digest()
        generator = np.random.default_rng(int.from_bytes(digest, "big") % (2**32))
        working["Score"] = generator.uniform(0, 100, len(working))
        working["Score_Coverage"] = 1.0
        return working


def _model5_result(frame, shared):
    """The shared Model 5.0 scoring for this cross-section, computing it only if
    the runner did not already."""
    if shared is not None and "model_5" in shared:
        return shared["model_5"].copy()
    return Model5().score(frame)


class Model5(Strategy):
    """The production Model 5.0 score, run on point-in-time evidence.

    Delegates to `screener.factors.FactorModel` unchanged. That is the whole
    point of the exercise -- a reimplementation would be testing a lookalike, and
    the only defensible answer to "does Model 5.0 predict returns" comes from
    running the object that makes the production decision.

    Two documented departures from the production configuration, both forced by
    what the archive carries rather than chosen:

    * **Ranking is market-wide, not sector-neutral.** The bhavcopy has no sector
      classification, and the obvious substitute -- today's sector map from the
      production fundamental cache -- exists only for companies still listed
      today. Joining it would quietly reintroduce the survivorship bias the whole
      archive was built to remove, since delisted names would fall into an
      "Unknown" bucket and be ranked against each other. Ranking market-wide is
      a real methodological difference and is stated, not hidden.
    * **The DCF block is disabled.** It needs free cash flow, and the filings
      carry operating cash flow with no capital expenditure. Its weight is
      redistributed by the block's own coverage machinery rather than being
      filled with a guess.
    """

    name = "model_5"
    produces_model5 = True

    def __init__(self, config=None):
        self.config = config or self._default_config()

    @staticmethod
    def _default_config():
        from screener.runtime import Config

        class BacktestConfig:
            pass

        config = BacktestConfig()
        for attribute in dir(Config):
            if attribute.startswith("FACTOR_"):
                setattr(config, attribute, getattr(Config, attribute))
        # See the class docstring: no point-in-time sector map exists that does
        # not smuggle survivorship back in.
        config.FACTOR_SECTOR_NEUTRAL = False
        return config

    def score(self, frame, shared=None):
        from screener.factors import FactorModel

        working = attach_market_relative(frame)
        working = self._prepare(working)
        # FactorModel recomputes RS_Market_6M/12M from market_context and
        # overwrites whatever the caller attached. Passing no context left both
        # terms NaN for every security, silently deleting 15% of the momentum
        # block (and 20% more via the absent sector map) from every model_5
        # result. The benchmark is the cross-sectional median, the same basis
        # attach_market_relative uses -- the eligible universe is the comparison
        # the model makes, and an index would fold a size bet into it.
        scored = FactorModel(self.config).score(
            working, market_context=self._market_context(working)
        )
        scored["Score"] = scored["Research_Score"]
        scored["Score_Coverage"] = scored[
            ["Quality_Coverage", "Growth_Coverage", "Value_Coverage",
             "Momentum_Coverage", "Risk_Coverage"]
        ].mean(axis=1)
        return scored

    @staticmethod
    def _market_context(frame):
        context = {}
        for horizon, column in (("6M", "Pct_Change_6M"), ("12M", "Pct_Change_12M")):
            values = pd.to_numeric(frame.get(column), errors="coerce")
            if values is not None and getattr(values, "notna", lambda: None)() is not None:
                median = float(values.median()) if values.notna().any() else np.nan
            else:
                median = np.nan
            context[f"Benchmark_Return_{horizon}_Pct"] = median
        return context

    @staticmethod
    def _prepare(frame):
        """Supply the columns FactorModel expects but the archive cannot."""
        working = frame.copy()
        if "Sector" not in working:
            working["Sector"] = "Unknown"
        if "Fundamental_Model" not in working:
            # Every row scored on the generic template. The specialist bank and
            # NBFC templates need regulatory line items the results XBRL does not
            # carry, so routing financials there would score them on absence.
            working["Fundamental_Model"] = "Generic Fundamental Model"
        for column, default in (
            ("DCF_Blend_Eligible", False),
            ("DCF_Valuation_Score", np.nan),
            ("Trading_Frequency_60D", np.nan),
        ):
            if column not in working:
                working[column] = default
        if "DCF_Status" not in working:
            working["DCF_Status"] = "unavailable: no capex in the filing feed"
        # The production risk block reads Trading_Frequency_60D; the archive
        # computes the same quantity under a shorter name.
        if "Trading_Frequency" in working:
            working["Trading_Frequency_60D"] = working["Trading_Frequency_60D"].fillna(
                working["Trading_Frequency"]
            )
        return working


class Model5Gated(Strategy):
    """Model 5.0 ranked the way the dashboard ranks it -- gates included.

    Every other strategy here ranks on `Research_Score` alone. Production does
    not: `screener.recommendation` caps names that fail an eligibility gate and
    sorts `Eligibility_Class` first, `Research_Score` second. So the published
    top-20 is drawn from the gated ordering, and comparing this against
    `model_5` is the only way to learn whether the gates earn their place or
    merely cost return.

    The score published here is a rank surrogate, not a rating: eligible names
    keep their research score, and each failing class is pushed strictly below
    every better class. Ranking on the *capped* score directly would sort a
    column that is constant within a class -- the exact failure mode the
    production code comments on -- so the class offset preserves research order
    inside each band while eligibility still dominates across bands.

    See `backtest.gates` for which production gates are reproduced and which the
    archive cannot support.
    """

    name = "model_5_gated"
    needs_model5 = True

    #: Width of one eligibility band. Scores are 0-100, so a 1000-point step
    #: cannot be closed by any research-score difference.
    CLASS_OFFSET = 1000.0

    def __init__(self, config=None):
        from .gates import GateConfig

        self.config = config or GateConfig.from_runtime()

    def score(self, frame, shared=None):
        from .gates import apply_gates

        scored = _model5_result(frame, shared)
        regime = (shared or {}).get("market_regime")
        gated = apply_gates(scored, self.config, regime=regime)

        research = pd.to_numeric(gated["Score"], errors="coerce").fillna(0.0)
        klass = pd.to_numeric(gated["Eligibility_Class"], errors="coerce").fillna(3)
        gated["Score"] = research - klass * self.CLASS_OFFSET
        return gated


class QualityOnly(Strategy):
    """Model 5.0's quality block alone -- `p0.md` §7D."""

    name = "quality_only"

    needs_model5 = True

    def score(self, frame, shared=None):
        scored = _model5_result(frame, shared)
        scored["Score"] = scored["Quality_Score"]
        scored["Score_Coverage"] = scored["Quality_Coverage"]
        return scored


class GrowthOnly(Strategy):
    """Model 5.0's growth block alone -- `p0.md` §7 strategy 5."""

    name = "growth_only"

    needs_model5 = True

    def score(self, frame, shared=None):
        scored = _model5_result(frame, shared)
        scored["Score"] = scored["Growth_Score"]
        scored["Score_Coverage"] = scored["Growth_Coverage"]
        return scored


class ValueOnly(Strategy):
    """Model 5.0's value block alone -- `p0.md` §7F."""

    name = "value_only"

    needs_model5 = True

    def score(self, frame, shared=None):
        scored = _model5_result(frame, shared)
        scored["Score"] = scored["Value_Score"]
        scored["Score_Coverage"] = scored["Value_Coverage"]
        return scored


class SimpleQualityMomentum(Strategy):
    """The 50/50 challenger from `p0.md` §7G.

    Deliberately simple, and the most important comparison in the matrix: if a
    two-block average matches the full model, the extra complexity has not earned
    its place.
    """

    name = "simple_quality_momentum"

    needs_model5 = True

    def score(self, frame, shared=None):
        scored = _model5_result(frame, shared)
        quality = pd.to_numeric(scored["Quality_Score"], errors="coerce")
        momentum = pd.to_numeric(scored["Momentum_Score"], errors="coerce")
        scored["Score"] = 0.5 * quality.fillna(50.0) + 0.5 * momentum.fillna(50.0)
        scored["Score_Coverage"] = (
            scored["Quality_Coverage"] + scored["Momentum_Coverage"]
        ) / 2.0
        return scored


# Price-only strategies. Runnable without any fundamental data.
PRICE_ONLY_STRATEGIES = (
    MomentumOnly(),
    RiskOnly(),
    MomentumRiskBlend(),
    EqualWeightUniverse(),
    RandomRanking(),
)

# The full benchmark matrix, requiring the fundamental panel.
FUNDAMENTAL_STRATEGIES = (
    Model5(),
    Model5Gated(),
    QualityOnly(),
    GrowthOnly(),
    ValueOnly(),
    MomentumOnly(),
    SimpleQualityMomentum(),
    EqualWeightUniverse(),
    RandomRanking(),
)

DEFAULT_STRATEGIES = PRICE_ONLY_STRATEGIES
