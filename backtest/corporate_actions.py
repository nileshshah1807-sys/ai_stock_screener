"""Corporate-action parsing and price adjustment.

Bhavcopy prices are raw. The exchange does **not** adjust them, and it does not
adjust ``Prev_Close`` either -- verified on NARMADA's 2026-07-31 face-value split,
where the close moved 36.19 to 17.02 while ``Prev_Close`` still read 36.19. A
return computed straight off those closes is -53% for a company whose holders
lost nothing. Every price series this engine measures returns on therefore has to
be adjusted before use, or the momentum block is scoring corporate actions.

Actions come from ``nse.actions()``, which is authoritative and carries the ratio
in its ``subject`` text. Over 2025-01 to 2026-08 the segment contains 3,029
actions in six recognisable shapes:

* ``Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share``
* ``Bonus 1:1`` / ``Bonus 2:5``
* ``Dividend - Re 0.40 Per Sh``
* ``Interest Payment ...`` -- debt, irrelevant to an equity cross-section
* ``Rights ...``, ``Demerger``, ``Buy Back``

Splits, bonuses and dividends are adjusted precisely. Rights issues, demergers
and buybacks change the value of a holding in ways no single ratio captures, so
they are **flagged rather than approximated**: the affected security is marked
around its ex-date and the run excludes it instead of silently mis-adjusting it.
Guessing there would put a fabricated return into the result, which is exactly
what P0 exists to prevent.

A chart and a live screen cannot exclude a security, though: they have to draw
and score it. For those readers alone an unadjustable action gets a
*display-grade* factor, ``ex_date_price_factor``, read off the security's own
ex-date bar. The backtest never applies it -- its table still blocks the
position.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

ACTIONS_SCHEMA_VERSION = 1

ACTION_SPLIT = "split"
ACTION_BONUS = "bonus"
ACTION_DIVIDEND = "dividend"
ACTION_RIGHTS = "rights"
ACTION_DEMERGER = "demerger"
ACTION_BUYBACK = "buyback"
ACTION_INTEREST = "interest"
ACTION_UNKNOWN = "unknown"

# Actions that change the share count or the price basis by a ratio we can
# compute exactly from the subject text.
RATIO_ACTIONS = frozenset({ACTION_SPLIT, ACTION_BONUS})

# Actions that materially change the value of a holding but not by a ratio this
# module can derive. Affected securities are excluded around the ex-date.
UNADJUSTABLE_ACTIONS = frozenset({ACTION_RIGHTS, ACTION_DEMERGER, ACTION_BUYBACK})

ACTION_COLUMNS = (
    "ISIN",
    "Symbol",
    "Ex_Date",
    "Action_Type",
    "Price_Factor",
    "Dividend_Per_Share",
    "Subject",
    "Parse_Status",
)

_FACE_VALUE_RE = re.compile(
    r"from\s+(?:rs\.?|re\.?)\s*([\d.]+)\s*/?-?\s*per\s+share\s+to\s+"
    r"(?:rs\.?|re\.?)\s*([\d.]+)",
    re.IGNORECASE,
)
# Punctuation between "Bonus" and the ratio is common: NSE emits "Bonus 1:1",
# "Bonus- 1:2" and "Bonus Issue 1:1" interchangeably. Without the separator class
# AJANTPHARM's real "Bonus- 1:2" is missed and the security is needlessly blocked.
_BONUS_RE = re.compile(
    r"bonus\b[\s\-:.]*(?:issue)?[\s\-:.]*(\d+)\s*:\s*(\d+)", re.IGNORECASE
)

# A bonus paid in something other than equity leaves the equity share count
# unchanged, so its ratio is emphatically not an equity price factor. Two real
# cases from the 2018-2026 feed:
#
#   TVSMOTOR   "Scheme Of Arrangement - Bonus Ncrps 4:1"
#   BRITANNIA  "Scheme Of Arangement- Bonus - 1 Debenture For 1 Equity Share Held"
#
# Treated as equity ratios these would apply factors of 5.0 and 2.0, turning
# ~1% ex-date drops into fabricated +400% and +100% returns on large caps. Both
# happened to miss the bonus pattern and block by luck; matching them explicitly
# makes the safety deliberate. ("Arangement" is NSE's spelling, not a typo here.)
_NON_EQUITY_BONUS_RE = re.compile(
    r"\b(?:ncrps|ncps|nccrps|ncd|preference\s+share|debenture|bond|warrant)",
    re.IGNORECASE,
)
_AMOUNT = r"(\d+(?:\.\d+)?)"
# Standard form, tolerating the stray hyphen NSE sometimes emits ("Rs -10").
_DIVIDEND_RE = re.compile(rf"(?:rs|re)\.?\s*-?\s*{_AMOUNT}", re.IGNORECASE)
# Observed malformations, tried only when the standard form finds nothing.
_DIVIDEND_REVERSED_RE = re.compile(rf"{_AMOUNT}\s*(?:rs|re)\b", re.IGNORECASE)
_DIVIDEND_SPACED_RE = re.compile(rf"\br\s+e\s+-?\s*{_AMOUNT}", re.IGNORECASE)
_DIVIDEND_MALFORMED_RE = re.compile(
    rf"(?:rs|re)\.?\s*per\s*{_AMOUNT}", re.IGNORECASE
)


def _dividend_amount(text):
    """Total per-share dividend in a subject, or None.

    Amounts are **summed**, not first-matched. 264 subjects in the 2022-2026 feed
    carry more than one -- "Interim Dividend - Rs 19 Per Share/Special Dividend -
    Rs 10 Per Share" is Rs 29 to the holder, and taking only the first understates
    total return systematically rather than randomly.

    Summing is safe here only because no dividend subject in the feed states a
    face value; if one ever did, "Rs 5 per share of Rs 10 face value" would sum to
    15. The fallbacks below are deliberately first-match, since a malformed
    subject gives no confidence that a second number is another dividend.
    """
    matches = _DIVIDEND_RE.findall(text)
    if matches:
        return sum(float(value) for value in matches)
    for pattern in (
        _DIVIDEND_REVERSED_RE,
        _DIVIDEND_SPACED_RE,
        _DIVIDEND_MALFORMED_RE,
    ):
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    return None


def ex_date_price_factor(prev_close, ex_open):
    """Divisor restating earlier prices across an action with no stated ratio.

    A demerger or a rights issue takes value out of the share on its ex-date,
    and the ex-date open is where the market prices what is left -- for a
    demerger through a special price-discovery session. ``prev_close /
    ex_open`` is therefore the market's own ratio, and a holder's value is
    unchanged across that open, which is what dividing every earlier price by
    the factor draws.

    Display-grade, not exact: the open also carries one overnight's ordinary
    move, and whatever the holder was handed is not followed afterwards.
    ``None`` when either price is missing or the open is not below the previous
    close -- such an action cannot add value to the share, so that is noise.
    """
    prev_close = pd.to_numeric(prev_close, errors="coerce")
    ex_open = pd.to_numeric(ex_open, errors="coerce")
    if pd.isna(prev_close) or pd.isna(ex_open) or prev_close <= 0 or ex_open <= 0:
        return None
    factor = float(prev_close) / float(ex_open)
    return factor if factor > 1.0 else None


# Below this the tick size alone moves a price by more than any opening band,
# so a large relative gap says nothing about the share's basis.
MIN_PRICE_FOR_OPEN_GAP = 1.0


def open_gap_factor(prev_close, bar_open, bar_close, max_open_gap):
    """Divisor implied by an open no session could have traded to, or ``None``.

    An exchange that caps the opening auction caps how far an open can sit from
    the previous close. An open beyond that cap was not traded to: the unit
    itself changed -- a split, a consolidation, a distribution, a re-listing on
    new terms -- or a price source restated one side of the bar and not the
    other. Either way earlier prices are on another basis, and ``prev_close /
    bar_open`` is the factor between the two. It can be below one.

    ``max_open_gap`` is that cap as a ratio with some margin (1.30 for a 20%
    band). The bar's own close has to sit within the cap of its open, so one
    bad opening print is not read as a change of basis.
    """
    # Plain floats: this runs once per bar of every security in the archive.
    try:
        prev_close, bar_open, bar_close = (
            float(prev_close), float(bar_open), float(bar_close)
        )
    except (TypeError, ValueError):
        return None
    # NaN fails the comparison, so a missing price is rejected here as well.
    if not all(
        price >= MIN_PRICE_FOR_OPEN_GAP for price in (prev_close, bar_open, bar_close)
    ):
        return None
    factor = prev_close / bar_open
    if max(factor, 1.0 / factor) <= max_open_gap:
        return None
    if max(bar_close / bar_open, bar_open / bar_close) > max_open_gap:
        return None
    return factor


def classify_action(subject):
    """Coarse action type from the NSE subject text."""
    text = str(subject or "").strip().lower()
    if not text:
        return ACTION_UNKNOWN
    # Order matters: a subject can mention several things, and the structural
    # action dominates the cash one.
    if "split" in text or "sub-division" in text or "sub division" in text:
        return ACTION_SPLIT
    # A consolidation is a split run backwards, stated in the same words; the
    # face-value pattern reads its ratio as below one. A capital reduction
    # changes value as well as count, so it is not a ratio and stays unknown.
    if "consolidation" in text and "reduction" not in text:
        return ACTION_SPLIT
    if "bonus" in text:
        return ACTION_BONUS
    if "demerger" in text or "de-merger" in text:
        return ACTION_DEMERGER
    if "buy back" in text or "buyback" in text:
        return ACTION_BUYBACK
    if "rights" in text:
        return ACTION_RIGHTS
    if "interest payment" in text:
        return ACTION_INTEREST
    if "dividend" in text:
        return ACTION_DIVIDEND
    return ACTION_UNKNOWN


def parse_action(subject):
    """Return ``(action_type, price_factor, dividend_per_share, status)``.

    ``price_factor`` is the multiple by which the share count rises, so the price
    basis divides by it: a 10-to-2 face-value split gives 5.0, ``Bonus 1:1`` gives
    2.0. ``None`` means no ratio applies or none could be parsed.

    A bonus of ``A:B`` awards A new shares for every B held, leaving ``A+B`` where
    there were ``B`` -- so the factor is ``(A+B)/B``, not ``A/B``. Getting that
    backwards would invert the correction it exists to make.
    """
    text = str(subject or "").strip()
    action = classify_action(text)

    if action == ACTION_SPLIT:
        match = _FACE_VALUE_RE.search(text)
        if match:
            before, after = float(match.group(1)), float(match.group(2))
            if before > 0 and after > 0:
                return action, before / after, None, "ok"
        return action, None, None, "unparsed_ratio"

    if action == ACTION_BONUS:
        # A bonus paid in preference shares, debentures or warrants leaves the
        # equity count untouched, so its ratio must never reach the price factor.
        # The price still moves by the value distributed, which no ratio here
        # captures, so these block rather than being adjusted.
        if _NON_EQUITY_BONUS_RE.search(text):
            return action, None, None, "unadjustable_non_equity_bonus"
        match = _BONUS_RE.search(text)
        if match:
            new, held = float(match.group(1)), float(match.group(2))
            if held > 0:
                return action, (new + held) / held, None, "ok"
        return action, None, None, "unparsed_ratio"

    if action == ACTION_DIVIDEND:
        amount = _dividend_amount(text)
        if amount is not None:
            return action, None, amount, "ok"
        # A dividend whose amount NSE never published. Skipped rather than
        # blocked: a missed rupee understates one position's total return by
        # about a percent, while excluding the security loses the whole
        # observation. That trade is the opposite way round for a split.
        return action, None, None, "unparsed_amount"

    if action in UNADJUSTABLE_ACTIONS:
        return action, None, None, "unadjustable"

    return action, None, None, "ignored"


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _parse_ex_date(value):
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    for pattern in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    try:
        return pd.Timestamp(text).date()
    except Exception:
        return None


def normalise_actions(records):
    """Normalise raw ``nse.actions()`` records into the stable action schema."""
    rows = []
    for record in records or []:
        ex_date = _parse_ex_date(record.get("exDate"))
        isin = str(record.get("isin") or "").strip().upper()
        if ex_date is None or not isin:
            continue
        subject = record.get("subject")
        action, factor, dividend, status = parse_action(subject)
        rows.append(
            {
                "ISIN": isin,
                "Symbol": str(record.get("symbol") or "").strip().upper(),
                "Ex_Date": ex_date.isoformat(),
                "Action_Type": action,
                "Price_Factor": factor,
                "Dividend_Per_Share": dividend,
                "Subject": str(subject or "").strip(),
                "Parse_Status": status,
            }
        )
    frame = pd.DataFrame(rows, columns=list(ACTION_COLUMNS))
    if frame.empty:
        return frame
    return frame.drop_duplicates(
        subset=["ISIN", "Ex_Date", "Action_Type", "Subject"]
    ).sort_values(["ISIN", "Ex_Date"]).reset_index(drop=True)


class ActionStore:
    """Fetch and cache the corporate-action feed for a window."""

    def __init__(self, path, *, nse_factory=None):
        self.path = Path(path)
        self._nse_factory = nse_factory

    def _make_nse(self, download_folder):
        if self._nse_factory is not None:
            return self._nse_factory(download_folder)
        from nse import NSE

        return NSE(download_folder=download_folder, timeout=90, server=False)

    def load(self):
        if not self.path.exists():
            return pd.DataFrame(columns=list(ACTION_COLUMNS))
        try:
            return pd.read_csv(self.path, dtype={"ISIN": str})
        except Exception as exc:
            logger.warning("Action cache unreadable: %s", exc)
            return pd.DataFrame(columns=list(ACTION_COLUMNS))

    def fetch(self, start, end):
        """Fetch and normalise actions for ``[start, end]``, merging them into the cache.

        Returns only the fetched window. The cache keeps every cached action
        outside the window: writing the window alone meant an incremental
        backfill (``--start`` a month back) deleted the whole history before
        it, and every earlier split then read as a fabricated ~50% loss.
        """
        from tempfile import TemporaryDirectory

        start, end = _as_date(start), _as_date(end)
        with TemporaryDirectory(prefix="nse_actions_") as folder, self._make_nse(folder) as nse:
            records = nse.actions(
                segment="equities",
                from_date=datetime.combine(start, datetime.min.time()),
                to_date=datetime.combine(end, datetime.max.time()),
            )
        frame = normalise_actions(records)

        existing = self.load()
        if not existing.empty:
            ex_dates = pd.to_datetime(existing["Ex_Date"], errors="coerce").dt.date
            # The window is re-fetched in full, so it replaces its cached rows
            # outright; a corrected or withdrawn action must not survive.
            outside = existing[~ex_dates.between(start, end)]
            merged = pd.concat([outside, frame], ignore_index=True)
            merged = merged.drop_duplicates(
                subset=["ISIN", "Ex_Date", "Action_Type", "Subject"]
            ).sort_values(["ISIN", "Ex_Date"]).reset_index(drop=True)
        else:
            merged = frame
        self.path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_csv(self.path, index=False)
        return frame


class AdjustmentTable:
    """Cumulative price adjustment per security, keyed by the security master.

    Back-adjustment convention: for an action with price factor ``f`` on ex-date
    ``d``, every price strictly before ``d`` is divided by ``f``. The adjusted
    series is therefore continuous across the action and returns measured on it
    are what a holder actually experienced.
    """

    def __init__(self, actions, master=None):
        self.master = master
        self._factors: dict[str, list] = {}
        self._dividends: dict[str, list] = {}
        self._blocked: dict[str, list] = {}

        if actions is None or len(actions) == 0:
            return
        for record in actions.to_dict("records"):
            ex_date = _parse_ex_date(record.get("Ex_Date"))
            if ex_date is None:
                continue
            key = self.key_for(record.get("ISIN"), record.get("Symbol"), ex_date)
            if key is None:
                continue
            action = str(record.get("Action_Type") or "")
            factor = pd.to_numeric(record.get("Price_Factor"), errors="coerce")
            dividend = pd.to_numeric(
                record.get("Dividend_Per_Share"), errors="coerce"
            )
            if action in RATIO_ACTIONS:
                if pd.notna(factor) and float(factor) > 0:
                    self._factors.setdefault(key, []).append((ex_date, float(factor)))
                else:
                    # A structural action we could not quantify is more dangerous
                    # than one we can, so it blocks rather than being skipped.
                    self._blocked.setdefault(key, []).append((ex_date, action))
            elif action == ACTION_DIVIDEND and pd.notna(dividend):
                self._dividends.setdefault(key, []).append((ex_date, float(dividend)))
            elif action in UNADJUSTABLE_ACTIONS:
                self._blocked.setdefault(key, []).append((ex_date, action))

    def add_derived_factor(self, key, ex_date, factor):
        """Record a price factor that did not come from an action's subject.

        For readers that must draw a security through an unadjustable action
        (see ``ex_date_price_factor``). The action still blocks: a backtest
        given this table would exclude the position exactly as before.
        """
        entry = (_as_date(ex_date), float(factor))
        entries = self._factors.setdefault(str(key), [])
        if entry[1] > 0 and all(existing[0] != entry[0] for existing in entries):
            entries.append(entry)

    def securities_with_actions_since(self, since):
        """Securities with a *ratio* action on or after ``since``.

        Only ratio actions -- splits, bonuses, consolidations -- matter here.
        They rescale the whole price history, so a series published before one
        is wrong from its first point until it is rebuilt. Dividends adjust
        returns rather than the price line a chart draws, so they are not a
        reason to republish.
        """
        return {
            key
            for key, entries in self._factors.items()
            if any(ex_date >= since for ex_date, _ in entries)
        }

    def key_for(self, isin, symbol=None, as_of=None):
        """The security an action record refers to, as the price panel keys it.

        The feed's ISIN is often not one the security ever traded under in the
        archive -- superseded by a face-value change, a placeholder, or simply
        another company's. Keyed on it alone the action matches no price row
        and is silently dropped: a split left unapplied. So the exact ISIN is
        tried first, then its core, then the ticker as of the ex-date.
        """
        isin = str(isin or "").strip().upper()
        if not isin:
            return None
        if self.master is not None:
            resolved = self.master.security_id_for_isin(
                isin
            ) or self.master.security_id_for_isin_core(isin)
            if not resolved and symbol and as_of is not None:
                resolved = self.master.resolve_symbol(symbol, as_of)
            if resolved:
                return resolved
        return isin

    def ratio_factor(self, key, ex_date):
        """Product of the ratio factors recorded for one ex-date, or ``None``."""
        ex_date = _as_date(ex_date)
        factors = [
            value for day, value in self._factors.get(str(key), ()) if day == ex_date
        ]
        if not factors:
            return None
        product = 1.0
        for value in factors:
            product *= value
        return product

    def replace_factor(self, key, ex_date, factor, *, effective=None):
        """Swap one ex-date's ratio factors for ``factor``, or drop them.

        For a reader that has checked the ledger against the price panel and
        found the stated ratio is not what the price did (see
        ``workers.price_series_publisher.reconcile_with_prices``).
        """
        ex_date = _as_date(ex_date)
        entries = [
            entry for entry in self._factors.get(str(key), ()) if entry[0] != ex_date
        ]
        if factor is not None and float(factor) > 0:
            entries.append((_as_date(effective or ex_date), float(factor)))
        if entries:
            self._factors[str(key)] = entries
        else:
            self._factors.pop(str(key), None)

    def price_factor(self, key, as_of):
        """Divisor converting a raw price on ``as_of`` to the adjusted basis.

        The product of every ratio action with an ex-date strictly after
        ``as_of``.
        """
        as_of = _as_date(as_of)
        factor = 1.0
        for ex_date, value in self._factors.get(str(key), ()):
            if ex_date > as_of:
                factor *= value
        return factor

    def dividends_between(self, key, start, end):
        """Dividends with an ex-date in ``(start, end]``, for total return."""
        start, end = _as_date(start), _as_date(end)
        return sum(
            amount
            for ex_date, amount in self._dividends.get(str(key), ())
            if start < ex_date <= end
        )

    def is_blocked(self, key, start, end):
        """Whether an unadjustable action falls in ``(start, end]``."""
        start, end = _as_date(start), _as_date(end)
        return any(
            start < ex_date <= end
            for ex_date, _ in self._blocked.get(str(key), ())
        )

    def blocked_reasons(self, key, start, end):
        start, end = _as_date(start), _as_date(end)
        return sorted(
            {
                action
                for ex_date, action in self._blocked.get(str(key), ())
                if start < ex_date <= end
            }
        )

    def summary(self):
        return {
            "securities_with_ratio_actions": len(self._factors),
            "ratio_actions": sum(len(v) for v in self._factors.values()),
            "securities_with_dividends": len(self._dividends),
            "dividend_events": sum(len(v) for v in self._dividends.values()),
            "securities_blocked": len(self._blocked),
            "blocking_events": sum(len(v) for v in self._blocked.values()),
        }


def adjust_panel(panel, table, *, key_column="Security_ID"):
    """Attach back-adjusted price columns to a long price panel.

    Adds ``Adj_Factor`` and adjusted ``Adj_Open``/``Adj_High``/``Adj_Low``/
    ``Adj_Close``. Volume is left raw: an adjusted volume is rarely what a
    capacity calculation wants, and turnover is unaffected by a split.
    """
    if panel is None or len(panel) == 0:
        return panel
    working = panel.copy()
    dates = pd.to_datetime(working["Trade_Date"]).dt.date
    keys = working[key_column].astype(str)
    working["Adj_Factor"] = [
        table.price_factor(key, day) for key, day in zip(keys, dates)
    ]
    for column in ("Open", "High", "Low", "Close"):
        if column in working.columns:
            working[f"Adj_{column}"] = pd.to_numeric(
                working[column], errors="coerce"
            ) / working["Adj_Factor"]
    return working
