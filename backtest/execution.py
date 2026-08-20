"""Next-session execution and forward returns.

The single rule this module exists to enforce: **a signal computed from the close
of session *t* may not be filled at that close.** The close is not observable
until the session ends, so filling at it assumes an order placed with knowledge
of its own outcome. `p0.md` §4 calls this out directly, and the existing
`screener.market_data.BacktestEngine` violates it -- it enters at
``Current_Price``, the same close that produced the score.

So every fill here happens at the **open of the next confirmed session**, resolved
through the empirical `TradingCalendar` rather than by adding a day.

A position that cannot be priced is dropped, never approximated. Four cases end a
holding period without a clean exit price, and each is recorded with a reason
rather than silently filled:

* the security did not trade on the fill session
* the horizon extends past the end of the archive
* an unadjustable corporate action (rights, demerger, buyback) falls inside the
  holding period
* the security stopped trading mid-period -- here the `DelistingPolicy` terminal
  value applies, which is an assumption and is labelled as one

Returns are computed on corporate-action-adjusted prices. Measuring them on raw
bhavcopy prices would score splits as ~50% losses.
"""

from __future__ import annotations

from datetime import date, datetime
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Reasons a holding period produced no usable return.
SKIP_NO_ENTRY_PRICE = "no_entry_price"
SKIP_NO_EXIT_PRICE = "no_exit_price"
SKIP_HORIZON_BEYOND_DATA = "horizon_beyond_data"
SKIP_UNADJUSTABLE_ACTION = "unadjustable_action"
SKIP_NOT_IN_UNIVERSE = "not_in_universe"

EXIT_NORMAL = "normal"
EXIT_DELISTED = "delisted_terminal_value"

DEFAULT_HORIZON_MONTHS = (1, 3, 6, 12)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


class PricePanel:
    """Adjusted price lookups keyed by ``(Security_ID, session)``.

    Built once per run from the cached day-files. Holds adjusted opens and closes
    because a fill uses the open and a signal uses the close.
    """

    def __init__(self, frame, *, key_column="Security_ID"):
        self.key_column = key_column
        self.frame = frame
        self._open = {}
        self._close = {}
        self._sessions_by_key = {}
        if frame is None or len(frame) == 0:
            return

        dates = pd.to_datetime(frame["Trade_Date"]).dt.date
        keys = frame[key_column].astype(str)
        opens = pd.to_numeric(
            frame.get("Adj_Open", frame.get("Open")), errors="coerce"
        )
        closes = pd.to_numeric(
            frame.get("Adj_Close", frame.get("Close")), errors="coerce"
        )
        for key, day, open_price, close_price in zip(keys, dates, opens, closes):
            if pd.notna(open_price) and open_price > 0:
                self._open[(key, day)] = float(open_price)
            if pd.notna(close_price) and close_price > 0:
                self._close[(key, day)] = float(close_price)
            self._sessions_by_key.setdefault(key, []).append(day)
        for sessions in self._sessions_by_key.values():
            sessions.sort()

    @classmethod
    def build(cls, store, sessions, master, table=None, *, key_column="Security_ID"):
        """Assemble an adjusted panel from cached day-files."""
        from .corporate_actions import adjust_panel

        frames = []
        for day in sessions:
            frame = store.load_day(day)
            if frame is None or frame.empty:
                continue
            frame = frame.copy()
            frame[key_column] = [
                master.security_id_for_isin(isin) or str(isin)
                for isin in frame["ISIN"].astype(str)
            ]
            frames.append(frame)
        if not frames:
            return cls(pd.DataFrame(), key_column=key_column)
        panel = pd.concat(frames, ignore_index=True)
        if table is not None:
            panel = adjust_panel(panel, table, key_column=key_column)
        return cls(panel, key_column=key_column)

    def open_price(self, key, session):
        return self._open.get((str(key), _as_date(session)))

    def close_price(self, key, session):
        return self._close.get((str(key), _as_date(session)))

    def traded_on(self, key, session):
        return (str(key), _as_date(session)) in self._close

    def keys_on(self, session):
        """Securities that traded on ``session`` -- the universe for that date."""
        session = _as_date(session)
        return {key for (key, day) in self._close if day == session}

    def last_session_for(self, key):
        sessions = self._sessions_by_key.get(str(key))
        return sessions[-1] if sessions else None

    def __len__(self):
        return len(self._close)


