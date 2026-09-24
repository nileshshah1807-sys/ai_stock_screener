"""Market profiles: the per-exchange facts the shared pipeline needs.

The scoring layer is market-agnostic already. Every score in ``screener/scoring``,
every factor percentile in ``screener/factors.py`` and every stage label in
``screener/stage.py`` is cross-sectional *within one run's frame*, so a US run
ranks US stocks against US stocks without a single change to the model. What is
genuinely exchange-specific is a short list of plumbing facts -- which suffix
yfinance wants, which index is the benchmark, when the daily bar closes -- and
this module is where that list lives instead of being scattered as literals.

A profile supplies **defaults only**. Every environment variable keeps the name
and the precedence it has always had, so a run with ``MARKET`` unset resolves to
exactly the values the NSE pipeline used before this module existed. That is the
property that lets a second market land without disturbing the first.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

NSE = "NSE"
US = "US"

DEFAULT_MARKET = NSE


@dataclass(frozen=True)
class MarketProfile:
    """Exchange-specific defaults for one market."""

    code: str
    label: str
    # Appended to a bare symbol for yfinance. NSE needs ".NS"; US tickers are
    # already the vendor's own identifiers, so the suffix is empty rather than
    # special-cased at each call site.
    ticker_suffix: str
    currency: str
    currency_symbol: str
    timezone: str
    # Local wall-clock time after which the session's daily bar is treated as
    # final. NSE permits trade modifications through 16:15; the US close is
    # 16:00 ET with no equivalent modification window.
    bar_complete_after: str
    benchmark_symbol: str
    benchmark_fallback: str
    # Key into the registry in ``screener.universe``.
    universe_source: str
    # NSE publishes a monthly security-category and impact-cost file that the
    # execution overlay joins against. No US equivalent is freely available, so
    # this is None there and the overlay degrades to "Unavailable" rather than
    # inventing a number.
    liquidity_provider: str | None
    # Default for CUSTOM_WATCHLIST: a handful of the most liquid names, used
    # when SCAN_ALL_NSE is off and the run is a smoke test rather than a scan.
    fallback_symbols: tuple[str, ...]
    # Unioned into the fetched universe so a vendor outage degrades the run to
    # the most liquid names rather than emptying it. On a healthy run these are
    # already in the fetched list and the union is a no-op.
    safety_net_symbols: tuple[str, ...]
    # Headline indices for the Market page, as (yfinance symbol, label), in
    # display order. Chosen from what Yahoo actually serves: Nifty Microcap 250
    # has no Yahoo series, so the NSE set stops at Smallcap 250.
    headline_indices: tuple[tuple[str, str], ...] = ()


_NSE_PROFILE = MarketProfile(
    code=NSE,
    label="NSE",
    ticker_suffix=".NS",
    currency="INR",
    currency_symbol="₹",
    timezone="Asia/Kolkata",
    bar_complete_after="16:15",
    # Nifty 500 is the broadest liquid total-market proxy Yahoo serves for
    # India; ^NSEI is the fallback when it is unavailable.
    benchmark_symbol="^CRSLDX",
    benchmark_fallback="^NSEI",
    universe_source="nse_equity_l",
    liquidity_provider="nse_impact_cost",
    fallback_symbols=(
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    ),
    safety_net_symbols=(
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
        "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT",
        "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "BAJFINANCE", "HCLTECH",
        "WIPRO", "NESTLEIND", "POWERGRID", "NTPC", "M&M", "TMCV", "ONGC",
        "JSWSTEEL", "TATASTEEL", "ADANIENT", "COALINDIA", "DRREDDY", "CIPLA",
        "DIVISLAB", "TECHM", "GRASIM", "BRITANNIA", "EICHERMOT", "APOLLOHOSP",
        "HEROMOTOCO", "UPL", "BANKBARODA", "LICI", "ETERNAL", "DELHIVERY",
        "HUDCO", "IREDA",
    ),
    headline_indices=(
        ("^NSEI", "Nifty 50"),
        ("^CRSLDX", "Nifty 500"),
        ("NIFTYMIDCAP150.NS", "Nifty Midcap 150"),
        ("NIFTYSMLCAP250.NS", "Nifty Smallcap 250"),
    ),
)

_US_PROFILE = MarketProfile(
    code=US,
    label="US",
    ticker_suffix="",
    currency="USD",
    currency_symbol="$",
    timezone="America/New_York",
    bar_complete_after="16:00",
    # ^GSPC is the S&P 500 index itself rather than the SPY tracker, so the
    # regime overlay reads index level rather than a fund's NAV. ^DJI is the
    # fallback purely because Yahoo serves it when ^GSPC is briefly missing.
    benchmark_symbol="^GSPC",
    benchmark_fallback="^DJI",
    universe_source="sp1500",
    liquidity_provider=None,
    fallback_symbols=(
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
        "META", "BRK-B", "JPM", "XOM", "UNH",
    ),
    # Every one of these is an S&P 500 member, so on a healthy run this union
    # adds nothing and cannot widen the universe past the configured index.
    safety_net_symbols=(
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "JPM",
        "XOM", "UNH", "V", "MA", "JNJ", "PG", "HD", "CVX", "LLY", "ABBV",
        "MRK", "KO", "PEP", "WMT", "COST", "CSCO", "ORCL", "CRM", "ADBE",
        "AMD", "INTC", "QCOM", "TXN", "CAT", "BA", "GE", "HON", "UNP",
        "T", "VZ", "DIS", "NFLX", "PFE", "TMO", "ABT", "MCD", "NKE",
    ),
    headline_indices=(
        ("^GSPC", "S&P 500"),
        ("^IXIC", "Nasdaq Composite"),
        ("^DJI", "Dow Jones Industrial"),
        ("^RUT", "Russell 2000"),
    ),
)

MARKETS: dict[str, MarketProfile] = {
    NSE: _NSE_PROFILE,
    US: _US_PROFILE,
}


def normalize_market(value) -> str:
    """Return a canonical market code, defaulting to NSE for empty input."""
    text = str(value or "").strip().upper()
    return text or DEFAULT_MARKET


def resolve(code) -> MarketProfile:
    """Return the profile for ``code``.

    Raises rather than falling back to NSE: a typo in ``MARKET`` would
    otherwise publish a US run's rows under the NSE market silently, which is
    the one failure mode that corrupts data instead of stopping the run.
    """
    market = normalize_market(code)
    try:
        return MARKETS[market]
    except KeyError:
        known = ", ".join(sorted(MARKETS))
        raise ValueError(f"Unknown market {market!r}; expected one of: {known}") from None


def active_profile(config=None) -> MarketProfile:
    """Resolve the market for a run from its config, then the environment.

    ``config`` may be a stub that predates this module -- the test suite is full
    of ``SimpleNamespace`` configs -- so a missing attribute falls through to
    ``MARKET`` and then to NSE rather than raising.
    """
    if config is not None:
        declared = getattr(config, "MARKET", None)
        if declared:
            return resolve(declared)
    return resolve(os.getenv("MARKET", DEFAULT_MARKET))


def ticker_for(symbol, profile: MarketProfile) -> str:
    """Return the vendor ticker for a bare symbol on this market."""
    return f"{str(symbol).strip().upper()}{profile.ticker_suffix}"


def bare_symbol(ticker, profile: MarketProfile) -> str:
    """Inverse of :func:`ticker_for`; tolerates an already-bare symbol."""
    text = str(ticker).strip().upper()
    suffix = profile.ticker_suffix
    if suffix and text.endswith(suffix):
        return text[: -len(suffix)]
    return text
