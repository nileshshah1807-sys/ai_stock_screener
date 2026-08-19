"""ISIN-keyed historical security master derived from the bhavcopy archive.

Answers the only universe question a backtest may ask: *which securities could an
investor actually buy on this date?* It is built by scanning the archived
sessions, so a company that was listed in 2022 and delisted in 2024 is present
for exactly the window it traded -- unlike a master built from today's
``EQUITY_L.csv``, which would omit it entirely and quietly remove its eventual
loss from every historical portfolio.

Four identity hazards are handled explicitly:

* **ISIN is not permanent in India.** A face-value change -- a split or a bonus
  issue -- is assigned a *new* ISIN by the depositories, keeping only the
  nine-character issuer-security core. ``BAJFINANCE`` went from
  ``INE296A01024`` to ``INE296A01032`` across a split; ``DRREDDY``, ``KOTAKBANK``,
  ``CANBK`` and ``COFORGE`` all did the same. Measured on the ingested archive,
  **150 of 226 apparent disappearances between 2024-01 and 2026-08 were
  face-value changes, not delistings** -- 66% of them. Treating the raw ISIN as
  permanent would mark those healthy large-caps delisted and exit each one at
  whatever `DelistingPolicy` assumes, wrecking the result. The permanent key is
  therefore an internal ``security_id`` that bridges linked ISINs.
* **Symbol changes.** Symbols are recorded with ``valid_from``/``valid_to``
  ranges. A rename is one security, not two.
* **Symbol reuse.** The same ticker can be reassigned to a different company.
  Resolving a symbol without a date is therefore ambiguous, and this module
  refuses to guess -- ``resolve_symbol`` requires an as-of date.
* **Suspensions.** A security absent for a stretch and then trading again was
  suspended, not delisted. Only a terminal absence is a delisting.

The bridge is structural rather than dependent on a corporate-action feed: two
ISINs sharing an issuer-security core belong to the same security unless they
traded *concurrently* for a sustained stretch, which is the signature of two
genuinely distinct instruments from one issuer (a DVR class alongside ordinary
shares) rather than one instrument being renumbered.

What this module deliberately does *not* do is infer *why* a security stopped
trading. Acquisition, voluntary delisting and insolvency imply very different
recovery values, and the bhavcopy does not say which occurred. The reason is
therefore recorded as ``unknown`` and the terminal-value assumption is an
explicit, reported policy choice rather than a hidden default.
"""

from __future__ import annotations

from datetime import date, datetime
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

MASTER_SCHEMA_VERSION = 1

# Sessions a security may be absent before its absence is treated as terminal
# rather than a suspension. Roughly one trading month: long enough that a short
# technical halt does not read as a delisting, short enough that a real
# delisting is not carried as tradable for a quarter.
DEFAULT_TERMINAL_ABSENCE_SESSIONS = 21

# Sessions two ISINs sharing an issuer-security core may overlap before they are
# treated as genuinely distinct instruments rather than one renumbering. A
# face-value change is a clean handover -- the old line stops and the new one
# starts, with at most a session or two of ragged overlap. A DVR class trading
# alongside ordinary shares overlaps for years.
DEFAULT_MAX_CONCURRENT_SESSIONS = 10

# Characters of an ISIN that survive a face-value change: country (2), issuer (5)
# and security type (2). Only the trailing series and check digits are reissued.
ISIN_CORE_LENGTH = 9

STATUS_ACTIVE = "active"
STATUS_DELISTED = "delisted"
STATUS_SUSPENDED_AT_END = "suspended_at_end"

REASON_UNKNOWN = "unknown"

MASTER_COLUMNS = (
    "Security_ID",
    "ISIN",
    "ISIN_History",
    "First_Session",
    "Last_Session",
    "Session_Count",
    "Status",
    "Delisting_Reason",
    "Final_Close",
    "Symbols",
    "Current_Symbol",
    "Gap_Sessions",
    "Max_Gap_Sessions",
    "Face_Value_Changes",
)


def isin_core(isin):
    """The part of an ISIN that survives a face-value change."""
    return str(isin).strip().upper()[:ISIN_CORE_LENGTH]