class ExecutionModel:
    """Resolve entry and exit prices for a signal date and horizon."""

    def __init__(
        self,
        calendar,
        panel,
        *,
        master=None,
        adjustment_table=None,
        delisting_policy=None,
    ):
        self.calendar = calendar
        self.panel = panel
        self.master = master
        self.adjustment_table = adjustment_table
        self.delisting_policy = delisting_policy

    def entry_session(self, signal_date):
        """The session an order signalled on ``signal_date``'s close fills in."""
        return self.calendar.next_session(signal_date)

    def exit_session(self, entry_session, horizon_months):
        """The session that closes a holding period of ``horizon_months``."""
        if entry_session is None:
            return None
        return self.calendar.session_after_calendar_months(
            entry_session, horizon_months
        )

    def resolve(self, key, signal_date, horizon_months, *, exit_override=None):
        """Return a fill record for one security and horizon.

        The record always carries ``Status``; ``Return_Pct`` is populated only when
        both legs priced cleanly.

        ``exit_override`` pins the exit to a specific session instead of deriving
        it from ``horizon_months``. That is what makes a chaining series exact: a
        calendar-month exit and the next rebalance's entry do not always coincide,
        so compounding month-horizon returns double-counts the days between them.
        """
        signal_date = _as_date(signal_date)
        record = {
            "Security_ID": str(key),
            "Signal_Date": signal_date.isoformat(),
            "Horizon_Months": int(horizon_months),
            "Entry_Session": None,
            "Exit_Session": None,
            "Entry_Price": None,
            "Exit_Price": None,
            "Return_Pct": None,
            "Dividends": 0.0,
            "Holding_Sessions": None,
            "Exit_Type": None,
            "Status": None,
        }

        entry = self.entry_session(signal_date)
        if entry is None:
            record["Status"] = SKIP_HORIZON_BEYOND_DATA
            return record
        record["Entry_Session"] = entry.isoformat()

        entry_price = self.panel.open_price(key, entry)
        if entry_price is None:
            # Did not trade on the fill session: an order would not have executed.
            record["Status"] = SKIP_NO_ENTRY_PRICE
            return record
        record["Entry_Price"] = entry_price

        exit_session = (
            _as_date(exit_override)
            if exit_override is not None
            else self.exit_session(entry, horizon_months)
        )
        if exit_session is None or exit_session <= entry:
            record["Status"] = SKIP_HORIZON_BEYOND_DATA
            return record
        record["Exit_Session"] = exit_session.isoformat()

        if self.adjustment_table is not None and self.adjustment_table.is_blocked(
            key, entry, exit_session
        ):
            record["Status"] = SKIP_UNADJUSTABLE_ACTION
            record["Exit_Type"] = ";".join(
                self.adjustment_table.blocked_reasons(key, entry, exit_session)
            )
            return record

        exit_price = self.panel.open_price(key, exit_session)
        exit_type = EXIT_NORMAL

        if exit_price is None:
            exit_price, exit_type = self._terminal_exit(key, entry, exit_session)
            if exit_price is None:
                record["Status"] = SKIP_NO_EXIT_PRICE
                return record

        record["Exit_Price"] = exit_price
        record["Exit_Type"] = exit_type
        if self.adjustment_table is not None:
            record["Dividends"] = float(
                self.adjustment_table.dividends_between(key, entry, exit_session)
            )
        record["Holding_Sessions"] = len(
            self.calendar.sessions_between(entry, exit_session)
        )
        record["Return_Pct"] = (
            (exit_price + record["Dividends"]) / entry_price - 1.0
        ) * 100.0
        record["Status"] = "ok"
        return record

    def _terminal_exit(self, key, entry, exit_session):
        """Price a position whose security stopped trading before the horizon.

        Only applies when the security genuinely stopped: its last observed session
        falls inside the holding period. A security that merely did not trade on
        the exact exit session is a liquidity gap, and the last close inside the
        window prices it without any delisting assumption.
        """
        last_session = self.panel.last_session_for(key)
        if last_session is None:
            return None, None

        if last_session >= exit_session:
            # Traded after the exit date but not on it: use the most recent close
            # at or before the exit session. No delisting assumption is involved.
            fallback = self.calendar.session_on_or_before(exit_session)
            while fallback is not None and fallback >= entry:
                price = self.panel.close_price(key, fallback)
                if price is not None:
                    return price, EXIT_NORMAL
                fallback = self.calendar.previous_session(fallback)
            return None, None

        if last_session < entry:
            return None, None

        # Stopped trading mid-period. The terminal value is a policy assumption.
        if self.delisting_policy is None:
            return None, None
        final_close = self.panel.close_price(key, last_session)
        terminal = self.delisting_policy.terminal_price(final_close)
        if terminal is None:
            return None, None
        return terminal, EXIT_DELISTED


