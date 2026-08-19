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
"""

from __future__ import annotations

from datetime import date, datetime
import logging
from pathlib import Path
import re

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
_BONUS_RE = re.compile(r"bonus\s*(?:issue)?\s*(\d+)\s*:\s*(\d+)", re.IGNORECASE)

# A "Bonus NCRPS 4:1" awards four non-convertible redeemable *preference* shares
# per equity share held. The equity share count does not change, so the ratio is
# emphatically not an equity price factor -- applying TVSMOTOR's 4:1 as one would
# turn its ~1.5% ex-date drop into a fabricated +400% return. These are matched
# explicitly and routed to the unadjustable path rather than being left to miss
# the bonus pattern by luck.
_PREFERENCE_BONUS_RE = re.compile(
    r"\b(?:ncrps|ncps|nccrps|preference\s+share)", re.IGNORECASE
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


def classify_action(subject):
    """Coarse action type from the NSE subject text."""
    text = str(subject or "").strip().lower()
    if not text:
        return ACTION_UNKNOWN
    # Order matters: a subject can mention several things, and the structural
    # action dominates the cash one.
    if "split" in text or "sub-division" in text or "sub division" in text:
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
        # Preference-share bonuses leave the equity count untouched, so their
        # ratio must never reach the price factor. They still move the price by
        # the value distributed, which no ratio here captures, so they block.
        if _PREFERENCE_BONUS_RE.search(text):
            return action, None, None, "unadjustable_preference_bonus"
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
        """Fetch, normalise, cache and return actions for ``[start, end]``."""
        from tempfile import TemporaryDirectory

        start, end = _as_date(start), _as_date(end)
        with TemporaryDirectory(prefix="nse_actions_") as folder:
            with self._make_nse(folder) as nse:
                records = nse.actions(
                    segment="equities",
                    from_date=datetime.combine(start, datetime.min.time()),
                    to_date=datetime.combine(end, datetime.max.time()),
                )
        frame = normalise_actions(records)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(self.path, index=False)
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
            key = self._key(record.get("ISIN"))
            if key is None:
                continue
            ex_date = _parse_ex_date(record.get("Ex_Date"))
            if ex_date is None:
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

    def _key(self, isin):
        isin = str(isin or "").strip().upper()
        if not isin:
            return None
        if self.master is not None:
            resolved = self.master.security_id_for_isin(isin)
            if resolved:
                return resolved
        return isin

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