def link_isin_chains(windows, *, max_concurrent_sessions=None):
    """Group ISINs sharing an issuer-security core into continuation chains.

    ``windows`` maps ISIN to ``(first_position, last_position)`` in session
    space. Returns a list of chains, each a list of ISINs ordered by first
    appearance.

    Two ISINs with the same core join the same chain only when the candidate
    looks like a *successor*: it must start strictly later than the chain already
    does, and overlap it by no more than ``max_concurrent_sessions``.

    Both conditions are needed. The overlap test alone is ambiguous over a short
    archive, where two instruments spanning the whole window overlap by only as
    many sessions as the window holds. Requiring a later start is what separates a
    renumbering -- the old line stops, the new one begins -- from two instruments
    listed side by side from the same day.
    """
    threshold = int(
        max_concurrent_sessions
        if max_concurrent_sessions is not None
        else DEFAULT_MAX_CONCURRENT_SESSIONS
    )
    by_core: dict[str, list] = {}
    for isin, (first, last) in windows.items():
        by_core.setdefault(isin_core(isin), []).append((first, last, isin))

    chains = []
    for core in sorted(by_core):
        members = sorted(by_core[core])
        core_chains: list[list] = []
        chain_windows: list[list] = []
        for first, last, isin in members:
            placed = False
            for index, (chain_first, chain_last) in enumerate(chain_windows):
                overlap = min(last, chain_last) - max(first, chain_first) + 1
                if first > chain_first and overlap <= threshold:
                    core_chains[index].append(isin)
                    chain_windows[index] = [
                        min(first, chain_first),
                        max(last, chain_last),
                    ]
                    placed = True
                    break
            if not placed:
                core_chains.append([isin])
                chain_windows.append([first, last])
        chains.extend(core_chains)
    return chains


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def build_master(
    store,
    sessions,
    *,
    terminal_absence_sessions=None,
    max_concurrent_sessions=None,
):
    """Aggregate cached day-files into a per-security master frame.

    ``sessions`` is the confirmed trading calendar. Absence is measured in
    sessions rather than calendar days so a long holiday cannot look like a halt.

    ISINs are bridged into ``Security_ID`` chains first, so a face-value change
    stays one continuous security rather than becoming a delisting plus a new
    listing.
    """
    sessions = sorted(_as_date(day) for day in sessions)
    if not sessions:
        return pd.DataFrame(columns=list(MASTER_COLUMNS))

    threshold = int(
        terminal_absence_sessions
        if terminal_absence_sessions is not None
        else DEFAULT_TERMINAL_ABSENCE_SESSIONS
    )
    position_of = {day: index for index, day in enumerate(sessions)}
    per_isin: dict[str, dict] = {}

    for day in sessions:
        frame = store.load_day(day)
        if frame is None or frame.empty:
            logger.debug("No cached day-file for confirmed session %s", day)
            continue
        for isin, symbol, close in zip(
            frame["ISIN"].astype(str),
            frame["Symbol"].astype(str),
            pd.to_numeric(frame["Close"], errors="coerce"),
        ):
            record = per_isin.get(isin)
            if record is None:
                record = per_isin[isin] = {
                    "positions": [],
                    "observations": [],
                }
            record["positions"].append(position_of[day])
            record["observations"].append(
                (position_of[day], symbol, None if pd.isna(close) else float(close))
            )

    windows = {
        isin: (record["positions"][0], record["positions"][-1])
        for isin, record in per_isin.items()
    }
    chains = link_isin_chains(
        windows, max_concurrent_sessions=max_concurrent_sessions
    )

    # A core with more than one chain had concurrent instruments, so its ids need
    # a ticker qualifier. Every other core -- the overwhelming majority -- keeps
    # the bare core as its id, which stays stable if the window is later extended.
    chains_per_core: dict[str, int] = {}
    for chain in chains:
        core = isin_core(chain[0])
        chains_per_core[core] = chains_per_core.get(core, 0) + 1

    last_position = len(sessions) - 1
    rows = []
    for chain in chains:
        observations = sorted(
            observation
            for isin in chain
            for observation in per_isin[isin]["observations"]
        )
        positions = sorted({observation[0] for observation in observations})
        first_position, latest_position = positions[0], positions[-1]
        absent_at_end = last_position - latest_position

        # Internal gaps: sessions the security was absent while still listed.
        gaps = 0
        max_gap = 0
        for previous, current in zip(positions, positions[1:]):
            gap = current - previous - 1
            if gap > 0:
                gaps += gap
                max_gap = max(max_gap, gap)

        if absent_at_end == 0:
            status = STATUS_ACTIVE
        elif absent_at_end >= threshold:
            status = STATUS_DELISTED
        else:
            status = STATUS_SUSPENDED_AT_END

        spans = []
        final_close = None
        for position, symbol, close in observations:
            day = sessions[position]
            if spans and spans[-1]["symbol"] == symbol:
                spans[-1]["valid_to"] = day
            else:
                spans.append({"symbol": symbol, "valid_from": day, "valid_to": day})
            if close is not None:
                final_close = close

        # Chain order follows first appearance, so the last ISIN is the current one.
        ordered_isins = sorted(chain, key=lambda isin: windows[isin])
        rows.append(
            {
                "Security_ID": _security_id(
                    ordered_isins,
                    spans,
                    ambiguous=chains_per_core.get(isin_core(chain[0]), 1) > 1,
                ),
                "ISIN": ordered_isins[-1],
                "ISIN_History": ";".join(ordered_isins),
                "First_Session": sessions[first_position].isoformat(),
                "Last_Session": sessions[latest_position].isoformat(),
                "Session_Count": len(positions),
                "Status": status,
                "Delisting_Reason": (
                    REASON_UNKNOWN if status == STATUS_DELISTED else ""
                ),
                "Final_Close": final_close,
                "Symbols": ";".join(
                    f"{span['symbol']}|{span['valid_from'].isoformat()}|"
                    f"{span['valid_to'].isoformat()}"
                    for span in spans
                ),
                "Current_Symbol": spans[-1]["symbol"] if spans else "",
                "Gap_Sessions": gaps,
                "Max_Gap_Sessions": max_gap,
                "Face_Value_Changes": len(ordered_isins) - 1,
            }
        )

    return pd.DataFrame(rows, columns=list(MASTER_COLUMNS)).sort_values(
        "Security_ID"
    ).reset_index(drop=True)