def forward_returns(
    execution,
    keys,
    signal_date,
    horizons=DEFAULT_HORIZON_MONTHS,
):
    """Fill records for every ``key`` across every horizon, as a long frame."""
    rows = [
        execution.resolve(key, signal_date, horizon)
        for horizon in horizons
        for key in keys
    ]
    return pd.DataFrame(rows)


def attach_forward_returns(scores, execution, signal_date,
                           horizons=DEFAULT_HORIZON_MONTHS, *, chain_exit=None):
    """Widen a scored cross-section with one forward-return column per horizon.

    ``scores`` must carry ``Security_ID``. Returns a copy with
    ``Forward_Return_{n}M_Pct`` and ``Forward_Status_{n}M`` per horizon, so a
    dropped position is visible as a reason instead of a silent NaN.

    ``chain_exit`` additionally produces ``Forward_Return_Chain_Pct``, held from
    this rebalance's entry to the *next* rebalance's entry. Only that series may
    be compounded into a CAGR: a calendar-month horizon overlaps the following
    period whenever the month-end and the horizon date fall on different
    sessions, which on this archive happened in 16 of 51 periods and counted
    ~2.4% of market time twice.
    """
    if scores is None or len(scores) == 0:
        return scores
    out = scores.copy()
    keys = out["Security_ID"].astype(str).tolist()
    if chain_exit is not None:
        records = [
            execution.resolve(key, signal_date, 0, exit_override=chain_exit)
            for key in keys
        ]
        out["Forward_Return_Chain_Pct"] = [r["Return_Pct"] for r in records]
        out["Forward_Status_Chain"] = [r["Status"] for r in records]
    for horizon in horizons:
        records = [execution.resolve(key, signal_date, horizon) for key in keys]
        out[f"Forward_Return_{horizon}M_Pct"] = [
            record["Return_Pct"] for record in records
        ]
        out[f"Forward_Status_{horizon}M"] = [record["Status"] for record in records]
        out[f"Forward_Exit_Type_{horizon}M"] = [
            record["Exit_Type"] for record in records
        ]
    return out


def coverage_report(frame, horizons=DEFAULT_HORIZON_MONTHS):
    """Per-horizon fill coverage, so a thin horizon cannot pass unnoticed."""
    report = {}
    for horizon in horizons:
        column = f"Forward_Status_{horizon}M"
        if column not in frame:
            continue
        counts = frame[column].astype(str).value_counts().to_dict()
        total = int(sum(counts.values()))
        report[f"{horizon}M"] = {
            "total": total,
            "ok": int(counts.get("ok", 0)),
            "coverage": round(counts.get("ok", 0) / total, 4) if total else 0.0,
            "skipped": {k: int(v) for k, v in counts.items() if k != "ok"},
        }
    return report
