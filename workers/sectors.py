"""Sector pages: a cap-weighted index per sector, its valuation and members.

Published as R2 objects only (``sectors/{MARKET}/directory.json``, one
``sectors/{MARKET}/{slug}.json`` per sector and ``weights.json``, by
``DashboardRepository.put_sector_objects``); no table. During the session
``workers/live_quotes.py`` turns ``weights.json`` and its quotes into
``live/{MARKET}/sectors.json`` (``live_sector_changes``). Written by
``tools/publish_market_breadth.py`` from the same adjusted closes the breadth
charts use and the newest published run's snapshot.

Display evidence only: nothing here feeds a score. (Sector RS as a score input
was tested and rejected in P11.)

Choices worth stating:

* **Weights are each member's market cap at the previous close**: today's
  share count (the run's market cap over the last close) times that close. A
  member with no market cap in the run carries no weight.
* **A session a member did not trade is a session its price held**, as Yahoo
  draws it, so the level moves by what the members that did trade moved.
* **The universe is today's**, as for breadth: a company that left the sector
  is not in its past.
* **A missing value is not a zero.** Cap-weighted P/E is total cap over total
  earnings over the companies with a positive P/E; the rest are counted apart.

Units follow the snapshot: ``pct_change_*`` and ``dividend_yield`` are percent,
``roe`` and ``revenue_growth`` are ratios.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

from screener.markets import is_bse_only
from screener.numeric import round_half_up, round_series_half_up, safe_float
from workers.market_breadth import _as_series, _delta_list, encode_sessions

logger = logging.getLogger(__name__)

# Snapshot columns a sector object carries, and the short key each is published under.
FIELDS = {
    "company": "c",
    "market_cap": "mc",
    "pe_ratio": "pe",
    "pb_ratio": "pb",
    "roe": "roe",
    "dividend_yield": "dy",
    "revenue_growth": "rg",
    "pct_change_1d": "d1",
    "pct_change_3m": "m3",
    "pct_change_12m": "y1",
    "median_turnover_20d_inr": "tv",
}
SNAPSHOT_FIELDS = ("sector", "industry", *FIELDS)

# NSE's classification replaces Yahoo's sectors once it covers this share of the NSE symbols.
NSE_SECTOR_COVERAGE = 0.9

# P/E bucket upper bounds; the last bucket is open.
PE_EDGES = (10, 15, 20, 30, 50, 100)


def sector_slug(name: str) -> str:
    """'Oil, Gas & Consumable Fuels' -> 'oil-gas-consumable-fuels' (lib/indices.mjs' rule)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "")).strip("-")


def close_panel(observations, sessions, symbols) -> np.ndarray:
    """(session x symbol) closes, carried forward after each symbol's first bar."""
    position_of = {day: index for index, day in enumerate(sessions)}
    session_set = set(position_of)
    closes = np.full((len(sessions), len(symbols)), np.nan)
    for column, symbol in enumerate(symbols):
        series = _as_series(observations.get(symbol, {}), session_set)
        if series is None:
            continue
        closes[[position_of[day] for day in series.index], column] = series.to_numpy()
    return pd.DataFrame(closes).ffill().to_numpy()


def sector_levels(closes: np.ndarray, shares: np.ndarray) -> np.ndarray:
    """A cap-weighted index of one group's members, 100 on its first session."""
    if len(closes) == 0:
        return np.array([])
    previous, current = closes[:-1], closes[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        weights = previous * shares
        weights = np.where(np.isfinite(weights) & np.isfinite(current) & (weights > 0), weights, 0.0)
        moves = np.where(weights > 0, current / previous - 1.0, 0.0)
        total = weights.sum(axis=1)
        returns = np.where(total > 0, (weights * moves).sum(axis=1) / total, 0.0)
    return 100.0 * np.concatenate([[1.0], np.cumprod(1.0 + returns)])


def _median(values) -> float | None:
    finite = [value for value in values if value is not None]
    return float(np.median(finite)) if finite else None


def sector_summary(rows) -> dict:
    """Valuation and the run's breadth for one sector's snapshot rows."""
    caps = [safe_float(row.get("market_cap")) for row in rows]
    pes = [safe_float(row.get("pe_ratio")) for row in rows]
    total_cap = sum(cap for cap in caps if cap and cap > 0)
    earning = [(cap, pe) for cap, pe in zip(caps, pes) if cap and cap > 0 and pe and pe > 0]
    earnings = sum(cap / pe for cap, pe in earning)
    positive_pe = [pe for pe in pes if pe and pe > 0]
    changes = [change for change in (safe_float(row.get("pct_change_1d")) for row in rows) if change is not None]
    pbs = [safe_float(row.get("pb_ratio")) for row in rows]
    return {
        "count": len(rows),
        "total_cap": total_cap or None,
        "cap_weighted_pe": sum(cap for cap, _ in earning) / earnings if earnings > 0 else None,
        "median_pe": _median(positive_pe),
        "median_pb": _median([pb for pb in pbs if pb and pb > 0]),
        "median_roe": _median([safe_float(row.get("roe")) for row in rows]),
        "median_yield": _median([safe_float(row.get("dividend_yield")) for row in rows]),
        "no_positive_pe": len(rows) - len(positive_pe),
        "advancing": sum(change > 0 for change in changes),
        "declining": sum(change < 0 for change in changes),
        "traded": len(changes),
    }


def pe_buckets(rows, edges=PE_EDGES) -> list[dict]:
    """Companies with a positive P/E, counted into ``edges``' buckets."""
    counts = [0] * (len(edges) + 1)
    for row in rows:
        pe = safe_float(row.get("pe_ratio"))
        if pe is None or pe <= 0:
            continue
        counts[next((index for index, edge in enumerate(edges) if pe < edge), len(edges))] += 1
    labels = [f"<{edges[0]}"] + [f"{low}–{high}" for low, high in zip(edges, edges[1:])] + [f"{edges[-1]}+"]
    return [{"label": label, "count": count} for label, count in zip(labels, counts)]


def level_changes(days: list[date], levels: np.ndarray) -> dict:
    """Percent change over 1 session, 1 month and 1 year; None where the level does not reach back."""
    if len(levels) < 2:
        return {"d1": None, "m1": None, "y1": None}
    last_day = days[-1]

    def back(months: int):
        year, month = divmod(last_day.month - 1 - months, 12)
        cutoff = date(last_day.year + year, month + 1, min(last_day.day, 28))
        if days[0] > cutoff:
            return None
        index = max(position for position, day in enumerate(days) if day <= cutoff)
        return _pct(levels[-1], levels[index])

    return {"d1": _pct(levels[-1], levels[-2]), "m1": back(1), "y1": back(12)}


def _pct(now, then):
    # + 0.0 turns a rounded -0.0 into 0.0, so a flat session never reads "-0.00%".
    return round_half_up((now / then - 1.0) * 100, 2) + 0.0 if then > 0 else None


def _member(row) -> dict:
    out = {"s": row["symbol"]}
    for field, key in FIELDS.items():
        value = row.get(field)
        out[key] = value if field == "company" else safe_float(value)
    if row.get("nse_industry"):
        out["in"] = row["nse_industry"]
    return out


def nse_sector_rows(rows, classified: dict[str, dict]):
    """``rows`` grouped by NSE's sector (``workers/nse_sectors.py``) instead of Yahoo's.

    ``classified`` is ``{symbol: {"sector", "industry", ...}}``, the worker's rows;
    each row gains ``nse_industry`` (None where NSE did not classify it). A symbol NSE has not classified
    (a BSE-only name, which NSE does not quote, or one not asked yet) takes the
    NSE sector most of its Yahoo industry's classified members are in, when at
    least two are and over half of them agree; otherwise it has no sector and
    is left off the pages. Until the classification covers NSE_SECTOR_COVERAGE
    of the NSE symbols, ``rows`` are returned unchanged, so the pages never mix
    the two schemes.
    """
    # NSE spells some sectors two ways across quotes (punctuation, case): one sector
    # per slug, under the spelling most of its stocks carry.
    spellings: dict[str, Counter] = {}
    for entry in classified.values():
        if entry.get("sector"):
            spellings.setdefault(sector_slug(entry["sector"]), Counter())[entry["sector"]] += 1
    canonical = {slug: counter.most_common(1)[0][0] for slug, counter in spellings.items()}
    for counter in spellings.values():
        if len(counter) > 1:
            logger.info("NSE sector spelt %d ways, read as one: %s", len(counter), dict(counter))
    sector_of = {
        symbol: canonical[sector_slug(entry["sector"])] for symbol, entry in classified.items() if entry.get("sector")
    }
    nse = [row for row in rows if not is_bse_only(row["symbol"])]
    covered = sum(1 for row in nse if sector_of.get(row["symbol"]))
    if not nse or covered < NSE_SECTOR_COVERAGE * len(nse):
        logger.info("NSE sectors cover %d of %d NSE symbols: sector pages stay on Yahoo's", covered, len(nse))
        return rows

    votes: dict[str, Counter] = {}
    for row in rows:
        if sector_of.get(row["symbol"]) and row.get("industry"):
            votes.setdefault(row["industry"], Counter())[sector_of[row["symbol"]]] += 1
    by_industry = {}
    for industry, counter in votes.items():
        sector, count = counter.most_common(1)[0]
        if count >= 2 and count > counter.total() / 2:
            by_industry[industry] = sector

    out, inferred, dropped = [], 0, 0
    for row in rows:
        sector = sector_of.get(row["symbol"])
        if not sector:
            sector = by_industry.get(row.get("industry"))
            inferred += sector is not None
            dropped += sector is None
        industry = (classified.get(row["symbol"]) or {}).get("industry") or None
        out.append({**row, "sector": sector, "nse_industry": industry})
    logger.info("NSE sectors: %d classified, %d by their industry, %d left off", covered, inferred, dropped)
    return out


def member_symbols(objects) -> dict:
    """``{symbol: slug}`` over every sector object: how a stock page finds its sector."""
    return {member["s"]: slug for slug, body in objects.items() for member in body["members"]}


def member_industries(objects) -> dict:
    """``{symbol: NSE industry}`` for every member NSE classified: the stock page's industry."""
    return {member["s"]: member["in"] for body in objects.values() for member in body["members"] if member.get("in")}


def build_sector_objects(observations, sessions, rows, *, market, run_date):
    """``(directory, {slug: sector})`` for every sector in the run's ``rows``."""
    by_sector: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("sector"):
            by_sector.setdefault(row["sector"], []).append(row)

    directory, objects = [], {}
    for name, members in sorted(by_sector.items()):
        slug = sector_slug(name)
        members = sorted(members, key=lambda row: -(safe_float(row.get("market_cap")) or 0))
        symbols = [row["symbol"] for row in members]
        closes = close_panel(observations, sessions, symbols)
        last = closes[-1] if len(closes) else np.full(len(symbols), np.nan)
        caps = np.array([safe_float(row.get("market_cap")) or np.nan for row in members])
        with np.errstate(divide="ignore", invalid="ignore"):
            shares = np.where((caps > 0) & (last > 0), caps / last, np.nan)
        traded = np.flatnonzero(np.isfinite(closes).any(axis=1)) if len(closes) else np.array([], int)
        start = int(traded[0]) if len(traded) else len(sessions)
        days = list(sessions[start:])
        levels = sector_levels(closes[start:], shares)

        summary = sector_summary(members)
        level = None
        if len(days) >= 2:
            hundredths = round_series_half_up(pd.Series(levels * 100), 0).astype(np.int64)
            level = {
                "sessions": encode_sessions(days),
                "series": json.dumps({"c": _delta_list(hundredths)}, separators=(",", ":")),
            }
        entry = {
            "name": name,
            "slug": slug,
            "last_session": days[-1].isoformat() if days else None,
            **level_changes(days, levels),
            **{key: summary[key] for key in ("count", "total_cap", "advancing", "declining", "traded")},
        }
        directory.append(entry)
        objects[slug] = {
            **entry,
            "market": market,
            "run_date": run_date,
            "summary": summary,
            "pe_buckets": pe_buckets(members),
            "level": level,
            "members": [_member(row) for row in members],
        }
    if len({entry["slug"] for entry in directory}) != len(directory):
        raise ValueError("Two sectors share a slug")
    return {"market": market, "run_date": run_date, "sectors": directory}, objects


def member_weights(objects) -> dict:
    """``{slug: {"last_session", "members": [[symbol, market_cap], ...]}}``: what ``live_sector_changes`` needs."""
    return {
        slug: {"last_session": body["last_session"], "members": [[m["s"], m["mc"]] for m in body["members"]]}
        for slug, body in objects.items()
    }


def live_sector_changes(weights, quotes) -> list[dict]:
    """Each sector's cap-weighted change in the quotes' session, by the level's own rule.

    ``quotes`` maps symbol to a live quote (``session``, ``change_pct`` in
    percent, against the previous close). A member weighs its market cap at
    the last close; one that has not traded this session held its price; a
    withheld change (a change of unit) or a member with no quote is left out
    of both sides. A sector whose close already covers the session is
    omitted, since its close is the figure.
    """
    session = max((quote["session"] for quote in quotes.values() if quote.get("session")), default=None)
    out = []
    for slug, sector in weights.items():
        if session is None or not sector.get("last_session") or sector["last_session"] >= session:
            continue
        weighted = total = 0.0
        advancing = declining = traded = 0
        for symbol, cap in sector["members"]:
            quote = quotes.get(symbol)
            if quote is None:
                continue
            if quote.get("session") == session:
                change = safe_float(quote.get("change_pct"))
                if change is None:
                    continue
                traded += 1
                advancing += change > 0
                declining += change < 0
            else:
                change = 0.0
            if cap and cap > 0:
                weighted += cap * change
                total += cap
        if traded:
            d1 = round_half_up(weighted / total, 2) + 0.0 if total else None
            out.append({"slug": slug, "session": session, "d1": d1, "advancing": advancing, "declining": declining, "traded": traded})
    return out
