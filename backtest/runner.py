"""Walk-forward orchestration.

Time moves only forward. For each rebalance date the runner builds the universe
that existed then, scores it on evidence available then, fills at the next
session's open, and measures the outcome. No step may consult a later date, and
the point-in-time boundary lives in exactly one place -- `HistoryPanel.slice_upto`
-- so it can be audited rather than trusted.

Weights are frozen for this pass, per `p0.md` §4. Expanding-window recalibration
is a separate later experiment; mixing it in here would make the first result
un-interpretable, because a good number could come from the ranking or from the
refitting and there would be no way to tell which.

Every strategy in a run shares the same rebalance dates, universe, price
snapshots, execution convention and cost model. `p0.md` §7 is explicit that
letting those differ means comparing the model and the execution rules together.
"""

from __future__ import annotations

from datetime import date, datetime
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .execution import ExecutionModel, PricePanel, attach_forward_returns, coverage_report
from .features import HistoryPanel, build_cross_section
from .metrics import (
    bucket_returns,
    bucket_spread,
    ic_summary,
    monotonicity,
    portfolio_metrics,
    rank_ic,
    turnover,
)

logger = logging.getLogger(__name__)

MONTHLY = "monthly"
QUARTERLY = "quarterly"

DEFAULT_HORIZONS = (1, 3, 6, 12)
DEFAULT_PORTFOLIO_SIZES = (10, 20, 50)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def rebalance_dates(calendar, start, end, frequency=MONTHLY):
    """Last confirmed session of each period in ``[start, end]``.

    The last session of the month is the signal date; the fill is the first
    session of the next month. Using the last *confirmed* session rather than a
    nominal month-end means a month ending on a holiday still rebalances on a real
    session.
    """
    start, end = _as_date(start), _as_date(end)
    sessions = [day for day in calendar.sessions if start <= day <= end]
    if not sessions:
        return []
    if frequency == QUARTERLY:
        key = lambda day: (day.year, (day.month - 1) // 3)
    elif frequency == MONTHLY:
        key = lambda day: (day.year, day.month)
    else:
        raise ValueError(f"unsupported rebalance frequency {frequency!r}")

    last_by_period = {}
    for day in sessions:
        last_by_period[key(day)] = day
    return [last_by_period[period] for period in sorted(last_by_period)]


class UniverseRule:
    """Point-in-time eligibility, applied before any scoring.

    Liquidity is the operative filter. A name that traded 40 lakh a day cannot be
    held at size, and leaving it in the cross-section inflates the top decile with
    positions the strategy could never actually take.

    ETFs are excluded structurally rather than by name. Indian ISINs encode the
    instrument class in their third character: ``INE`` is a company security,
    ``INF`` is a mutual-fund scheme -- which is what an ETF unit is. So
    ``NIFTYBEES`` (``INF204KB14I2``) and ``GOLDBEES`` (``INF204KB17I5``) are
    excluded while ``RELIANCE`` (``INE002A01018``) is kept, with no name patterns
    and no dependence on a snapshot of today's ETF list. That matters for a
    historical run: a list fetched now would miss ETFs that delisted years ago,
    whereas the ISIN prefix was correct on every date.

    This also explains the reused-ticker warnings from the security master -- ETF
    schemes are renumbered on scheme changes, and every reused ticker observed in
    the archive belonged to a fund rather than a company.
    """

    def __init__(
        self,
        *,
        min_median_turnover_inr=2_000_000.0,
        min_trading_frequency=0.80,
        min_history_sessions=200,
        require_identifier_prefix="INE",
        exclude_symbols=(),
    ):
        self.min_median_turnover_inr = float(min_median_turnover_inr)
        self.min_trading_frequency = float(min_trading_frequency)
        self.min_history_sessions = int(min_history_sessions)
        self.require_identifier_prefix = (
            str(require_identifier_prefix).strip().upper()
            if require_identifier_prefix
            else ""
        )
        self.exclude_symbols = {str(s).strip().upper() for s in exclude_symbols}

    def apply(self, frame):
        if frame is None or len(frame) == 0:
            return frame, {"input": 0, "eligible": 0}
        turnover_values = pd.to_numeric(
            frame.get("Median_Turnover_INR"), errors="coerce"
        )
        frequency = pd.to_numeric(frame.get("Trading_Frequency"), errors="coerce")
        history = pd.to_numeric(frame.get("Price_History_Sessions"), errors="coerce")
        symbols = frame.get("Symbol", pd.Series("", index=frame.index)).astype(str).str.upper()
        identifiers = (
            frame.get("Security_ID", pd.Series("", index=frame.index))
            .astype(str)
            .str.upper()
        )
        is_equity = (
            identifiers.str.startswith(self.require_identifier_prefix)
            if self.require_identifier_prefix
            else pd.Series(True, index=frame.index)
        )

        mask = (
            turnover_values.notna()
            & turnover_values.ge(self.min_median_turnover_inr)
            & frequency.notna()
            & frequency.ge(self.min_trading_frequency)
            & history.notna()
            & history.ge(self.min_history_sessions)
            & is_equity
            & ~symbols.isin(self.exclude_symbols)
        )
        diagnostics = {
            "input": int(len(frame)),
            "eligible": int(mask.sum()),
            "failed_turnover": int((~turnover_values.ge(self.min_median_turnover_inr)).sum()),
            "failed_frequency": int((~frequency.ge(self.min_trading_frequency)).sum()),
            "failed_history": int((~history.ge(self.min_history_sessions)).sum()),
            "excluded_non_equity": int((~is_equity).sum()),
            "excluded_by_name": int(symbols.isin(self.exclude_symbols).sum()),
        }
        return frame.loc[mask].reset_index(drop=True), diagnostics

    def describe(self):
        return {
            "min_median_turnover_inr": self.min_median_turnover_inr,
            "min_trading_frequency": self.min_trading_frequency,
            "min_history_sessions": self.min_history_sessions,
            "require_identifier_prefix": self.require_identifier_prefix,
            "excluded_symbols": sorted(self.exclude_symbols),
        }


class WalkForwardRunner:
    """Run one or more strategies across a shared set of rebalance dates."""

    def __init__(
        self,
        calendar,
        history_panel,
        price_panel,
        *,
        master=None,
        adjustment_table=None,
        delisting_policy=None,
        universe_rule=None,
        cost_model=None,
        value_per_position=100_000.0,
        horizons=DEFAULT_HORIZONS,
        fundamental_panel=None,
        max_statement_age_days=None,
        require_fundamentals=False,
        regime_provider=None,
    ):
        self.calendar = calendar
        self.history_panel = history_panel
        self.price_panel = price_panel
        self.master = master
        self.adjustment_table = adjustment_table
        self.universe_rule = universe_rule or UniverseRule()
        self.cost_model = cost_model
        self.value_per_position = float(value_per_position)
        self.horizons = tuple(int(h) for h in horizons)
        self.fundamental_panel = fundamental_panel
        self.max_statement_age_days = max_statement_age_days
        # When true, a security with no visible statement is dropped rather than
        # scored on price alone. Scoring it anyway would let the fundamental
        # blocks shrink to neutral and quietly turn Model 5.0 into a momentum
        # model for exactly the names whose fundamentals are missing.
        self.require_fundamentals = bool(require_fundamentals)
        # ``signal_date -> "RISK_ON"|"NEUTRAL"|"RISK_OFF"|None``. Injected rather
        # than computed here so a run without index history simply has no regime
        # overlay instead of a fabricated one.
        self.regime_provider = regime_provider
        self.execution = ExecutionModel(
            calendar,
            price_panel,
            master=master,
            adjustment_table=adjustment_table,
            delisting_policy=delisting_policy,
        )

    def cross_section(self, signal_date):
        """Eligible, point-in-time feature frame for one rebalance date."""
        keys = self.price_panel.keys_on(signal_date)
        frame = build_cross_section(
            self.history_panel,
            signal_date,
            keys=keys,
            min_history=self.universe_rule.min_history_sessions,
        )
        frame, diagnostics = self.universe_rule.apply(frame)
        if self.fundamental_panel is not None and frame is not None and len(frame):
            frame, fundamental_diagnostics = self._attach_fundamentals(
                frame, signal_date
            )
            diagnostics.update(fundamental_diagnostics)
        return frame, diagnostics

    def _attach_fundamentals(self, frame, signal_date):
        """Merge point-in-time statement factors onto the price cross-section."""
        from .fundamentals import attach_valuation_inputs

        fundamentals = self.fundamental_panel.cross_section(
            frame["Security_ID"].astype(str).tolist(),
            signal_date,
            max_age_days=self.max_statement_age_days,
        )
        diagnostics = {
            "with_fundamentals": int(len(fundamentals)),
            "without_fundamentals": int(len(frame) - len(fundamentals)),
        }
        if fundamentals.empty:
            logger.warning("No visible statements on %s", signal_date)
            return (frame.iloc[0:0] if self.require_fundamentals else frame), diagnostics

        merged = frame.merge(
            fundamentals, on="Security_ID", how="inner" if self.require_fundamentals else "left"
        )
        # Market cap and book value must be built from the point-in-time price and
        # the filed share count, never from a vendor's current market cap.
        merged = attach_valuation_inputs(merged, price_column="Close")
        return merged, diagnostics

    def run(self, strategies, signal_dates, *, on_progress=None):
        """Score every strategy on every date and return the long fill frame."""
        records = []
        diagnostics = []

        for index, signal_date in enumerate(signal_dates, start=1):
            frame, universe_diagnostics = self.cross_section(signal_date)
            universe_diagnostics["signal_date"] = _as_date(signal_date).isoformat()
            diagnostics.append(universe_diagnostics)
            if frame is None or len(frame) == 0:
                logger.warning("Empty eligible universe on %s", signal_date)
                continue

            # The chain exit is the *next* rebalance's entry session, which is
            # what makes the compounded series exact. Deriving it from a calendar
            # month instead overlaps the following period whenever the month-end
            # and the horizon date land on different sessions.
            chain_exit = None
            if index < len(signal_dates):
                chain_exit = self.calendar.next_session(signal_dates[index])
            with_returns = attach_forward_returns(
                frame,
                self.execution,
                signal_date,
                horizons=self.horizons,
                chain_exit=chain_exit,
            )

            # Model 5.0 is scored once per rebalance and shared. The block-level
            # ablations are views on the same scoring, so recomputing it per
            # strategy would repeat the whole factor model five more times for
            # results that must be identical anyway.
            shared = {}
            if self.regime_provider is not None:
                shared["market_regime"] = self.regime_provider(signal_date)
            if any(getattr(s, "needs_model5", False) for s in strategies):
                producer = next(
                    (s for s in strategies if getattr(s, "produces_model5", False)),
                    None,
                )
                from .strategies import Model5

                shared["model_5"] = (producer or Model5()).score(with_returns)

            for strategy in strategies:
                scored = (
                    shared["model_5"].copy()
                    if getattr(strategy, "produces_model5", False) and "model_5" in shared
                    else strategy.score(with_returns, shared)
                )
                scored = scored.assign(
                    Strategy=strategy.name,
                    Signal_Date=_as_date(signal_date).isoformat(),
                )
                if self.cost_model is not None:
                    scored = self._attach_costs(scored)
                records.append(scored)

            if on_progress is not None:
                on_progress(signal_date, index, len(signal_dates), universe_diagnostics)

        fills = (
            pd.concat(records, ignore_index=True)
            if records
            else pd.DataFrame()
        )
        return fills, pd.DataFrame(diagnostics)

    def _attach_costs(self, frame):
        """Charge each horizon's gross return for a round trip."""
        from .costs import round_trip_cost_rate

        working = frame.copy()
        turnovers = pd.to_numeric(
            working.get("Median_Turnover_INR"), errors="coerce"
        )
        for horizon in self.horizons:
            gross_column = f"Forward_Return_{horizon}M_Pct"
            if gross_column not in working:
                continue
            rates = []
            for turnover_value, signal_date in zip(
                turnovers, working["Signal_Date"].astype(str)
            ):
                entry = self.calendar.next_session(signal_date)
                exit_session = (
                    self.calendar.session_after_calendar_months(entry, horizon)
                    if entry
                    else None
                )
                if entry is None or exit_session is None or pd.isna(turnover_value):
                    rates.append(np.nan)
                    continue
                rate = round_trip_cost_rate(
                    self.cost_model,
                    self.value_per_position,
                    entry,
                    exit_session,
                    float(turnover_value),
                )
                rates.append(np.nan if rate is None else rate)
            cost_pct = pd.Series(rates, index=working.index, dtype="float64") * 100.0
            working[f"Cost_Rate_{horizon}M"] = rates
            working[f"Net_Return_{horizon}M_Pct"] = (
                pd.to_numeric(working[gross_column], errors="coerce") - cost_pct
            )
        return working


def evaluate(fills, *, horizons=DEFAULT_HORIZONS, portfolio_sizes=DEFAULT_PORTFOLIO_SIZES,
             score_column="Score", net=False):
    """Aggregate a fill frame into per-strategy, per-horizon evidence."""
    if fills is None or len(fills) == 0:
        return {}

    prefix = "Net_Return" if net else "Forward_Return"
    results = {}

    for strategy_name, strategy_rows in fills.groupby("Strategy"):
        per_horizon = {}
        for horizon in horizons:
            return_column = f"{prefix}_{horizon}M_Pct"
            if return_column not in strategy_rows:
                continue

            ics = []
            period_returns = {size: [] for size in portfolio_sizes}
            universe_returns = []
            bucket_frames = []

            for _signal_date, period in strategy_rows.groupby("Signal_Date"):
                scores = period[score_column]
                returns = period[return_column]
                ics.append(rank_ic(scores, returns))

                buckets = bucket_returns(scores, returns, buckets=10)
                if buckets is not None:
                    bucket_frames.append(buckets)

                usable = period.dropna(subset=[return_column])
                if usable.empty:
                    continue
                universe_mean = float(usable[return_column].mean())
                universe_returns.append(universe_mean)
                # A constant score cannot rank. Slicing "top N" from it returns
                # whichever rows sort first, which reads as a selection but is an
                # arbitrary fixed subset. Such a strategy's portfolio is the whole
                # eligible universe -- that is what a flat score expresses.
                if usable[score_column].nunique() <= 1:
                    for size in portfolio_sizes:
                        period_returns[size].append(universe_mean)
                    continue
                ordered = usable.sort_values(score_column, ascending=False)
                for size in portfolio_sizes:
                    top = ordered.head(size)
                    if len(top):
                        period_returns[size].append(float(top[return_column].mean()))

            combined_buckets = (
                pd.concat(bucket_frames).groupby("bucket", as_index=False).mean(
                    numeric_only=True
                )
                if bucket_frames
                else None
            )

            per_horizon[f"{horizon}M"] = {
                "ic": ic_summary(ics),
                "buckets": (
                    combined_buckets.to_dict("records")
                    if combined_buckets is not None
                    else None
                ),
                "bucket_spread": bucket_spread(combined_buckets),
                "monotonicity": monotonicity(combined_buckets),
                "universe_mean_return_pct": (
                    round(float(np.mean(universe_returns)), 4)
                    if universe_returns
                    else None
                ),
                "portfolios": {
                    f"top_{size}": {
                        "mean_period_return_pct": (
                            round(float(np.mean(values)), 4) if values else None
                        ),
                        "periods": len(values),
                        "vs_universe_pct": (
                            round(
                                float(np.mean(values)) - float(np.mean(universe_returns)),
                                4,
                            )
                            if values and universe_returns
                            else None
                        ),
                    }
                    for size, values in period_returns.items()
                },
            }
        results[strategy_name] = per_horizon
    return results


def portfolio_turnover_series(fills, *, size=20, score_column="Score"):
    """One-way turnover per rebalance for a top-``size`` portfolio."""
    out = {}
    for strategy_name, strategy_rows in fills.groupby("Strategy"):
        previous = {}
        values = []
        for _signal_date, period in sorted(
            strategy_rows.groupby("Signal_Date"), key=lambda item: item[0]
        ):
            ordered = period.dropna(subset=[score_column]).sort_values(
                score_column, ascending=False
            )
            top = ordered.head(size)
            weight = 1.0 / len(top) if len(top) else 0.0
            current = {str(key): weight for key in top["Security_ID"]}
            values.append(turnover(previous, current))
            previous = current
        out[strategy_name] = {
            "mean_one_way_turnover": round(float(np.mean(values)), 4) if values else None,
            "periods": len(values),
        }
    return out


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