def _security_id(ordered_isins, spans, *, ambiguous=False):
    """Permanent key for a linked chain.

    The issuer-security core alone where it is unambiguous, which keeps the id
    stable if the archive window is later extended. Qualified by the earliest
    ticker only when one issuer had concurrent instruments, so an ordinary share
    and a DVR class never collide.
    """
    core = isin_core(ordered_isins[0])
    if not ambiguous:
        return core
    first_symbol = spans[0]["symbol"] if spans else ""
    return f"{core}:{first_symbol}" if first_symbol else core


class SecurityMaster:
    """Lookups over the historical master frame."""

    def __init__(self, frame):
        self.frame = frame.copy() if frame is not None else pd.DataFrame(
            columns=list(MASTER_COLUMNS)
        )
        self._by_security = {}
        # Every ISIN a security ever traded under maps to it, so a lookup keyed on
        # a pre-split ISIN resolves to the same continuous security.
        self._isin_to_security = {}
        self._symbol_spans = []
        for record in self.frame.to_dict("records"):
            security_id = str(record.get("Security_ID") or "").strip().upper()
            if not security_id:
                continue
            self._by_security[security_id] = record
            history = str(record.get("ISIN_History") or record.get("ISIN") or "")
            for isin in history.split(";"):
                isin = isin.strip().upper()
                if isin:
                    self._isin_to_security[isin] = security_id
            for span in _parse_symbol_spans(record.get("Symbols")):
                self._symbol_spans.append((span[0], span[1], span[2], security_id))

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls(pd.DataFrame(columns=list(MASTER_COLUMNS)))
        return cls(pd.read_csv(path, dtype={"ISIN": str}))

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.frame.to_csv(path, index=False)
        return path

    def __len__(self):
        return len(self._by_security)

    def security_id_for_isin(self, isin):
        """Permanent id for any ISIN the security traded under, pre- or post-split."""
        return self._isin_to_security.get(str(isin).strip().upper())

    def record(self, identifier):
        """Master row for a ``Security_ID`` or any of its ISINs."""
        key = str(identifier).strip().upper()
        if key in self._by_security:
            return self._by_security[key]
        resolved = self._isin_to_security.get(key)
        return self._by_security.get(resolved) if resolved else None

    def status(self, identifier):
        record = self.record(identifier)
        return str(record["Status"]) if record else None

    def delisted_securities(self):
        return sorted(
            security_id
            for security_id, record in self._by_security.items()
            if record["Status"] == STATUS_DELISTED
        )

    def was_listed(self, identifier, as_of):
        """Whether the security had traded on or before ``as_of`` and not yet ended.

        A membership test, not a tradability test: presence in the bhavcopy for a
        given session is the authority on whether it actually traded that day.
        """
        record = self.record(identifier)
        if record is None:
            return False
        as_of = _as_date(as_of)
        first = _as_date(record["First_Session"])
        last = _as_date(record["Last_Session"])
        return first <= as_of <= last

    def resolve_symbol(self, symbol, as_of):
        """``Security_ID`` a ticker referred to on ``as_of``, or None.

        The as-of date is required rather than optional. NSE reassigns tickers,
        so a dateless symbol lookup can silently return the wrong company.
        """
        symbol = str(symbol).strip().upper()
        as_of = _as_date(as_of)
        for span_symbol, valid_from, valid_to, security_id in self._symbol_spans:
            if span_symbol == symbol and valid_from <= as_of <= valid_to:
                return security_id
        return None

    def reused_symbols(self):
        """Tickers that mapped to more than one security over the window."""
        owners: dict[str, set] = {}
        for symbol, _, _, security_id in self._symbol_spans:
            owners.setdefault(symbol, set()).add(security_id)
        return {
            symbol: sorted(ids) for symbol, ids in owners.items() if len(ids) > 1
        }

    def renamed_securities(self):
        """Securities that traded under more than one ticker over the window."""
        out = {}
        for security_id, record in self._by_security.items():
            spans = _parse_symbol_spans(record.get("Symbols"))
            symbols = list(dict.fromkeys(span[0] for span in spans))
            if len(symbols) > 1:
                out[security_id] = symbols
        return out

    def face_value_changes(self):
        """Securities whose ISIN was reissued, keyed to the full ISIN chain."""
        out = {}
        for security_id, record in self._by_security.items():
            history = [
                isin.strip().upper()
                for isin in str(record.get("ISIN_History") or "").split(";")
                if isin.strip()
            ]
            if len(history) > 1:
                out[security_id] = history
        return out

    def survivorship_summary(self, as_of=None):
        """Counts that make the survivorship gap explicit in the run report."""
        statuses = self.frame["Status"].astype(str).value_counts().to_dict()
        return {
            "securities_total": len(self._by_security),
            "active": int(statuses.get(STATUS_ACTIVE, 0)),
            "delisted": int(statuses.get(STATUS_DELISTED, 0)),
            "suspended_at_end": int(statuses.get(STATUS_SUSPENDED_AT_END, 0)),
            "renamed": len(self.renamed_securities()),
            "reused_symbols": len(self.reused_symbols()),
            "face_value_changes": len(self.face_value_changes()),
            "as_of": _as_date(as_of).isoformat() if as_of else None,
        }


def _parse_symbol_spans(value):
    if not value or (isinstance(value, float) and pd.isna(value)):
        return []
    spans = []
    for chunk in str(value).split(";"):
        parts = chunk.split("|")
        if len(parts) != 3:
            continue
        try:
            spans.append(
                (
                    parts[0].strip().upper(),
                    date.fromisoformat(parts[1]),
                    date.fromisoformat(parts[2]),
                )
            )
        except ValueError:
            continue
    return spans


class DelistingPolicy:
    """Terminal value applied when a held position stops trading.

    Every strategy here is an assumption, not an observation, because the
    bhavcopy does not record why trading stopped. The policy is named and its
    effect is reported per position so the final result can be re-run under a
    different assumption and the difference quantified.

    * ``last_close`` -- exit at the final observed close. The most generous
      assumption: correct for an acquisition at around market price, far too
      generous for an insolvency.
    * ``haircut`` -- exit at the final close times ``recovery_rate``. The
      defensible default when the reason is unknown, since a delisting skews
      towards distress in the Indian small-cap tail.
    * ``zero`` -- total loss. The most conservative bound.
    """

    STRATEGIES = ("last_close", "haircut", "zero")

    def __init__(self, strategy="haircut", recovery_rate=0.5):
        if strategy not in self.STRATEGIES:
            raise ValueError(
                f"Unknown delisting strategy {strategy!r}; expected one of "
                f"{self.STRATEGIES}"
            )
        if not 0.0 <= float(recovery_rate) <= 1.0:
            raise ValueError("recovery_rate must be within [0, 1]")
        self.strategy = strategy
        self.recovery_rate = float(recovery_rate)

    def terminal_price(self, final_close):
        if final_close is None or pd.isna(final_close):
            return None
        final_close = float(final_close)
        if self.strategy == "last_close":
            return final_close
        if self.strategy == "zero":
            return 0.0
        return final_close * self.recovery_rate

    def describe(self):
        if self.strategy == "haircut":
            return f"haircut@{self.recovery_rate:.2f}"
        return self.strategy
